#!/usr/bin/env python3
"""
model_router.py — OpenLLM 模型路由与基准测试工具

功能:
  1. scan    扫描 OpenLLM 所有可用模型，分类统计
  2. select  自动选5个代表模型（快速/均衡/强大/代码/多模态）
  3. bench   对选定模型运行速度基准（延迟/吞吐）
  4. route   按任务推荐模型（智能路由）
  5. list    列出所有模型（支持过滤）

依赖: requests (pip install requests)
"""

import os, sys, json, time, argparse, textwrap
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import URLError

# ── 配置 ──
OPENLLM_BASE = os.environ.get("OPENLLM_BASE", "http://127.0.0.1:11343")
BENCH_PROMPT = "What is the capital of France? Answer in one word."
BENCH_MAX_TOKENS = 10

# ── 模型分类规则 ──
FAST_KEYWORDS = ["flash", "1b", "2b", "3b", "small", "mini", "lite"]
POWERFUL_KEYWORDS = ["70b", "90b", "675b", "480b", "large", "max", "m2.7", "k2.6"]
CODE_KEYWORDS = ["coder", "code", "starcoder", "codestral"]
VISION_KEYWORDS = ["vision", "visual", "multimodal", "kosmos", "deplot", "phi-4-multimodal"]


# ── API 工具 ──
def api_get(endpoint: str) -> dict:
    url = f"{OPENLLM_BASE}{endpoint}"
    req = Request(url, headers={"Accept": "application/json"})
    try:
        with urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        raise RuntimeError(f"API 请求失败 {url}: {e}")


def api_chat(model: str, prompt: str = BENCH_PROMPT, max_tokens: int = BENCH_MAX_TOKENS,
             timeout: int = 15) -> dict:
    url = f"{OPENLLM_BASE}/v1/chat/completions"
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
    }).encode()
    req = Request(url, data=body, headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode())
    elapsed = time.time() - t0
    usage = data.get("usage", {})
    return {
        "latency": round(elapsed, 3),
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        "total_tokens": usage.get("total_tokens", 0),
    }


# ── 模型分类 ──
def classify_model(model_id: str) -> str:
    """将模型归类: fast / balanced / powerful / code / vision / other"""
    m = model_id.lower()
    for kw, cat in [(VISION_KEYWORDS, "vision"), (CODE_KEYWORDS, "code"),
                     (FAST_KEYWORDS, "fast"), (POWERFUL_KEYWORDS, "powerful")]:
        if any(k in m for k in kw):
            return cat
    return "balanced"


def select_representatives(models: list, count: int = 5) -> list:
    """从模型中选 count 个代表"""
    # 按分类去重选代表
    by_cat = {}
    for m in models:
        cat = classify_model(m["id"])
        by_cat.setdefault(cat, []).append(m)
    
    # 优先选各分类的最佳代表
    selected = []
    # 分类优先级
    cat_order = ["fast", "balanced", "powerful", "code", "vision", "other"]
    for cat in cat_order:
        if len(selected) >= count:
            break
        if cat not in by_cat:
            continue
        # 选该分类第一个模型
        candidates = by_cat[cat]
        # 尽量选不同 provider
        used_providers = {s["id"].split("/")[0] for s in selected}
        best = None
        for c in candidates:
            prov = c["id"].split("/")[0]
            if prov not in used_providers:
                best = c
                break
        if best is None:
            best = candidates[0]
        selected.append(best)
    
    # 补足到 count
    while len(selected) < count and len(models) > len(selected):
        for m in models:
            if m not in selected:
                selected.append(m)
                break
    
    return selected[:count]


# ── 子命令 ──
def cmd_scan(args):
    """扫描所有模型"""
    data = api_get("/v1/models")
    models = data.get("data", [])
    print(f"📊 OpenLLM 模型总数: {len(models)}")
    # 按 provider 分类
    from collections import Counter
    prov_counter = Counter()
    cat_counter = Counter()
    for m in models:
        mid = m["id"]
        prov = mid.split("/")[0] if "/" in mid else "unknown"
        prov_counter[prov] += 1
        cat_counter[classify_model(mid)] += 1
    
    print("\n按 Provider:")
    for p, c in prov_counter.most_common():
        print(f"  {p}: {c} 个")
    print("\n按类型:")
    for cat in ["fast", "balanced", "powerful", "code", "vision", "other"]:
        if cat_counter[cat]:
            print(f"  {cat}: {cat_counter[cat]} 个")
    
    if args.list:
        print("\n全部模型:")
        for m in models:
            cat = classify_model(m["id"])
            print(f"  [{cat:>8}] {m['id']}")
    
    return models


def cmd_select(args):
    """自动选代表模型"""
    data = api_get("/v1/models")
    models = data.get("data", [])
    selected = select_representatives(models, args.count)
    print(f"🏆 选出 {len(selected)} 个代表模型:\n")
    for i, m in enumerate(selected, 1):
        cat = classify_model(m["id"])
        print(f"  {i}. [{cat:>8}] {m['id']}")
    # 保存
    out = args.output or "/tmp/selected_models.json"
    with open(out, "w") as f:
        json.dump([s["id"] for s in selected], f, indent=2)
    print(f"\n已保存: {out}")
    return selected


def cmd_bench(args):
    """对选定模型运行速度基准"""
    # 获取模型列表
    if args.model:
        model_ids = args.model if isinstance(args.model, list) else [args.model]
    elif args.file:
        with open(args.file) as f:
            model_ids = json.load(f)
    else:
        # 自动选5个
        data = api_get("/v1/models")
        selected = select_representatives(data.get("data", []), 5)
        model_ids = [s["id"] for s in selected]
    
    print(f"🧪 基准测试: {', '.join(model_ids)}\n")
    results = []
    for mid in model_ids:
        print(f"  ⏳ 测试 {mid}...", end=" ", flush=True)
        try:
            # 跑3次取平均
            latencies = []
            tokens = []
            for _ in range(3):
                r = api_chat(mid)
                latencies.append(r["latency"])
                tokens.append(r["total_tokens"])
            avg_lat = sum(latencies) / len(latencies)
            avg_tok = sum(tokens) / len(tokens)
            tps = avg_tok / avg_lat if avg_lat > 0 else 0
            results.append({
                "model": mid,
                "category": classify_model(mid),
                "avg_latency_s": round(avg_lat, 3),
                "avg_tokens": round(avg_tok, 1),
                "tokens_per_sec": round(tps, 1),
                "latencies": latencies,
            })
            print(f" ✅ {avg_lat:.2f}s | {tps:.1f} tok/s")
        except Exception as e:
            print(f" ❌ {e}")
            results.append({"model": mid, "error": str(e)})
    
    print("\n📊 基准结果:")
    print(f"  {'模型':<50} {'延迟(s)':<10} {'吞吐(tok/s)':<15} {'分类':<10}")
    print(f"  {'-'*50} {'-'*10} {'-'*15} {'-'*10}")
    for r in results:
        if "error" in r:
            print(f"  {r['model']:<50} {'ERROR':<10} {r['error']:<30}")
        else:
            print(f"  {r['model']:<50} {r['avg_latency_s']:<10.2f} {r['tokens_per_sec']:<15.1f} {r['category']:<10}")
    
    # 保存
    out = args.output or "/tmp/bench_results.json"
    with open(out, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n结果已保存: {out}")
    return results


def cmd_route(args):
    """按任务推荐模型"""
    task = args.task or "chat"
    
    # 从基准结果或默认分类推断
    bench_file = args.bench or "/tmp/bench_results.json"
    if os.path.exists(bench_file):
        with open(bench_file) as f:
            bench_data = json.load(f)
    else:
        bench_data = None
    
    # 任务路由表
    route_table = {
        "chat": {"desc": "通用对话", "prefer": "balanced", "example": "router/nvidia/meta/llama-3.1-8b-instruct"},
        "fast": {"desc": "快速响应", "prefer": "fast", "example": "deepseek/deepseek-v4-flash"},
        "code": {"desc": "代码生成", "prefer": "code", "example": "nvidia/meta/codellama-70b"},
        "reasoning": {"desc": "复杂推理", "prefer": "powerful", "example": "nvidia/meta/llama-3.3-70b-instruct"},
        "vision": {"desc": "图像理解", "prefer": "vision", "example": "nvidia/meta/llama-3.2-11b-vision-instruct"},
        "writing": {"desc": "长文写作", "prefer": "powerful", "example": "nvidia/mistralai/mistral-large"},
    }
    
    if task not in route_table:
        print(f"❌ 未知任务: {task}")
        print(f"可用任务: {', '.join(route_table.keys())}")
        return
    
    info = route_table[task]
    print(f"📌 任务: {task} ({info['desc']})")
    print(f"   推荐类型: {info['prefer']}")
    print(f"   示例模型: {info['example']}")
    
    # 从基准数据中找最优
    if bench_data:
        candidates = [r for r in bench_data if "error" not in r]
        task_cat = info["prefer"]
        cat_candidates = [r for r in candidates if r.get("category") == task_cat]
        if not cat_candidates:
            cat_candidates = candidates
        
        # 按延迟排序
        sorted_by_latency = sorted(cat_candidates, key=lambda x: x.get("avg_latency_s", 999))
        # 按吞吐排序
        sorted_by_tps = sorted(cat_candidates, key=lambda x: -x.get("tokens_per_sec", 0))
        
        print(f"\n🏆 基于基准数据的推荐:")
        if sorted_by_latency:
            best = sorted_by_latency[0]
            print(f"   最低延迟: {best['model']} ({best['avg_latency_s']:.2f}s)")
        if sorted_by_tps:
            best_tps = sorted_by_tps[0]
            print(f"   最高吞吐: {best_tps['model']} ({best_tps['tokens_per_sec']:.1f} tok/s)")
        
        print(f"\n   候选排名 (按延迟):")
        for i, r in enumerate(sorted_by_latency[:5], 1):
            print(f"     {i}. {r['model']:<50} {r['avg_latency_s']:.2f}s | {r['tokens_per_sec']:.1f} tok/s")
    else:
        print(f"\n💡 提示: 先运行 'model_router.py bench' 获取基准数据以获得精准推荐")


def cmd_list(args):
    """列出所有模型，支持过滤"""
    data = api_get("/v1/models")
    models = data.get("data", [])
    
    # 过滤
    if args.provider:
        models = [m for m in models if m["id"].startswith(args.provider)]
    if args.category:
        models = [m for m in models if classify_model(m["id"]) == args.category]
    if args.search:
        models = [m for m in models if args.search.lower() in m["id"].lower()]
    
    print(f"📋 模型列表 ({len(models)}):\n")
    for m in models:
        cat = classify_model(m["id"])
        print(f"  [{cat:>8}] {m['id']}")
    
    # 统计
    from collections import Counter
    cats = Counter(classify_model(m["id"]) for m in models)
    print(f"\n统计: ", end="")
    for cat, cnt in cats.most_common():
        print(f"{cat}={cnt}", end=" ")
    print()


# ── 质量评估 ──
QUALITY_TESTS = [
    # (name, prompt, check_fn) — check_fn recieves response, returns score 0-100
    {
        "dimension": "知识",
        "prompt": "What is the capital of Australia? Answer with just the city name.",
        "check": lambda r: 100 if "canberra" in r.lower().strip() else (50 if "sydney" not in r.lower() else 0),
    },
    {
        "dimension": "知识",
        "prompt": "What is the chemical symbol for gold? Answer with just the symbol.",
        "check": lambda r: 100 if r.lower().strip().startswith("au") else 0,
    },
    {
        "dimension": "推理",
        "prompt": "If you have three apples and you take away two, how many apples do you have? Think step by step.",
        "check": lambda r: 100 if "2" in r or "two" in r.lower() else 0,
    },
    {
        "dimension": "推理",
        "prompt": "A bat and a ball cost $1.10 in total. The bat costs $1.00 more than the ball. How much does the ball cost? Show your reasoning.",
        "check": lambda r: 100 if "0.05" in r or "5 cent" in r or "5¢" in r else (50 if "bat" in r.lower() else 0),
    },
    {
        "dimension": "代码",
        "prompt": "Write a Python function to check if a string is a palindrome. Only return the code, no explanation.",
        "check": lambda r: 100 if "def palindrome" in r.lower() or "def is_palindrome" in r.lower() else (50 if "return" in r.lower() else 0),
    },
    {
        "dimension": "代码",
        "prompt": "Write a bash one-liner to find all .py files modified in the last 7 days and count them.",
        "check": lambda r: 100 if "find" in r.lower() and ".py" in r and ("mtime" in r or "newer" in r or "day" in r.lower()) else (50 if "find" in r.lower() else 0),
    },
    {
        "dimension": "多语言",
        "prompt": "请用中文介绍深度学习的基本概念，不少于50字。",
        "check": lambda r: min(100, len(r) // 2) if any('\u4e00' <= c <= '\u9fff' for c in r) else 0,
    },
    {
        "dimension": "多语言",
        "prompt": "Traduisez cette phrase en français: 'Hello, how are you today?'",
        "check": lambda r: 100 if any(w in r.lower() for w in ["bonjour", "comment", "ça", "va", "aujourd"]) else (50 if len(r.split()) > 5 else 0),
    },
    {
        "dimension": "指令遵循",
        "prompt": "List exactly three reasons why Python is popular. Output each reason on a separate line starting with a dash (-).",
        "check": lambda r: 100 if r.count("-") >= 3 else (50 if r.count("\n") >= 2 else 0),
    },
    {
        "dimension": "指令遵循",
        "prompt": "Answer ONLY with the word 'Hello'. Do not output anything else.",
        "check": lambda r: 100 if r.strip().lower() == "hello" else (50 if "hello" in r.lower() else 0),
    },
]


def run_quality_test(model_id: str, test: dict, timeout: int = 30) -> dict:
    """对单个测试用例评分"""
    prompt = test["prompt"]
    try:
        r = api_chat(model_id, prompt=prompt, max_tokens=200, timeout=timeout)
        response_text = ""
        # 获取生成内容
        url = f"{OPENLLM_BASE}/v1/chat/completions"
        body = json.dumps({
            "model": model_id,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 200,
        }).encode()
        req = Request(url, data=body, headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
        choices = data.get("choices", [])
        if choices:
            msg = choices[0].get("message", {})
            response_text = msg.get("content", "")
        
        score = test["check"](response_text)
        return {
            "dimension": test["dimension"],
            "prompt": prompt[:60],
            "score": score,
            "response_length": len(response_text),
            "latency": r["latency"],
        }
    except Exception as e:
        return {
            "dimension": test["dimension"],
            "prompt": prompt[:60],
            "score": 0,
            "error": str(e),
            "latency": 0,
        }


def cmd_quality(args):
    """对代表模型进行质量评估"""
    # 获取模型列表
    if args.model:
        model_ids = args.model
    elif args.file:
        with open(args.file) as f:
            model_ids = json.load(f)
    else:
        data = api_get("/v1/models")
        selected = select_representatives(data.get("data", []), 5)
        model_ids = [s["id"] for s in selected]
    
    print(f"🎯 质量评估: {', '.join(model_ids)}\n")
    
    all_results = {}
    for mid in model_ids:
        print(f"  📝 评估 {mid}...")
        cat = classify_model(mid)
        tests = QUALITY_TESTS
        results = []
        for i, test in enumerate(tests, 1):
            print(f"    [{i}/{len(tests)}] {test['dimension']}: {test['prompt'][:40]}...", end=" ", flush=True)
            r = run_quality_test(mid, test)
            results.append(r)
            status = f"✅ {r['score']}/100" if r['score'] > 0 else "⚠️ 0"
            print(status)
        
        # 按维度汇总
        dim_scores = {}
        for r in results:
            dim_scores.setdefault(r["dimension"], []).append(r["score"])
        avg_dim = {d: sum(s)/len(s) for d, s in dim_scores.items()}
        overall = sum(avg_dim.values()) / len(avg_dim)
        avg_lat = sum(r.get("latency", 0) for r in results) / len(results)
        
        all_results[mid] = {
            "category": cat,
            "dimension_scores": {d: round(s, 1) for d, s in avg_dim.items()},
            "overall_quality": round(overall, 1),
            "avg_latency_s": round(avg_lat, 3),
            "details": results,
        }
        
        print(f"\n  📊 {mid} 质量总分: {overall:.1f}/100 (延迟: {avg_lat:.2f}s)")
        for d, s in avg_dim.items():
            print(f"    {d}: {s:.1f}")
        print()
    
    # 排名
    print("=" * 60)
    print("🏆 质量排名:")
    print(f"  {'排名':<6} {'模型':<55} {'质量分':<8} {'延迟(s)':<10} {'分类':<10}")
    print(f"  {'-'*6} {'-'*55} {'-'*8} {'-'*10} {'-'*10}")
    ranked = sorted(all_results.items(), key=lambda x: -x[1]["overall_quality"])
    for i, (mid, data) in enumerate(ranked, 1):
        print(f"  #{i:<4} {mid:<55} {data['overall_quality']:<8.1f} {data['avg_latency_s']:<10.2f} {data['category']:<10}")
    
    # 保存
    out = args.output or "/tmp/quality_results.json"
    with open(out, "w") as f:
        json.dump({"models": all_results, "ranking": [m for m, _ in ranked]}, f, indent=2, ensure_ascii=False)
    print(f"\n结果已保存: {out}")
    
    return all_results


# ── 主入口 ──
def main():
    parser = argparse.ArgumentParser(
        description="OpenLLM 模型路由与基准测试工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            使用示例:
              %(prog)s scan                          # 扫描所有模型
              %(prog)s scan --list                   # 扫描并列出全部
              %(prog)s select                        # 自动选5个代表
              %(prog)s bench                         # 对代表模型跑基准
              %(prog)s bench --model deepseek/deepseek-v4-flash  # 测指定模型
              %(prog)s bench --file /tmp/selected_models.json    # 从文件加载
              %(prog)s route --task code             # 推荐代码模型
              %(prog)s list --category fast          # 列出快速模型
        """))
    parser.add_argument("command", nargs="?", default="help",
                        choices=["scan", "select", "bench", "route", "list", "quality", "help"])
    parser.add_argument("--list", action="store_true", help="scan时列出全部模型")
    parser.add_argument("--count", "-n", type=int, default=5, help="选择代表数量")
    parser.add_argument("--model", "-m", action="append", type=str, help="指定模型ID（可多次）")
    parser.add_argument("--task", "-t", type=str, default="chat", help="路由任务类型")
    parser.add_argument("--file", "-f", type=str, help="从JSON文件加载模型列表")
    parser.add_argument("--output", "-o", type=str, default="", help="输出文件路径")
    parser.add_argument("--bench", "-b", type=str, default="/tmp/bench_results.json", help="基准数据文件")
    parser.add_argument("--provider", "-p", type=str, help="按provider过滤")
    parser.add_argument("--category", "-c", type=str, help="按分类过滤(fast/balanced/powerful/code/vision)")
    parser.add_argument("--search", "-s", type=str, help="按关键词搜索")
    
    args = parser.parse_args()
    
    try:
        if args.command == "scan":
            cmd_scan(args)
        elif args.command == "select":
            cmd_select(args)
        elif args.command == "bench":
            cmd_bench(args)
        elif args.command == "route":
            cmd_route(args)
        elif args.command == "list":
            cmd_list(args)
        elif args.command == "quality":
            cmd_quality(args)
        else:
            parser.print_help()
    except RuntimeError as e:
        print(f"❌ {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n⏹ 中断")
        sys.exit(1)


if __name__ == "__main__":
    main()
