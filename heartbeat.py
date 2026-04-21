"""P2.1 — 心跳起搏器 (HeartbeatProducer) CTO硬核令版
daemon 线程,每 interval_sec 向主任务队列 put 一次 heartbeat 事件
核心变更(P2.1 CTO硬核令):
  - .locked() → acquire(blocking=False),教授不抢学生话(TOCTOU 零竞态)
  - 配合 agentmain RLock,heartbeat 探测获取成功即立刻释放(探针语义)
R9 工程规范: 子线程只 queue.put 回主线程,禁止直接操作模型/记忆
"""
import threading, time


class HeartbeatProducer(threading.Thread):
    def __init__(self, agent, interval_sec=60):
        super().__init__(daemon=True, name="HeartbeatProducer")
        self.agent = agent
        self.q = agent.task_queue
        self.interval = interval_sec

    def run(self):
        # 启动延时: 避免启动瞬间与主消费者 race
        time.sleep(self.interval)
        while True:
            try:
                ts = time.strftime("%H:%M:%S")
                # P2.1 CTO硬核令: 非阻塞探测,失败立刻丢弃本次心跳 (不阻塞主线程推理)
                acquired = self.agent.llm_busy_lock.acquire(blocking=False)
                if not acquired:
                    print(f"[Heartbeat] {ts} L0-scan skipped: LLM busy.", flush=True)
                else:
                    try:
                        self.q.put({"type": "heartbeat", "timestamp": time.time(), "source": "cron"})
                        print(f"[Heartbeat] {ts} 💓 投递主动突袭入队 qsize={self.q.qsize()}", flush=True)
                    finally:
                        self.agent.llm_busy_lock.release()
            except Exception as e:
                print(f"[Heartbeat] 入队异常(忽略): {e}", flush=True)
            time.sleep(self.interval)
