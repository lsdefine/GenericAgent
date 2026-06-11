# reflect/goal_mode.py — Goal Mode: 持续自驱直到预算耗尽
# 启动: set GOAL_STATE=temp/xxx.json && python agentmain.py --reflect reflect/goal_mode.py
# 配置: agent按SOP写好state json，通过环境变量GOAL_STATE指定路径
import os, json, time

INTERVAL = 5   # check间隔短，agent跑完立刻再检查
ONCE = False

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
CONTINUATION_PROMPT = """[Goal Mode — 持续优化]

<objective>
{objective}
</objective>

⏱ 已用 {elapsed_min:.0f} 分钟，剩余约 {remaining_min:.0f} 分钟。第 {turn} 次唤醒。

你正在 Goal Mode 下工作：无法宣告完成，你会被无法阻止地持续唤醒直到预算耗尽
唤醒后流程（3选1）：
1. 创造阶段(第一次唤醒)：分析objective，在cwd建工作文件夹，严格按照objective执行
2. 检验阶段：从不同视角检验创造结果，产出检验报告
    - 换身份查看（读者/受众/用户/测试工程师/领导） | 设计未跑过的更难测例 | 查素材/事实/引用的真实性与数量/说服力 | 代码质量/产物格式/美观 | 实测验证(亲自执行/模拟用户操作)
    - 按任务类型**轮换**选用合适的角色和方法
    - 在遵循原始需求约束下追求超预期，拒绝保守和平庸，必须提出“不够出色”的点
    - 先保及格线（无事实错误/乱码/格式错误，能运行，过基础测例，遵循用户约束），及格同时追求出色
3. 改进阶段：针对检验报告优化改进交付物，必须实质性改进

原则：
1. 每次唤醒**交替**进行检验阶段和改进阶段，保留每次的检验报告和改进changelog。
2. 除非发现严重问题，不要对创造结果进行完全重写，而是改进
3. 严格区分交付物和进度报告，交付物中不要混入`已检验`等中间信息
4. 若检验都是无关紧要问题，下次升级检验（要求更出色产物/更苛刻视角/更难测试/对照原始需求重审/开subagent第三方评审）
5. 改进阶段禁止产出"无改动"。若检验未发现值得改的点，说明检验标准太低——本轮产出"检验标准升级报告"，论证当前标准为何不够高并提出新标准，下轮按新标准重新检验。
6. 在工作文件夹中记录进度，不要更新全局记忆
7. 所有阶段都建议进行充分调研：web调研、查看记忆和相关SOP、获取用户倾向
8. 禁止进行sha1等无用验证，文件版本不会出错
"""

BUDGET_LIMIT_PROMPT = """[Goal Mode — 预算耗尽，收口]

<objective>
{objective}
</objective>

⏱ 预算已耗尽（{budget_min:.0f} 分钟）。这是最后一轮。

请执行收口：
1. 总结本次 goal 的所有进展（列表）
2. 列出未完成的事项和建议的 next step
3. 确保工作文件夹中记录了关键成果
4. 清理一些确定无用的中间临时文件和不再用的进程
{done_prompt}
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
            budget_min=budget_sec / 60,
            done_prompt=state.get('done_prompt', '')
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
