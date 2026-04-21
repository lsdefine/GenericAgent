# -*- coding: utf-8 -*-
"""P2.1 PHASE C 隔离沙盒: 强制反向并发证据 (物理级时序锁定)

不启 HeartbeatProducer, 不投大任务, 纯 fake_heartbeat 先占锁 -> put_task(user) 撞锁.

期望 5 行严格顺序 (由 threading.Event 物理同步保证):
  1 [Heartbeat] lock acquired (forced first)
  2 [UserTurn] queued, waiting lock           <- agentmain.py L213-214 埋点
  3 [Heartbeat] releasing lock
  4 [UserTurn] lock acquired, processing...   <- agentmain.py L216 埋点
  5 [PHASE C] forced race completed
"""
import sys, os, time, threading, io

# UTF-8 行缓冲, 防 emoji 乱码 + 日志实时落盘
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', line_buffering=True)

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
sys.path.insert(0, HERE)

print(f"[ACC-C] cwd={os.getcwd()}", flush=True)
from agentmain import GeneraticAgent  # 项目实拼写, 不是 Generic

agent = GeneraticAgent()
agent.next_llm(0)
agent.verbose = False
threading.Thread(target=agent.run, daemon=True).start()
# 关键: 不起 HeartbeatProducer, 消除真实 HB 对锁的持续争抢
print(f"[ACC-C] agent 启动,llm={agent.get_llm_name()} (无真实 HB, 隔离沙盒)", flush=True)

# 等 agent.run 线程进入 queue.get() 阻塞态
time.sleep(0.5)

print("\n" + "="*68, flush=True)
print("[ACC-C] ===== PHASE C: FORCED RACE (隔离沙盒 / 物理同步) =====", flush=True)
print("="*68, flush=True)

event_hb_holding  = threading.Event()
event_hb_released = threading.Event()

def fake_heartbeat():
    # TrackedLock 支持 with 语义 (agentmain.py L30+ 封装)
    with agent.llm_busy_lock:
        print("[Heartbeat] lock acquired (forced first)", flush=True)
        event_hb_holding.set()
        # 给 user task 充分窗口穿过 L213 queued 分支 + 进 L215 acquire 阻塞
        time.sleep(2.0)
        print("[Heartbeat] releasing lock", flush=True)
    event_hb_released.set()

t_hb = threading.Thread(target=fake_heartbeat, daemon=True)
t_hb.start()

# 硬断言 1: HB 真拿到锁 (3s 内必达, 无真实竞争者)
if not event_hb_holding.wait(timeout=3.0):
    print("FATAL: HB did not acquire lock in time", flush=True)
    os._exit(1)

# 兼容 property / 方法两种封装, 杜绝 TypeError
_locked_attr = agent.llm_busy_lock.locked
is_locked = _locked_attr if isinstance(_locked_attr, bool) else _locked_attr()
assert is_locked, "FATAL: Lock is not held by external thread"

# 投 user 任务 -> agent.run 线程 get -> L213 检查 locked=True -> 打印 queued -> L215 阻塞
agent.put_task("phase-c probe message", source="user")

# 等 HB 自然释放 (sleep 2.0s 后)
event_hb_released.wait(timeout=5.0)
t_hb.join(timeout=2.0)

# 关键防御: 让出 CPU 给 run() 线程完成 acquire + 打印 [UserTurn] lock acquired...
# 没这 0.5s, 主线程的 forced race completed 可能先于 run() 的日志, 破坏 5 行判据顺序
time.sleep(0.5)

print("[PHASE C] forced race completed", flush=True)
time.sleep(0.3)  # 最后日志 flush
os._exit(0)
