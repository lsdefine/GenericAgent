#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LLM 服务候选发现器（低影响 GET 指纹探测，不执行利用）。

示例：
    python scanner/probe.py -i data/raw/hosts.txt -o data/candidates/result.jsonl --resume

输入每行一个裸主机、IP、host:port、[IPv6]:port 或显式 http(s) URL。
每条 probe 的全部 expect 规则必须满足；纯状态码和认证会话路径不会形成候选。
输出为追加式 JSONL，每个输入目标均有 candidate 或 no_match_or_unreachable 记录。
"""
import argparse, asyncio, hashlib, ipaddress, json, re, sys, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

WORK_DIR = Path(__file__).resolve().parents[1]
DEFAULT_FINGERPRINT = str(WORK_DIR / "fingerprints" / "ai_fingerprints.json")
DEFAULT_OUTPUT = str(WORK_DIR / "data" / "candidates" / "result.jsonl")
SCANNER_VERSION = "0.3"

try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False

DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
EV_ID = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def choose_proxy(target, proxies):
    """为目标稳定选择代理，避免同一目标在重跑时随机漂移。"""
    if not proxies:
        return None
    digest = hashlib.sha256(target.encode("utf-8")).digest()
    return proxies[int.from_bytes(digest[:8], "big") % len(proxies)]


def normalize_host(h):
    """规范化目标，保留显式 scheme、端口及 IPv6；不接受带凭据的 URL。"""
    h = h.strip().strip('"').strip("'")
    if not h or h.startswith('#'):
        return None
    explicit_scheme = None
    text = h
    if '://' in h:
        p0 = urlsplit(h)
        if p0.scheme.lower() not in ('http', 'https'):
            return None
        explicit_scheme = p0.scheme.lower()
    else:
        text = '//' + h
    try:
        p = urlsplit(text)
        if not p.hostname or p.username or p.password:
            return None
        host = p.hostname.rstrip('.').lower()
        try:
            ip = ipaddress.ip_address(host)
            host = f'[{ip.compressed}]' if ip.version == 6 else ip.compressed
        except ValueError:
            if any(c.isspace() for c in host):
                return None
        authority = host if p.port is None else f'{host}:{p.port}'
        return f'{explicit_scheme}://{authority}' if explicit_scheme else authority
    except (ValueError, UnicodeError):
        return None


def target_schemes(target):
    return [urlsplit(target).scheme.lower()] if '://' in target else ['https', 'http']


def target_authority(target):
    return urlsplit(target if '://' in target else '//' + target).netloc


def _json_contains(value, needle):
    if isinstance(value, dict):
        return needle in value or any(_json_contains(v, needle) for v in value.values())
    if isinstance(value, list):
        return any(_json_contains(v, needle) for v in value)
    return needle.lower() in str(value).lower()


def match_expect(expect, status, headers, body):
    """校验一条规则；调用方负责将一条 probe 的所有规则做 AND 聚合。"""
    try:
        if expect.startswith("status:"):
            code = expect.split(":", 1)[1].lower()
            return str(status).startswith(code[0]) if code.endswith("xx") else status == int(code)
        if expect.startswith("json_contains:"):
            return _json_contains(json.loads(body), expect.split(":", 1)[1])
        if expect.startswith("html_contains:"):
            return expect.split(":", 1)[1].lower() in body.lower()
        if expect.startswith("title_contains:"):
            title = re.search(r"<title[^>]*>(.*?)</title>", body, re.S | re.I)
            return bool(title and expect.split(":", 1)[1].lower() in title.group(1).lower())
        if expect.startswith("header_contains:"):
            name, _, value = expect.split(":", 1)[1].partition(":")
            return value.lower() in next((v for k, v in headers.items() if k.lower() == name.lower()), "").lower()
    except (ValueError, TypeError, json.JSONDecodeError):
        return False
    return False


def redact_evidence(body):
    """只输出有限且脱敏后的 JSON/文本片段，避免候选库收集令牌。"""
    try:
        value = json.loads(body)
        def walk(node):
            if isinstance(node, dict):
                return {k: "[REDACTED]" if re.search(r"token|secret|password|api[_-]?key|authorization|cookie", k, re.I) else walk(v) for k, v in node.items()}
            if isinstance(node, list):
                return [walk(v) for v in node[:10]]
            return node
        return json.dumps(walk(value), ensure_ascii=False)[:600]
    except (ValueError, TypeError, json.JSONDecodeError):
        return re.sub(r"(?i)(token|secret|password|api[_-]?key|authorization)\s*[:=]\s*[^\s<,;]+", r"\1=[REDACTED]", body)[:300]


async def probe_one(session, authority, base_scheme, path, timeout, sem, proxy=None, insecure=False, follow_redirects=False):
    """发一条低影响 GET；返回成功、状态、头、正文、最终 URL。"""
    url = f"{base_scheme}://{authority}{path}"
    try:
        async with sem:
            async with session.get(url, timeout=timeout, proxy=proxy, allow_redirects=follow_redirects,
                                   ssl=False if insecure else None) as response:
                return True, response.status, dict(response.headers), await response.text(errors="replace"), str(response.url)
    except Exception:
        return False, 0, {}, "", ""


async def scan_target(session, target, fp, timeout, sem, probe_only=None, proxy=None,
                      insecure=False, follow_redirects=False):
    """对单个目标做低影响 GET 指纹探测；一条 probe 的 expect 必须全部满足。"""
    for scheme in target_schemes(target):
        authority = target_authority(target)
        for fp_cat, cat_name in (("open_source_chat_frameworks", "chat_framework"),
                                 ("api_gateway_panels", "gateway_panel"),
                                 ("raw_model_backends", "model_backend")):
            for item in fp.get(fp_cat, []):
                probes = item.get("probes", [])
                if probe_only:
                    probes = [p for p in probes if p.get("path") in probe_only]
                for pr in probes:
                    path = pr.get("path", "/")
                    # 认证会话可能包含真实令牌；默认不采集。
                    if re.search(r"/auth/|/session|token", path, re.I):
                        continue
                    expects = pr.get("expect", [])
                    strong = [e for e in expects if not e.startswith("status:")]
                    # 空 expect 或纯 status 规则不能提供稳定指纹证据。
                    if not strong:
                        continue
                    ok, status, headers, body, final_url = await probe_one(
                        session, authority, scheme, path, timeout, sem, proxy,
                        insecure, follow_redirects)
                    if not ok or not all(match_expect(e, status, headers, body) for e in expects):
                        continue
                    return {
                        "target": target, "cat": cat_name, "name": item.get("name", "unknown"),
                        "score": item.get("score", 0),
                        "hits": [{"path": path, "status": status, "scheme": scheme,
                                  "evidence": redact_evidence(body),
                                  "final_url": final_url}],
                        "ts": datetime.now(timezone.utc).isoformat()
                    }
    return None


async def main():
    ap = argparse.ArgumentParser(description="LLM 服务候选发现器（仅低影响 GET 指纹探测）")
    ap.add_argument("-i", "--input", help="目标文件；省略时从标准输入读取")
    ap.add_argument("-o", "--output", default=DEFAULT_OUTPUT)
    ap.add_argument("-p", "--proxies", help="HTTP(S) 代理列表；只在请求中使用，不写入结果")
    ap.add_argument("-c", "--concurrency", type=int, default=12)
    ap.add_argument("-t", "--timeout", type=float, default=8.0)
    ap.add_argument("-f", "--fingerprint", default=DEFAULT_FINGERPRINT)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--probe-only", help="逗号分隔的路径白名单")
    ap.add_argument("--resume", action="store_true", help="跳过输出 JSONL 中已记录的目标")
    ap.add_argument("--insecure", action="store_true", help="仅在本地测试时关闭 TLS 证书校验")
    ap.add_argument("--follow-redirects", action="store_true", help="显式允许跟随重定向")
    args = ap.parse_args()
    if not HAS_AIOHTTP:
        print("[!] 需要 aiohttp: pip install aiohttp", file=sys.stderr)
        sys.exit(1)
    if not 1 <= args.concurrency <= 100 or args.timeout <= 0:
        ap.error("--concurrency 必须为 1..100，--timeout 必须大于 0")
    with open(args.fingerprint, encoding="utf-8") as f:
        fp = json.load(f)

    raw_lines = open(args.input, encoding="utf-8", errors="replace") if args.input else sys.stdin
    try:
        targets = [h for line in raw_lines if (h := normalize_host(line))]
    finally:
        if args.input:
            raw_lines.close()
    targets = list(dict.fromkeys(targets))
    if args.limit:
        targets = targets[:args.limit]

    completed = set()
    if args.resume:
        try:
            with open(args.output, encoding="utf-8", errors="replace") as f:
                for line in f:
                    try:
                        record = json.loads(line)
                        completed.add(record.get("target", record.get("host")))
                    except json.JSONDecodeError:
                        continue
        except FileNotFoundError:
            pass
        targets = [target for target in targets if target not in completed]
    proxy_list = []
    if args.proxies:
        with open(args.proxies, encoding="utf-8") as f:
            proxy_list = [line.strip() for line in f if line.strip() and not line.lstrip().startswith("#")]
        if any(urlsplit(proxy).scheme.lower() not in ("http", "https") or not urlsplit(proxy).hostname
               for proxy in proxy_list):
            ap.error("--proxies 中的每项必须是完整的 http(s) 代理 URL")
    probe_only = ({path.strip() for path in args.probe_only.split(",") if path.strip()}
                  if args.probe_only else None)
    if args.probe_only and not probe_only:
        ap.error("--probe-only 至少包含一个非空路径")
    if probe_only and any(not path.startswith("/") for path in probe_only):
        ap.error("--probe-only 中的路径必须以 / 开头")
    run_meta = {
        "run_id": EV_ID,
        "scanner_version": SCANNER_VERSION,
        "fingerprint_version": str(fp.get("_meta", {}).get("version", "unknown")),
        "timeout_seconds": args.timeout,
        "follow_redirects": args.follow_redirects,
        "insecure": args.insecure,
        "probe_only": sorted(probe_only) if probe_only else None,
        "proxy_count": len(proxy_list),
    }
    print(f"[*] 待测 {len(targets)} 个，框架 {sum(len(fp.get(k, [])) for k in fp if not k.startswith('_'))} 组，并发 {args.concurrency}，代理 {len(proxy_list)} 条", flush=True)

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    sem, queue = asyncio.Semaphore(args.concurrency), asyncio.Queue()
    for target in targets:
        queue.put_nowait(target)
    tested = candidates = 0
    start = time.time()
    headers = {"User-Agent": DEFAULT_UA, "Accept": "application/json,text/html;q=0.9,*/*;q=0.1"}
    connector = aiohttp.TCPConnector(limit=args.concurrency, ssl=None)
    with open(args.output, "a", encoding="utf-8") as out:
        async with aiohttp.ClientSession(connector=connector, headers=headers) as session:
            async def worker():
                nonlocal tested, candidates
                while True:
                    try:
                        target = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        return
                    proxy = choose_proxy(target, proxy_list)
                    result = await scan_target(session, target, fp, args.timeout, sem, probe_only, proxy,
                                               args.insecure, args.follow_redirects)
                    record = result or {"target": target, "outcome": "no_match_or_unreachable",
                                        "ts": datetime.now(timezone.utc).isoformat()}
                    record["run"] = run_meta
                    if result:
                        record["outcome"] = "candidate"
                        candidates += 1
                    out.write(json.dumps(record, ensure_ascii=False) + "\n")
                    out.flush()
                    tested += 1
                    if tested % 25 == 0:
                        print(f"[*] 已测 {tested}/{len(targets)}，候选 {candidates}，耗时 {time.time()-start:.0f}s", flush=True)
                    queue.task_done()
            await asyncio.gather(*(worker() for _ in range(min(args.concurrency, len(targets) or 1))))
    print(f"[+] 完成：测试 {tested}，候选 {candidates}，追加写入 {args.output}，耗时 {time.time()-start:.0f}s", flush=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[!] 中断", file=sys.stderr)
        sys.exit(130)
