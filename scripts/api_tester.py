#!/usr/bin/env python3
"""
api_tester.py — API 端点测试 + 响应验证 + 性能基准 (discriminator_api_tester_sop 实战化)
================================================================================

综合 HTTP API 测试工具，覆盖:
  1. 快乐路径测试 (200/成功)
  2. 异常路径测试 (400/401/403/404/409/500)
  3. 认证测试 (Bearer/Basic/API Key)
  4. 参数验证 (必填/类型/边界)
  5. 性能基准 (延迟/吞吐量)
  6. JSON Schema 验证
  7. 报告输出 (JSON/Markdown)

CLI 用法:
  api_tester.py test <url> [options]
  api_tester.py benchmark <url> [--requests 50] [--concurrent 5]
  api_tester.py schema <url> [--method GET]
  api_tester.py smoke <url>           # 快速健康检查
  api_tester.py suite <config.json>   # 批量测试套件

Python API:
  from scripts.api_tester import ApiTester
  tester = ApiTester(base_url="http://localhost:11343")
  result = tester.test_endpoint("/v1/chat/completions", method="POST", json={...})
  report = tester.benchmark("/v1/chat/completions", requests=50, concurrent=5)

依赖: requests (pip install requests)
"""

import os, sys, json, time, math, statistics, argparse
from datetime import datetime
from pathlib import Path
from typing import Optional, Any

SCRIPTS_DIR = Path(__file__).resolve().parent
MEMORY_DIR = SCRIPTS_DIR.parent / 'memory'

try:
    import requests as _req
    HAS_REQUESTS = True
except ImportError:
    _req = None
    HAS_REQUESTS = False

# ═══════════════════════════════════════════════════════
#  ApiTester — 核心类
# ═══════════════════════════════════════════════════════

class ApiTester:
    """
    API 测试代理：HTTP 端点测试 + 响应验证 + 性能基准

    属性:
        base_url (str): 基础 URL
        headers (dict): 默认请求头
        timeout (int): 超时秒数
        verify_ssl (bool): 是否验证 SSL
    """

    def __init__(self, base_url: str = "", headers: dict = None,
                 timeout: int = 15, verify_ssl: bool = True):
        if not HAS_REQUESTS:
            raise ImportError("需要 requests 库: pip install requests")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        self._session = _req.Session()
        self._session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json",
        })
        if headers:
            self._session.headers.update(headers)

    # ── 认证设置 ─────────────────────────────────────

    def set_auth_bearer(self, token: str):
        """设置 Bearer Token 认证"""
        self._session.headers["Authorization"] = f"Bearer {token}"

    def set_auth_basic(self, username: str, password: str):
        """设置 Basic 认证"""
        from requests.auth import HTTPBasicAuth
        self._session.auth = HTTPBasicAuth(username, password)

    def set_auth_header(self, name: str, value: str):
        """设置自定义认证头"""
        self._session.headers[name] = value

    # ── 核心请求 ─────────────────────────────────────

    def request(self, method: str, path: str,
                params: dict = None, json_body: Any = None,
                headers: dict = None, timeout: int = None) -> dict:
        """
        发送 HTTP 请求并返回详细结果

        返回:
            {
                "ok": bool,
                "status": int,
                "time_ms": float,
                "headers": dict,
                "body": Any,
                "body_size": int,
                "error": str | None
            }
        """
        url = f"{self.base_url}{path}" if self.base_url else path
        t0 = time.monotonic()
        try:
            resp = self._session.request(
                method=method.upper(), url=url,
                params=params, json=json_body,
                headers=headers, timeout=timeout or self.timeout,
                verify=self.verify_ssl,
            )
            elapsed = (time.monotonic() - t0) * 1000  # ms
            # 尝试解析 JSON，失败则保留原始文本
            try:
                body = resp.json() if resp.text else None
            except Exception:
                body = resp.text[:2000] if resp.text else None
            return {
                "ok": resp.ok,
                "status": resp.status_code,
                "time_ms": round(elapsed, 2),
                "headers": dict(resp.headers),
                "body": body,
                "body_size": len(resp.content) if resp.content else 0,
                "error": None,
            }
        except _req.exceptions.ConnectionError as e:
            elapsed = (time.monotonic() - t0) * 1000
            return {"ok": False, "status": 0, "time_ms": round(elapsed, 2),
                    "headers": {}, "body": None, "body_size": 0,
                    "error": f"ConnectionError: {e}"}
        except _req.exceptions.Timeout as e:
            elapsed = (time.monotonic() - t0) * 1000
            return {"ok": False, "status": 0, "time_ms": round(elapsed, 2),
                    "headers": {}, "body": None, "body_size": 0,
                    "error": f"Timeout: {e}"}
        except Exception as e:
            elapsed = (time.monotonic() - t0) * 1000
            return {"ok": False, "status": 0, "time_ms": round(elapsed, 2),
                    "headers": {}, "body": None, "body_size": 0,
                    "error": str(e)}

    # ── 端点测试 ─────────────────────────────────────

    def test_endpoint(self, path: str, method: str = "GET",
                      params: dict = None, json_body: Any = None,
                      expected_status: int = 200,
                      expected_schema: dict = None,
                      description: str = "") -> dict:
        """
        测试单个端点，返回详细测试结果 + 验证结论

        验证项:
          - HTTP 状态码匹配
          - 响应时间 (默认 < 5s)
          - 响应非空
          - JSON Schema 匹配 (可选)
        """
        result = self.request(method, path, params, json_body)
        checks = {
            "status_match": result["status"] == expected_status,
            "time_ok": result["time_ms"] < 5000,
            "has_body": result["body"] is not None,
        }
        if expected_schema and isinstance(result["body"], dict):
            checks["schema_match"] = self._validate_schema(
                result["body"], expected_schema
            )
        elif expected_schema:
            checks["schema_match"] = False

        # 对于错误路径测试，如果预期非200，不要求 result["ok"]（resp.ok对非200返回False）
        passed = all(checks.values()) and (result["ok"] or expected_status != 200)
        return {
            "test": description or f"{method} {path}",
            "passed": passed,
            "endpoint": path,
            "method": method,
            "expected_status": expected_status,
            "result": result,
            "checks": checks,
        }

    def _validate_schema(self, data: dict, schema: dict) -> bool:
        """简化 JSON Schema 验证 (仅检查必填字段是否存在)"""
        if "required" in schema:
            for field in schema["required"]:
                if field not in data:
                    return False
        if "type" in schema:
            expected = schema["type"]
            if expected == "object" and not isinstance(data, dict):
                return False
            if expected == "array" and not isinstance(data, list):
                return False
        return True

    # ── 性能基准 ─────────────────────────────────────

    def benchmark(self, path: str, method: str = "GET",
                  json_body: Any = None,
                  requests: int = 30, concurrency: int = 3,
                  description: str = "") -> dict:
        """
        性能基准测试

        参数:
            requests: 总请求数
            concurrent: 并发数 (通过线程池模拟)

        返回:
            {
                "total_requests": int,
                "successful": int,
                "failed": int,
                "total_time_ms": float,
                "avg_ms": float,
                "p50_ms": float,
                "p95_ms": float,
                "p99_ms": float,
                "min_ms": float,
                "max_ms": float,
                "throughput_req_per_sec": float,
                "status_codes": {code: count},
                "errors": [error_msg, ...]
            }
        """
        import concurrent.futures

        def _single_req(_):
            t0 = time.monotonic()
            try:
                resp = self._session.request(
                    method=method.upper(),
                    url=f"{self.base_url}{path}" if self.base_url else path,
                    json=json_body, timeout=self.timeout,
                    verify=self.verify_ssl,
                )
                elapsed = (time.monotonic() - t0) * 1000
                return {
                    "ok": resp.ok,
                    "status": resp.status_code,
                    "time_ms": elapsed,
                    "error": None,
                }
            except Exception as e:
                elapsed = (time.monotonic() - t0) * 1000
                return {"ok": False, "status": 0, "time_ms": elapsed,
                        "error": str(e)}

        t_start = time.monotonic()
        latencies = []
        errors = []
        status_codes = {}
        successful = 0
        failed = 0

        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as ex:
            futures = [ex.submit(_single_req, i) for i in range(requests)]
            for fut in concurrent.futures.as_completed(futures):
                r = fut.result()
                latencies.append(r["time_ms"])
                status_codes[r["status"]] = status_codes.get(r["status"], 0) + 1
                if r["ok"]:
                    successful += 1
                else:
                    failed += 1
                    if r["error"]:
                        errors.append(r["error"][:200])

        total_time = (time.monotonic() - t_start) * 1000
        latencies.sort()
        n = len(latencies)

        return {
            "description": description or f"benchmark {method} {path}",
            "total_requests": requests,
            "concurrency": concurrency,
            "successful": successful,
            "failed": failed,
            "total_time_ms": round(total_time, 2),
            "avg_ms": round(statistics.mean(latencies), 2) if latencies else 0,
            "p50_ms": round(latencies[int(n * 0.50)], 2) if n else 0,
            "p95_ms": round(latencies[int(n * 0.95)], 2) if n else 0,
            "p99_ms": round(latencies[int(n * 0.99)], 2) if n else 0,
            "min_ms": round(latencies[0], 2) if latencies else 0,
            "max_ms": round(latencies[-1], 2) if latencies else 0,
            "throughput_req_per_sec": round(requests / (total_time / 1000), 2) if total_time > 0 else 0,
            "status_codes": status_codes,
            "errors": errors[:10],  # 只记录前10个错误
        }

    # ── 套件测试 ─────────────────────────────────────

    def run_suite(self, config: dict) -> dict:
        """
        运行测试套件

        config 格式:
            {
                "base_url": "...",
                "auth": {"bearer": "..."} | {"basic": ["user", "pass"]},
                "tests": [
                    {"path": "...", "method": "GET", "expected_status": 200, ...},
                    ...
                ],
                "benchmarks": [
                    {"path": "...", "requests": 50, "concurrent": 5, ...},
                    ...
                ]
            }
        """
        if "base_url" in config:
            self.base_url = config["base_url"]
        if "auth" in config:
            auth = config["auth"]
            if "bearer" in auth:
                self.set_auth_bearer(auth["bearer"])
            elif "basic" in auth:
                self.set_auth_basic(*auth["basic"])

        results = {"tests": [], "benchmarks": [], "summary": {}}
        test_passed = 0
        test_total = 0
        bench_total = 0

        for t in config.get("tests", []):
            r = self.test_endpoint(
                path=t["path"], method=t.get("method", "GET"),
                params=t.get("params"), json_body=t.get("json"),
                expected_status=t.get("expected_status", 200),
                description=t.get("description", ""),
            )
            results["tests"].append(r)
            test_total += 1
            if r["passed"]:
                test_passed += 1

        for b in config.get("benchmarks", []):
            r = self.benchmark(
                path=b["path"], method=b.get("method", "GET"),
                json_body=b.get("json"),
                requests=b.get("requests", 30),
                concurrency=b.get("concurrency", 3),
                description=b.get("description", ""),
            )
            results["benchmarks"].append(r)
            bench_total += 1

        results["summary"] = {
            "tests_passed": test_passed,
            "tests_total": test_total,
            "tests_pass_rate": f"{test_passed/test_total*100:.1f}%" if test_total else "N/A",
            "benchmarks_total": bench_total,
            "timestamp": datetime.now().isoformat(),
        }
        return results

    # ── 健康检查 ─────────────────────────────────────

    def health_check(self, path: str = "/health") -> dict:
        """快速健康检查，返回状态摘要"""
        r = self.request("GET", path)
        return {
            "service": self.base_url,
            "alive": r["ok"],
            "status": r["status"],
            "latency_ms": r["time_ms"],
            "error": r["error"],
        }

    # ── 错误路径测试 ─────────────────────────────────

    def test_error_paths(self, path: str, method: str = "GET",
                         json_body: Any = None) -> list[dict]:
        """
        测试异常路径:
          - 缺少认证 (401)
          - 资源不存在 (404)
          - 方法不允许 (405)
          - 无效请求体 (400/422)
          - 服务器错误 (500)
        """
        from copy import deepcopy
        results = []

        # 1. 缺少认证头
        old_headers = dict(self._session.headers)
        if "Authorization" in old_headers:
            del self._session.headers["Authorization"]
            r = self.test_endpoint(path, method, json_body=json_body,
                                   expected_status=401,
                                   description="Missing auth → 401")
            results.append(r)
            self._session.headers.update(old_headers)

        # 2. 不存在的资源
        r = self.test_endpoint(path + "/nonexistent-resource-12345", method,
                               expected_status=404,
                               description="Nonexistent resource → 404")
        results.append(r)

        # 3. 方法不允许
        wrong_method = "PUT" if method == "GET" else "DELETE"
        r = self.test_endpoint(path, wrong_method, json_body=json_body,
                               expected_status=405,
                               description=f"Wrong method {wrong_method} → 405")
        results.append(r)

        # 4. 无效请求体
        if json_body is not None:
            bad_body = deepcopy(json_body) if isinstance(json_body, dict) else {}
            if isinstance(bad_body, dict):
                # 删除必填字段
                for key in list(bad_body.keys())[:1]:
                    del bad_body[key]
                r = self.test_endpoint(path, method, json_body=bad_body,
                                       expected_status=422,
                                       description="Missing required field → 422")
                results.append(r)

        return results


# ═══════════════════════════════════════════════════════
#  报告工具
# ═══════════════════════════════════════════════════════

def _format_report(results: dict, fmt: str = "text") -> str:
    """格式化测试报告"""
    if fmt == "json":
        return json.dumps(results, indent=2, default=str)

    lines = []
    summary = results.get("summary", {})
    tests = results.get("tests", [])
    benchmarks = results.get("benchmarks", [])

    lines.append("=" * 60)
    lines.append("  API Test Report")
    lines.append("  " + summary.get("timestamp", ""))
    lines.append("=" * 60)

    if summary:
        lines.append(f"\n📊  Summary:")
        lines.append(f"    Tests:   {summary.get('tests_passed', 0)}/{summary.get('tests_total', 0)} passed ({summary.get('tests_pass_rate', 'N/A')})")
        lines.append(f"    Benchmarks: {summary.get('benchmarks_total', 0)}")

    if tests:
        lines.append(f"\n🧪  Tests ({len(tests)}):")
        for t in tests:
            icon = "✅" if t.get("passed") else "❌"
            status = t.get("result", {}).get("status", "?")
            ms = t.get("result", {}).get("time_ms", "?")
            lines.append(f"  {icon} {t.get('test', '?')} → {status} ({ms}ms)")

    if benchmarks:
        lines.append(f"\n⚡  Benchmarks ({len(benchmarks)}):")
        for b in benchmarks:
            lines.append(f"  {b.get('description', '?')}:")
            lines.append(f"    Requests: {b.get('total_requests')} @ {b.get('concurrency')} concurrent")
            lines.append(f"    Successful: {b.get('successful')} / Failed: {b.get('failed')}")
            lines.append(f"    Latency: avg={b.get('avg_ms')}ms p50={b.get('p50_ms')}ms p95={b.get('p95_ms')}ms p99={b.get('p99_ms')}ms")
            lines.append(f"    Throughput: {b.get('throughput_req_per_sec')} req/s")
            if b.get("errors"):
                lines.append(f"    Errors: {len(b.get('errors'))}")
                for e in b["errors"][:3]:
                    lines.append(f"      - {e}")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════
#  CLI 入口
# ═══════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="API Tester — 端点测试 + 验证 + 基准",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s smoke http://localhost:11343
  %(prog)s test POST http://localhost:11343/v1/chat/completions --json '{"model":"test","messages":[{"role":"user","content":"hi"}]}' --status 200
  %(prog)s benchmark GET http://localhost:11343/health --requests 50 --concurrent 5
  %(prog)s auth-test GET http://localhost:11343/api/data --token YOUR_TOKEN
  %(prog)s suite suite_config.json
        """
    )
    sub = parser.add_subparsers(dest="command", help="子命令")

    # smoke
    p_smoke = sub.add_parser("smoke", help="快速健康检查")
    p_smoke.add_argument("url", help="服务 URL (如 http://localhost:11343)")
    p_smoke.add_argument("--path", default="/health", help="健康检查路径 (默认 /health)")
    p_smoke.add_argument("--token", help="Bearer Token")

    # test
    p_test = sub.add_parser("test", help="测试单个端点")
    p_test.add_argument("method", help="HTTP 方法 (GET/POST/PUT/DELETE)")
    p_test.add_argument("url", help="完整 URL")
    p_test.add_argument("--json", help="JSON 请求体 (JSON 字符串)")
    p_test.add_argument("--status", type=int, default=200, help="期望状态码")
    p_test.add_argument("--token", help="Bearer Token")
    p_test.add_argument("--desc", help="测试描述", default="")

    # benchmark
    p_bench = sub.add_parser("benchmark", help="性能基准测试")
    p_bench.add_argument("method", help="HTTP 方法")
    p_bench.add_argument("url", help="完整 URL")
    p_bench.add_argument("--json", help="JSON 请求体")
    p_bench.add_argument("--requests", type=int, default=30, help="总请求数")
    p_bench.add_argument("--concurrent", type=int, default=3, help="并发数")
    p_bench.add_argument("--token", help="Bearer Token")

    # auth-test (异常路径)
    p_auth = sub.add_parser("auth-test", help="认证 + 异常路径测试")
    p_auth.add_argument("method", help="HTTP 方法")
    p_auth.add_argument("url", help="完整 URL")
    p_auth.add_argument("--json", help="JSON 请求体")
    p_auth.add_argument("--token", help="Bearer Token")

    # suite
    p_suite = sub.add_parser("suite", help="运行测试套件 (JSON 配置)")
    p_suite.add_argument("config", help="套件配置文件路径")
    p_suite.add_argument("--output", help="输出报告路径 (.json / .md)")

    # report 格式
    parser.add_argument("--format", choices=["text", "json"], default="text",
                        help="输出格式")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)

    # 解析 URL 提取 base_url
    def _parse_url(url):
        """从 URL 分离 base_url 和 path"""
        from urllib.parse import urlparse
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        return base, path

    try:
        # ── smoke ──
        if args.command == "smoke":
            base = args.url.rstrip("/")
            tester = ApiTester(base)
            if args.token:
                tester.set_auth_bearer(args.token)
            r = tester.health_check(args.path)
            if r["alive"]:
                print(f"✅ {base} — alive ({r['latency_ms']}ms)")
            else:
                print(f"❌ {base} — dead (status={r['status']}, error={r['error']})")

        # ── test ──
        elif args.command == "test":
            base, path = _parse_url(args.url)
            tester = ApiTester(base)
            if args.token:
                tester.set_auth_bearer(args.token)
            body = json.loads(args.json) if args.json else None
            r = tester.test_endpoint(
                path, args.method, json_body=body,
                expected_status=args.status, description=args.desc,
            )
            print(json.dumps(r, indent=2, default=str))

        # ── benchmark ──
        elif args.command == "benchmark":
            base, path = _parse_url(args.url)
            tester = ApiTester(base)
            if args.token:
                tester.set_auth_bearer(args.token)
            body = json.loads(args.json) if args.json else None
            r = tester.benchmark(
                path, args.method, json_body=body,
                requests=args.requests, concurrency=args.concurrent,
            )
            print(json.dumps(r, indent=2, default=str))

        # ── auth-test ──
        elif args.command == "auth-test":
            base, path = _parse_url(args.url)
            tester = ApiTester(base)
            if args.token:
                tester.set_auth_bearer(args.token)
            body = json.loads(args.json) if args.json else None
            results = tester.test_error_paths(path, args.method, body)
            all_pass = all(r["passed"] for r in results)
            print(f"{'✅ All passed' if all_pass else '❌ Some failed'} ({len(results)} tests)")
            for r in results:
                icon = "✅" if r["passed"] else "❌"
                s = r.get("result", {}).get("status", "?")
                ms = r.get("result", {}).get("time_ms", "?")
                print(f"  {icon} {r['test']} → {s} ({ms}ms)")

        # ── suite ──
        elif args.command == "suite":
            with open(args.config) as f:
                config = json.load(f)
            tester = ApiTester()
            results = tester.run_suite(config)
            report = _format_report(results, args.format)
            if args.output:
                with open(args.output, "w") as f:
                    f.write(report)
                print(f"📄 Report saved to {args.output}")
            else:
                print(report)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
