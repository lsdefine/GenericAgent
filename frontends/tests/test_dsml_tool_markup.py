"""伪工具调用（DSML / XML 风格）救回机制验收测试。

关键约束：
 A. 危险例（正文里被讨论/引用的标签）—— 绝不能执行
 B. 漏检例（真实泄漏形态）—— 必须救回
 C. DSML 标记变体（| ｜ ‖ 单/双/三、开/闭标签、跨 chunk）
 D. arguments 侧污染（上游 #846-B）
 E. 散文/代码区否决，不产生假重试
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
import llmcore as L

NAMES = {'code_run', 'code_exec', 'ask_user', 'web_scan', 'web_execute_js',
         'file_read', 'file_write', 'file_patch', 'update_working_checkpoint'}

DANGER = {
    '讨论句带 cwd': '引擎不会输出 <code_run cwd="/tmp"> 这种标记，请放心。',
    '反引号裸标签': '<summary>发现 `<code_run>` 抢救有误判风险</summary>',
    '反引号带属性': '真实形态：`<code_run script="bash" cwd="/tmp">` 这种',
    '反引号含完整调用': '看到 `<code_run>print(1)</code_run>` 这种就说明泄漏了',
    '围栏代码块': '用法：\n```\n<code_run script="bash">rm -rf /tmp/x</code_run>\n```\n就这样。',
    '函数名提及': '你可以用 code_run 来跑脚本，参数是 script。',
    '行内提及 dsml': '最近的 commit 加了 DSML 检测，但还不够保底。',
}

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


def calls_of(text):
    return L.salvage_leaked_tool_calls(text, NAMES)[0]


@pytest.mark.parametrize('label,text', list(DANGER.items()))
def test_danger_cases_never_execute(label, text):
    """正文里被讨论/引用的标签，一个都不许执行。"""
    calls = calls_of(text)
    assert not calls, f"{label}: 误执行 {[(c.function.name, c.function.arguments[:50]) for c in calls]}"


@pytest.mark.parametrize('label,text,want_name,want_args', LEAK)
def test_leaked_forms_are_salvaged(label, text, want_name, want_args):
    """真实泄漏形态必须救回成工具调用。"""
    calls = calls_of(text)
    assert calls, f"{label}: 漏检"
    assert calls[0].function.name == want_name, f"{label}: 工具名 {calls[0].function.name}"
    if want_args:
        args = json.loads(calls[0].function.arguments)
        for k, v in want_args.items():
            assert args.get(k) == v, f"{label}: {k}={args.get(k)!r}"


def test_json_body_not_double_wrapped():
    """体内直接是 JSON 参数时，不能二次包装成 {"script": "{\"script\": ...}"}。"""
    calls = calls_of('<code_run>{"script": "ls -l"}</code_run>')
    assert json.loads(calls[0].function.arguments).get('script') == 'ls -l'


def test_bare_children_multi_value_becomes_list():
    calls = calls_of('<ask_user>\n<question>which one?</question>\n'
                     '<candidates><item>a</item><item>b</item></candidates>\n</ask_user>')
    args = json.loads(calls[0].function.arguments)
    assert args == {'question': 'which one?', 'candidates': ['a', 'b']}


@pytest.mark.parametrize('label,raw,want', [
    ('单ASCII竖线', f'A</{chr(124)}DSML{chr(124)} parameter>B', 'AB'),
    ('全角竖线', f'A</{chr(0xFF5C)}DSML{chr(0xFF5C)} parameter>B', 'AB'),
    ('双ASCII竖线', 'A</||DSML|| parameter>B', 'AB'),
    ('双全角竖线', f'A</{chr(0xFF5C) * 2}DSML{chr(0xFF5C) * 2} parameter>B', 'AB'),
    ('U+2016双竖线', f'A<{chr(0x2016)}DSML{chr(0x2016)}tool_calls>B', 'AB'),
    ('开标签带属性', f'A<{chr(124)}DSML{chr(124)}invoke name="x">B', 'AB'),
    ('dsml_下划线式', 'A<dsml_parameter name="p">B', 'AB'),
    ('无标记不误伤', 'A < b and c > d', 'A < b and c > d'),
])
def test_dsml_marker_variants(label, raw, want):
    assert L._strip_dsml_tags(raw) == want, label


def test_stream_filter_strips_across_chunks():
    f = L.DsmlStreamFilter()
    out = f.feed('hello<|') + f.feed('|DSML||tool_calls>') + f.feed('world') + f.flush()
    assert out == 'helloworld'


def test_stream_filter_keeps_trailing_angle_bracket():
    f = L.DsmlStreamFilter()
    assert f.feed('a<') + f.flush() == 'a<'


def test_arguments_side_marker_stripped():
    raw = '{"path": "/tmp/a.txt"}</' + '||DSML|| parameter>'
    assert L._try_parse_tool_args(raw)[0].get('path') == '/tmp/a.txt'


def test_arguments_with_lt_untouched():
    assert L._try_parse_tool_args('{"script": "if a < b: pass"}')[0].get('script') == 'if a < b: pass'


def test_bad_json_falls_back_without_raising():
    assert '_raw' in L._try_parse_tool_args('{bad json')[0]


def test_prose_mention_is_not_leak():
    assert L.leaked_markup_kind('<summary>不会输出 <code_run cwd="/tmp"> 这种</summary>', NAMES) == ''


def test_fenced_example_is_not_leak():
    assert L.leaked_markup_kind('```\n<code_run>x</code_run>\n```', NAMES) == ''


def test_real_leak_is_detected():
    assert L.leaked_markup_kind('<code_run script="bash">ls</code_run>', NAMES) != ''


def test_prose_mention_is_not_incomplete():
    assert L.leaked_markup_incomplete('不会输出 <code_run cwd="/tmp"> 这种标记') is False


def test_truncated_fragment_is_incomplete():
    assert L.leaked_markup_incomplete('<code_run">') is True


def test_closed_call_is_not_incomplete():
    assert L.leaked_markup_incomplete('<code_run script="bash">ls</code_run>') is False
