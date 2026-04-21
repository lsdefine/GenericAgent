# -*- coding: utf-8 -*-
"""P2.1 CTO 硬核令验收 driver
Phase A: 空闲突袭 (HB 10s, 不投任务) → 观察 💓 + 🔔
Phase B: 忙碌降级 (投大任务)          → 观察 L0-scan skipped
"""
import sys, os, time, threading, io

# UTF-8 输出,避免 emoji 乱码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', line_buffering=True)

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
sys.path.insert(0, HERE)

print(f"[ACC] cwd={os.getcwd()}", flush=True)
from agentmain import GeneraticAgent
from heartbeat import HeartbeatProducer

agent = GeneraticAgent()
agent.next_llm(0)
agent.verbose = False
threading.Thread(target=agent.run, daemon=True).start()
HeartbeatProducer(agent, interval_sec=10).start()
print(f"[ACC] agent 启动,llm={agent.get_llm_name()} HB interval=10s", flush=True)

# ===== Phase A: IDLE AMBUSH =====
print("\n" + "="*68, flush=True)
print("[ACC] ===== PHASE A: IDLE AMBUSH (25s 空闲观察,不碰键盘) =====", flush=True)
print("="*68, flush=True)
time.sleep(25)

# ===== Phase B: BUSY DEGRADATION =====
print("\n" + "="*68, flush=True)
print("[ACC] ===== PHASE B: BUSY DEGRADATION (投大任务,HB 应 skipped) =====", flush=True)
print("="*68, flush=True)

dq = agent.put_task(
    "给我写一段完整的贪吃蛇 Python 代码,要求含注释,越长越好",
    source="user"
)
# 观察 30s,期间 HB 应多次触发 L0-scan skipped
t0 = time.time()
got_done = False
while time.time() - t0 < 35:
    try:
        item = dq.get(timeout=1)
        if 'done' in item:
            got_done = True
            print(f"[ACC] Phase B LLM done, resp_len={len(item['done'])}", flush=True)
            break
    except Exception:
        pass

print(f"\n[ACC] ===== PHASE A/B 结束 elapsed={time.time()-t0:.1f}s got_done={got_done} =====", flush=True)

# PHASE C 已拆分到独立沙盒脚本 acceptance_p21_phase_c.py (避免真实 HB 污染强制反证)
time.sleep(1)  # 等最后日志 flush
os._exit(0)
