# reflect/goal_mode.py — Goal Mode: 持续自驱直到预算耗尽
# 启动: set GOAL_STATE=temp/xxx.json && python agentmain.py --reflect reflect/goal_mode.py
# 配置: agent按SOP写好state json，通过环境变量GOAL_STATE指定路径
import os, json, time

INTERVAL = 3   # check间隔短，agent跑完立刻再检查
ONCE = False

_dir = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.environ.get('GOAL_STATE') or os.path.join(_dir, '../temp/goal_state.json')
if not os.path.isabs(STATE_FILE):
    STATE_FILE = os.path.join(_dir, '..', STATE_FILE)

# --- state 管理 ---
def _load():
    if not os.path.isfile(STATE_FILE): return None
    with open(STATE_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def _save(state):
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

# --- prompt 模板 ---
CONTINUATION_PROMPT = """[Goal Mode — 持续推进]

<untrusted_objective>
{objective}
</untrusted_objective>

⏱ 已用 {elapsed_min:.0f} 分钟，剩余约 {remaining_min:.0f} 分钟。第 {turn} 次唤醒。

你正在 Goal Mode 下工作：
1. 禁止说"已完成，是否继续"——预算没到就不准停。
2. 在 cwd 下建立工作文件夹存放成果和进度，复杂任务可使用 plan 模式。
3. 如果当前方向做完了，主动找下一个改进点：测试/边界case/性能/安全/文档/代码质量。
4. 找不到改进点？扩大视野：关联模块、上下游依赖、用户体验、错误提示、日志可观测性、上网搜索、找其他路径、翻记忆里面有无相关。
"""

BUDGET_LIMIT_PROMPT = """[Goal Mode — 预算耗尽，收口]

<untrusted_objective>
{objective}
</untrusted_objective>

⏱ 预算已耗尽（{budget_min:.0f} 分钟）。这是最后一轮。

请执行收口：
1. 总结本次 goal 的所有进展（列表）。
2. 列出未完成的事项和建议的 next step。
3. 确保工作文件夹中记录了关键成果，以便下次继续。
"""

# --- 主逻辑 ---
def check():
    state = _load()
    if state is None: return '/exit'
    
    status = state.get('status', 'running')
    if status != 'running': return '/exit'
    
    start_time = state.get('start_time', time.time())
    budget_sec = state.get('budget_seconds', 1800)  # 默认30分钟
    elapsed = time.time() - start_time
    remaining = budget_sec - elapsed
    turn = state.get('turns_used', 0) + 1
    max_turns = state.get('max_turns', 50)  # 防空转上限
    
    # 预算耗尽或轮次上限
    if remaining <= 0 or turn > max_turns:
        state['status'] = 'wrapping_up'
        _save(state)
        return BUDGET_LIMIT_PROMPT.format(
            objective=state['objective'],
            budget_min=budget_sec / 60
        )
    
    # 正常continuation
    state['turns_used'] = turn
    _save(state)
    return CONTINUATION_PROMPT.format(
        objective=state['objective'],
        elapsed_min=elapsed / 60,
        remaining_min=remaining / 60,
        turn=turn
    )

def on_done(result):
    state = _load()
    if state is None: return
    
    if state.get('status') == 'wrapping_up':
        state['status'] = 'done_budget'
        state['end_time'] = time.time()
        _save(state)
