"""P1.4 CTO 竣工验收 — 教授人格对抗测试 (不污染向量记忆)
启动: cd aduAgent/GenericAgent && python tests/eval_persona.py

验证目标:
  ① threading.Lock 机械化闸已生效 (heartbeat 生产端看到 locked 直接跳过)
  ② 教授人格在场: 2 例对抗性用户输入,reply 呈现冷酷/数据驱动风格
  ③ task_queue.qsize 全程 ≤ 2 (消费者未卡死)
  ④ agent_vec.db 字节数 before == after (mem_write 已被 hook 拦截)
"""
import os, sys, time, threading
import queue as _q

# 让 tests/ 能 import agentmain.py
_HERE = os.path.dirname(os.path.abspath(__file__))
_GA_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _GA_ROOT)


def _vec_db_path():
    """从 memory_vec.brain 拿真实 db 路径,拿不到则回退 memory/vector_store/embeddings.db"""
    try:
        from memory_vec import brain
        for attr in ("db_path", "DB_PATH", "_db_path", "path"):
            p = getattr(brain, attr, None)
            if isinstance(p, str) and p:
                return p
    except Exception as e:
        print(f"[VecDB] memory_vec 探测失败: {e}", flush=True)
    return os.path.join(_GA_ROOT, "memory", "vector_store", "embeddings.db")


def _db_bytes(p):
    try: return os.path.getsize(p)
    except OSError: return -1


# ───────────────────────── LLM 自动探活 (CTO 方案 D) ─────────────────────────
# 直接打底层 backend.raw_ask(单次 HTTP,不写 history,不走外层 ask 的历史追加逻辑)。
# MixinSession 临时把 _retries 降到 0,避免 10 轮 85s 的重试海啸。
DEAD_MARKERS = ("Error:", "HTTP 401", "HTTP 403", "HTTP 404",
                "Incorrect API key", "invalid_api_key", "sk-<", "placeholder",
                "Invalid API", "authentication")

def probe_live_llm(agent, ping="hi", cap=200):
    """逐槽位单次探活,返回首个 alive 的 index。全挂则 raise。"""
    n = len(agent.llmclients)
    print(f"[Probe] 发现 {n} 个 LLM 槽位,开始逐个探活 (单次 HTTP,不污染 history)...", flush=True)
    alive_idx = -1
    probe_log = []
    for i, client in enumerate(agent.llmclients):
        backend = client.backend
        name = getattr(backend, 'name', f'slot{i}')
        model = getattr(backend, 'model', '?')
        # MixinSession: 临时降 retries 到 0,探完恢复
        orig_retries = None
        if hasattr(backend, '_retries'):
            try:
                orig_retries = backend._retries
                backend._retries = 0
            except Exception: pass
        t0 = time.time(); reply = ''
        try:
            msgs_in = [{"role": "user", "content": [{"type": "text", "text": ping}]}]
            msgs = backend.make_messages(msgs_in) if hasattr(backend, 'make_messages') else msgs_in
            gen = backend.raw_ask(msgs)
            for chunk in gen:
                reply += str(chunk)
                if len(reply) > cap: break
        except Exception as e:
            reply = f"Error: {e}"
        finally:
            if orig_retries is not None:
                try: backend._retries = orig_retries
                except Exception: pass
        elapsed = time.time() - t0
        is_dead = (not reply.strip()) or any(m in reply for m in DEAD_MARKERS)
        verdict = "DEAD " if is_dead else "ALIVE"
        name_s = name if len(name) < 50 else name[:47] + "..."
        print(f"[Probe] slot{i} [{verdict}] t={elapsed:4.1f}s name={name_s!r} model={model!r}", flush=True)
        print(f"        reply[:100] = {reply[:100]!r}", flush=True)
        probe_log.append({"idx": i, "alive": not is_dead, "name": name, "model": model,
                          "elapsed": elapsed, "reply_head": reply[:100]})
        if (not is_dead) and alive_idx < 0:
            alive_idx = i  # 记住首个 alive,但继续探完全部 (CTO 要完整追踪数据)
    if alive_idx < 0:
        raise RuntimeError(f"[Probe] 所有 {n} 个 LLM 槽位均 DEAD,无法进行对抗测试。"
                           f"请检查 mykey.py / API 可用性。")
    return alive_idx, probe_log


def main():
    db_p = _vec_db_path()
    size_before = _db_bytes(db_p)
    print(f"[VecDB] path     = {db_p}", flush=True)
    print(f"[VecDB] size_bef = {size_before} bytes", flush=True)

    from agentmain import GeneraticAgent
    agent = GeneraticAgent()

    # —— LLM 自动探活 + 回退轮询 (CTO 方案 D) ——
    live_idx, probe_log = probe_live_llm(agent)
    live_backend = agent.llmclients[live_idx].backend
    live_name = getattr(live_backend, 'name', '?')
    live_model = getattr(live_backend, 'model', '?')
    print(f"\n[Backend] live_index={live_idx} name={live_name!r} model={live_model!r}\n", flush=True)
    agent.next_llm(live_idx)

    try: agent.verbose = False
    except Exception: pass

    # —— 不污染 hook: 屏蔽 mem_write 入队 ——
    orig_put = agent.task_queue.put
    blocked = {"count": 0}
    def filtered_put(item, *a, **kw):
        if isinstance(item, dict) and item.get("type") == "mem_write":
            blocked["count"] += 1
            return
        return orig_put(item, *a, **kw)
    agent.task_queue.put = filtered_put

    # 启动主消费者
    threading.Thread(target=agent.run, daemon=True, name="AgentMainLoop").start()

    # —— 心跳压力源(8s 一跳),用于验证 Lock 在 LLM 繁忙时能闸断生产端 ——
    from heartbeat import HeartbeatProducer
    HeartbeatProducer(agent, interval_sec=8).start()

    # qsize 采样线程 (每 200ms)
    qsize_samples = []
    stop_evt = threading.Event()
    def sampler():
        while not stop_evt.is_set():
            qsize_samples.append(agent.task_queue.qsize())
            time.sleep(0.2)
    threading.Thread(target=sampler, daemon=True, name="QSizeSampler").start()

    # 2 例对抗性用户输入
    cases = [
        ("逃避型", "老师,我最近状态很差,啥也学不进去,我不想学了"),
        ("畏难型", "这个递归我想了一晚上还是不会,能不能直接告诉我答案"),
    ]

    replies = []
    for idx, (label, q) in enumerate(cases, 1):
        print(f"\n{'='*68}\n[CASE {idx}/{label}] user_input = {q!r}\n{'='*68}", flush=True)
        dq = agent.put_task(q, source="eval_persona")
        t0 = time.time()
        reply = ""
        while True:
            try:
                item = dq.get(timeout=180)
            except _q.Empty:
                reply = "[TIMEOUT 180s]"; break
            if isinstance(item, dict) and "done" in item:
                reply = item["done"]; break
        elapsed = time.time() - t0
        print(f"[CASE {idx}] elapsed={elapsed:.1f}s reply_len={len(reply)}", flush=True)
        print(f"[CASE {idx}] reply(前900字):\n---\n{reply[:900]}\n---", flush=True)
        replies.append((label, reply))

    # 结束采样
    stop_evt.set(); time.sleep(0.3)
    size_after = _db_bytes(db_p)

    # ===== 汇总 4 条证据 =====
    print(f"\n{'='*68}\n[VERDICT] P1.4 CTO 4 条验收证据\n{'='*68}", flush=True)

    # 证据③ qsize
    qmax = max(qsize_samples) if qsize_samples else -1
    qavg = sum(qsize_samples)/len(qsize_samples) if qsize_samples else -1
    print(f"证据③ qsize 采样: n={len(qsize_samples)}  max={qmax}  avg={qavg:.2f}  要求≤2 → "
          + ("PASS" if qmax <= 2 else "FAIL"), flush=True)

    # 证据④ 向量库无污染
    delta = (size_after - size_before) if (size_before >= 0 and size_after >= 0) else None
    print(f"证据④ 向量库: before={size_before}B after={size_after}B Δ={delta}B  "
          f"mem_write 拦截次数={blocked['count']}  → "
          + ("PASS" if delta == 0 else f"CHECK(Δ={delta})"), flush=True)

    # 证据② 人格冷酷关键词(非硬指标,供人肉审阅)
    cold_kw = ["进度","承诺","立刻","执行","数据","事实","借口","拖延","废话","行动","量化","完成","deadline","标准"]
    warm_kw = ["理解你","抱抱","没关系","我陪你","辛苦了"]
    print(f"证据② 人格对抗:", flush=True)
    for label, r in replies:
        cold_hit = [k for k in cold_kw if k in r]
        warm_hit = [k for k in warm_kw if k in r]
        print(f"  [{label}] 冷酷词命中={cold_hit}  软弱词命中={warm_hit}", flush=True)

    # 证据① Lock Diff 提示
    print(f"证据① Lock Diff: 见 agentmain.py L82(定义)/L175(acquire)/L230(release) + heartbeat.py L15-28", flush=True)

    # 证据⑤ LLM 探活追踪 (CTO 方案 D)
    print(f"证据⑤ LLM 探活追踪:", flush=True)
    for p in probe_log:
        tag = "ALIVE" if p["alive"] else "DEAD "
        nm = p["name"] if len(p["name"]) < 46 else p["name"][:43] + "..."
        print(f"  slot{p['idx']} [{tag}] t={p['elapsed']:4.1f}s model={p['model']!r} name={nm!r}", flush=True)
    print(f"  → [Backend] live_index={live_idx} name={live_name!r} model={live_model!r}", flush=True)

    print(f"\n{'='*68}\n[END] 4 条证据已输出,请 CTO 审阅\n{'='*68}", flush=True)


if __name__ == "__main__":
    main()
