"""DSML v7 验收测试：误执行 0，漏检 0。

覆盖 5 类：
 A. 危险例（正文里被讨论/引用的标签）—— 绝不能执行
 B. 漏检例（真实泄漏形态）—— 必须救回
 C. DSML 标记变体（| ｜ ‖ 单/双/三、开/闭标签、跨 chunk）
 D. arguments 侧污染（上游 #846-B）
 E. 散文/代码区否决不产生假重试
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
import llmcore as L

NAMES = {'code_run', 'code_exec', 'ask_user', 'web_scan', 'web_execute_js',
         'file_read', 'file_write', 'file_patch', 'update_working_checkpoint'}
PASS = FAIL = 0
fails = []


def check(name, cond, detail=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        fails.append(f"{name}  {detail}")
        print(f"  FAIL {name}  {detail}")


def calls_of(text):
    return L.salvage_leaked_tool_calls(text, NAMES)[0]


# ---------------- A. 危险例：一个都不许执行 ----------------
print("\n== A. 危险例（正文引用/讲解）应 0 执行")
DANGER = {
    '讨论句带 cwd': '引擎不会输出 <code_run cwd="/tmp"> 这种标记，请放心。',
    '反引号裸标签': '<summary>发现 `<code_run>` 抢救有误判风险</summary>',
    '反引号带属性': '真实形态：`<code_run script="bash" cwd="/tmp">` 这种',
    '反引号含完整调用': '看到 `<code_run>print(1)</code_run>` 这种就说明泄漏了',
    '围栏代码块': '用法：\n```\n<code_run script="bash">rm -rf /tmp/x</code_run>\n```\n就这样。',
    '函数名提及': '你可以用 code_run 来跑脚本，参数是 script。',
    '行内提及 dsml': '最近的 commit 加了 DSML 检测，但还不够保底。',
}
for n, t in DANGER.items():
    c = calls_of(t)
    check(f"A/{n}", len(c) == 0, f"误执行 {[(x.function.name, x.function.arguments[:50]) for x in c]}")

# ---------------- B. 漏检例：都必须救回 ----------------
print("\n== B. 真实泄漏形态应救回")
LEAK = [
    ('行内真泄漏', '<summary>查一下</summary>\n先跑 <code_run script="bash" cwd="/tmp">ls -l</code_run> 看结果', 'code_run', {'cwd': '/tmp'}),
    ('行首裸脚本', '<summary>查一下</summary>\n<code_run>\nimport os\nprint(os.getcwd())\n</code_run>', 'code_run', None),
    ('调用后带说明', '<code_run script="bash">ls -l</code_run>\n\n以上命令用于列出目录。', 'code_run', None),
    ('调用后带 summary', '<code_run script="bash">ls -l</code_run>\n<summary>已执行</summary>', 'code_run', None),
    ('JSON 体', '<code_run>{"script": "ls -l"}</code_run>', 'code_run', None),
    ('压平单行', '<code_run>script: echo hi</code_run>', 'code_run', None),
    ('裸子标签 ask_user', '<ask_user>\n<question>which one?</question>\n<candidates><item>a</item><item>b</item></candidates>\n</ask_user>', 'ask_user', None),
    ('标签名后多引号', '<code_run">ls -l</code_run>', 'code_run', None),
]
for n, t, want_name, want_args in LEAK:
    c = calls_of(t)
    ok = bool(c) and c[0].function.name == want_name
    if ok and want_args:
        a = json.loads(c[0].function.arguments)
        ok = all(a.get(k) == v for k, v in want_args.items())
    check(f"B/{n}", ok, f"calls={[(x.function.name, x.function.arguments[:70]) for x in c]}")

# JSON 体不能被二次包装
c = calls_of('<code_run>{"script": "ls -l"}</code_run>')
_a = json.loads(c[0].function.arguments) if c else {}
check("B/JSON体不二次包装", _a.get('script') == 'ls -l', str(_a))
# 裸子标签多值要变列表
c = calls_of('<ask_user>\n<question>which one?</question>\n<candidates><item>a</item><item>b</item></candidates>\n</ask_user>')
a = json.loads(c[0].function.arguments) if c else {}
check("B/裸子标签多值成列表", a.get('candidates') == ['a', 'b'] and a.get('question') == 'which one?', str(a))

# ---------------- C. DSML 变体 ----------------
print("\n== C. DSML 标记变体剥离")
B = chr(0xFF5C); U = chr(0x2016)
for label, s, want in [
    ('单ASCII竖线', f'A</{chr(124)}DSML{chr(124)} parameter>B', 'AB'),
    ('全角竖线', f'A</{B}DSML{B} parameter>B', 'AB'),
    ('双ASCII竖线', f'A</||DSML|| parameter>B', 'AB'),
    ('双全角竖线', f'A</{B}{B}DSML{B}{B} parameter>B', 'AB'),
    ('U+2016双竖线', f'A<{U}DSML{U}tool_calls>B', 'AB'),
    ('开标签带属性', f'A<{chr(124)}DSML{chr(124)}invoke name="x">B', 'AB'),
    ('dsml_下划线式', 'A<dsml_parameter name="p">B', 'AB'),
    ('无标记不误伤', 'A < b and c > d', 'A < b and c > d'),
]:
    got = L._strip_dsml_tags(s)
    check(f"C/{label}", got == want, f"{got!r}")

# 跨 chunk
f = L.DsmlStreamFilter()
out = f.feed('hello<|') + f.feed('|DSML||tool_calls>') + f.feed('world') + f.flush()
check("C/跨chunk剥离", out == 'helloworld', repr(out))
f = L.DsmlStreamFilter()
out = f.feed('a<') + f.flush()
check("C/跨chunk不吞正常<", out == 'a<', repr(out))

# ---------------- D. arguments 侧 ----------------
print("\n== D. arguments 侧污染")
raw = '{"path": "/tmp/a.txt"}</' + '||DSML|| parameter>'
got = L._try_parse_tool_args(raw)
check("D/arguments剥标记后可解析", got and got[0].get('path') == '/tmp/a.txt', str(got))
got = L._try_parse_tool_args('{"script": "if a < b: pass"}')
check("D/正常脚本含<不受影响", got and got[0].get('script') == 'if a < b: pass', str(got))
got = L._try_parse_tool_args('{bad json')
check("D/坏 JSON 退回 _raw 不抛", got and '_raw' in got[0], str(got))

# ---------------- E. 假重试 / 真重试判定 ----------------
print("\n== E. 泄漏类别与截断判定")
check("E/讨论句不算泄漏", L.leaked_markup_kind('<summary>不会输出 <code_run cwd="/tmp"> 这种</summary>', NAMES) == '',
      repr(L.leaked_markup_kind('<summary>不会输出 <code_run cwd="/tmp"> 这种</summary>', NAMES)))
check("E/围栏示例不算泄漏", L.leaked_markup_kind('```\n<code_run>x</code_run>\n```', NAMES) == '', '')
check("E/真泄漏算泄漏", L.leaked_markup_kind('<code_run script="bash">ls</code_run>', NAMES) != '', '')
check("E/讨论句不算截断", L.leaked_markup_incomplete('不会输出 <code_run cwd="/tmp"> 这种标记') is False, '')
check("E/截断残片算截断", L.leaked_markup_incomplete('<code_run">') is True, '')
check("E/闭合调用不算截断", L.leaked_markup_incomplete('<code_run script="bash">ls</code_run>') is False, '')

print(f"\n{'='*50}\n通过 {PASS} / 失败 {FAIL}")
if fails:
    print("失败项：")
    for f_ in fails: print("  -", f_)
sys.exit(1 if FAIL else 0)
