# reflect/goal_mode.py — Goal Mode: bounded self-drive loop
# 启动: set GOAL_STATE=temp/xxx.json && python agentmain.py --reflect reflect/goal_mode.py
# 配置: agent按SOP写好state json，通过环境变量GOAL_STATE指定路径
import os, json, time

INTERVAL = 5   # check间隔短，agent跑完立刻再检查
ONCE = False
READY_MARKER = '[GOAL_READY_TO_WRAP]'

_dir = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = ''
def init(a):
    global STATE_FILE
    STATE_FILE = a.get('goal_state') or os.environ.get('GOAL_STATE') or os.path.join(_dir, '../temp/goal_state.json')
    if not os.path.isabs(STATE_FILE): STATE_FILE = os.path.join(_dir, '..', STATE_FILE)
# --- state 管理 ---
def _load():
    if not os.path.isfile(STATE_FILE): return None
    with open(STATE_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def _save(state):
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

# --- prompt 模板 ---
CONTINUATION_PROMPT = """[Goal Mode — 持续优化（预算上限）]

<objective>
{objective}
</objective>

⏱ 已用 {elapsed_min:.0f} 分钟，剩余约 {remaining_min:.0f} 分钟。第 {turn} 次唤醒。

你正在 Goal Mode 下工作：预算是上限，不是必须花完的最低消费。除非 objective 明确要求跑满预算，达到可交付线后应主动收口，避免无收益复检。
唤醒后流程（择一）：
1. 创造阶段(第一次唤醒)：分析objective，在cwd建工作文件夹，严格按照objective执行
2. 检验阶段：从不同视角检验创造结果，产出检验报告
    - 换身份查看（读者/受众/用户/测试工程师/领导） | 设计未跑过的更难测例 | 查素材/事实/引用的真实性与数量/说服力 | 代码质量/产物格式/美观 | 实测验证(亲自执行/模拟用户操作)
    - 按任务类型**轮换**选用合适的角色和方法
    - 在遵循原始需求约束下追求超预期，拒绝保守和平庸，必须提出“不够出色”的点
    - 先保及格线（无事实错误/乱码/格式错误，能运行，过基础测例，遵循用户约束），及格同时追求出色
3. 改进阶段：针对检验报告优化改进交付物，必须实质性改进
4. 收口申请：若产物已满足用户目标、连续复检只剩主观偏好/低价值润色、或继续投入会让成本高于收益，停止新调查和新 worker，回复最后一行单独输出：{ready_marker}

原则：
1. 每次唤醒在检验/改进/收口申请中择一；有明确 P0/P1 才继续改。
2. 除非发现严重问题，不要对创造结果进行完全重写，而是改进
3. 严格区分交付物和进度报告，交付物中不要混入`已检验`等中间信息
4. 若检验都是无关紧要问题，先对照用户目标判断是否已达标；达标则收口，不要为了消耗预算升级标准。
5. 改进阶段禁止产出"无改动"。若没有值得改的点且已达标，走收口申请。
6. 在工作文件夹中记录进度，不要更新全局记忆
7. 所有阶段都建议进行充分调研：web调研、查看记忆和相关SOP、获取用户倾向
8. 禁止进行sha1等无用验证，文件版本不会出错
"""

CLOSEOUT_PROMPT = """[Goal Mode — 收口]

<objective>
{objective}
</objective>

⏱ 收口原因：{reason}。预算上限 {budget_min:.0f} 分钟，已用 {elapsed_min:.0f} 分钟。这是最后一轮。

请执行收口，不要重新复检：
1. 总结本次 goal 的所有进展（列表）
2. 列出未完成的事项和建议的 next step
3. 确保工作文件夹中记录了关键成果
4. 清理一些确定无用的中间临时文件和不再用的进程
{done_prompt}
"""

def _closeout(state, reason):
    state['status'] = 'wrapping_up'
    state['wrap_reason'] = reason
    state['wrap_started_at'] = time.time()
    _save(state)
    start_time = state.get('start_time', time.time())
    budget_sec = state.get('budget_seconds', 1800)
    return CLOSEOUT_PROMPT.format(
        objective=state['objective'],
        reason=reason,
        budget_min=budget_sec / 60,
        elapsed_min=(time.time() - start_time) / 60,
        done_prompt=state.get('done_prompt', '')
    )

def _ready(result):
    lines = [l.strip() for l in (result or '').splitlines() if l.strip()]
    return bool(lines and lines[-1] == READY_MARKER)

# --- 主逻辑 ---
def check():
    state = _load()
    if state is None: return '/exit'
    
    status = state.get('status', 'running')
    if status == 'ready_to_wrap':
        return _closeout(state, state.get('wrap_reason', 'goal_ready'))
    if status != 'running': return '/exit'
    
    start_time = state.get('start_time', time.time())
    budget_sec = state.get('budget_seconds', 1800)  # 默认30分钟
    elapsed = time.time() - start_time
    remaining = budget_sec - elapsed
    turn = state.get('turns_used', 0) + 1
    max_turns = state.get('max_turns', 50)  # 防空转上限
    
    # 预算耗尽或轮次上限
    if remaining <= 0: return _closeout(state, 'budget_exhausted')
    if turn > max_turns: return _closeout(state, 'max_turns')
    
    # 正常continuation
    state['turns_used'] = turn
    _save(state)
    return CONTINUATION_PROMPT.format(
        objective=state['objective'],
        elapsed_min=elapsed / 60,
        remaining_min=remaining / 60,
        turn=turn,
        ready_marker=READY_MARKER
    )

def on_done(result):
    state = _load()
    if state is None: return
    
    if state.get('status') == 'wrapping_up':
        reason = state.get('wrap_reason', 'budget_exhausted')
        state['status'] = 'done_budget' if reason == 'budget_exhausted' else 'done_ready'
        state['end_time'] = time.time()
        _save(state)
    elif state.get('status') == 'running' and _ready(result):
        state['status'] = 'ready_to_wrap'
        state['wrap_reason'] = 'goal_ready'
        state['ready_at'] = time.time()
        _save(state)
