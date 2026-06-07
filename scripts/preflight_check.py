#!/usr/bin/env python3
"""
preflight_check.py — 环境预检 + SOP引用校验 + 脚本可用性
===========================================================
整合: preflight_check + sop_script_audit + 脚本可用性扫描
解决R45 P0问题"环境假设失败"(4次,每次12回合浪费)

用法:
  python scripts/preflight_check.py                      # 默认三验(网络/环境/依赖)
  python scripts/preflight_check.py --full               # 全量: 三验+引用校验+脚本可用性
  python scripts/preflight_check.py --refs               # 仅做SOP引用校验
  python scripts/preflight_check.py --only net           # 仅验网络
  python scripts/preflight_check.py --only env           # 仅验环境变量
  python scripts/preflight_check.py --only deps          # 仅验依赖
  python scripts/preflight_check.py --urls api.example.com  # 自定义URL
  python scripts/preflight_check.py --deps python3,git   # 自定义依赖
  python scripts/preflight_check.py --json               # JSON输出
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import re
from datetime import datetime
from pathlib import Path


# ── 路径 ──
GA_ROOT = Path(__file__).resolve().parent.parent
MEMORY_DIR = GA_ROOT / "memory"
SCRIPTS_DIR = GA_ROOT / "scripts"


# ── 默认配置 ───────────────────────────────────────────
DEFAULT_URLS = [
    "https://www.baidu.com",
    "https://api.github.com",
    "https://pypi.org",
]

DEFAULT_DEPS = [
    "python3", "pip3", "git", "curl", "chromium-browser",
]

SENSITIVE_PATTERNS = [
    r'(?i)(api[_-]?key|apikey)',
    r'(?i)(secret|secret[_-]?key)',
    r'(?i)(token|access[_-]?token)',
    r'(?i)(password|passwd|pwd)',
    r'AWS[A-Z_]+KEY',
    r'GITHUB[A-Z_]+TOKEN',
    r'SLACK[A-Z_]+TOKEN',
    r'DISCORD[A-Z_]+TOKEN',
    r'TELEGRAM[A-Z_]+TOKEN',
    r'OPENAI[A-Z_]+KEY',
    r'ANTHROPIC[A-Z_]+KEY',
    r'SK-[a-zA-Z0-9]+',
]

SAFE_WHITELIST = {
    "LS_COLORS", "DBUS_SESSION_BUS_ADDRESS", "DISPLAY",
    "PYTHON_HASH_SEED", "PYTHONDONTWRITEBYTECODE",
    "LESSOPEN", "LESSCLOSE", "OLDPWD", "PWD",
    "HOME", "USER", "LOGNAME", "SHELL", "TERM", "PATH",
    "LANG", "LC_ALL", "LC_CTYPE", "TZ",
}

# ── SOP引用校验配置 (来自 sop_script_audit.py) ──
IGNORE_PATTERNS = [
    r'https?://',
    r'^#',
    r'^\s*[-*+]\s',
]

KNOWN_ALIASES = {
    "solver_role_sops": "solver_writer_sop",
    "vision_api.template": "vision_api.template",
    "keychain": "keychain",
    "procmem_scanner": "procmem_scanner",
    "ui_detect.py": "ui_detect.py",
    "ocr_utils.py": "ocr_utils.py",
    "adb_ui.py": "adb_ui.py",
}

DIRECTORY_NAMES = {"keychain", "procmem_scanner", "L4_raw_sessions", "utils",
                   "templates", "subagent", "agents"}


class PreflightChecker:
    """一站式环境预检 + SOP引用校验 + 脚本可用性"""

    def __init__(self, urls=None, deps=None, only=None, json_output=False, no_color=False, full=False):
        self.urls = urls or DEFAULT_URLS
        self.deps = deps or DEFAULT_DEPS
        self.only = only  # None='all', or 'net'/'env'/'deps'/'refs'/'scripts'
        self.json_output = json_output
        self.no_color = no_color
        self.full = full  # --full: run all checks
        self.results = {
            "timestamp": datetime.now().isoformat(),
            "hostname": os.uname().nodename,
            "checks": {}
        }
        self._color_on = not no_color

    def _color(self, code, text):
        if not self._color_on:
            return text
        return f"\033[{code}m{text}\033[0m"

    def green(self, text): return self._color("92", text)
    def yellow(self, text): return self._color("93", text)
    def red(self, text): return self._color("91", text)
    def bold(self, text): return self._color("1", text)

    # ── 1. 网络连通性 ──
    def _check_network(self):
        checks = {}
        all_ok = True
        for url in self.urls:
            try:
                r = subprocess.run(
                    ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--connect-timeout", "5", url],
                    capture_output=True, text=True, timeout=10
                )
                code = r.stdout.strip()
                ok = code.startswith("2") or code.startswith("3")
                checks[url] = {"status": "ok" if ok else "unexpected", "http_code": code}
                if not ok:
                    all_ok = False
            except subprocess.TimeoutExpired:
                checks[url] = {"status": "timeout", "http_code": "000"}
                all_ok = False
            except Exception as e:
                checks[url] = {"status": "error", "error": str(e)}
                all_ok = False
        return {"ok": all_ok, "checks": checks}

    # ── 2. 环境变量扫描 ──
    def _check_env(self):
        findings = []
        suspicious = []
        for name, value in sorted(os.environ.items()):
            if name in SAFE_WHITELIST:
                continue
            name_matched = False
            for pat in SENSITIVE_PATTERNS:
                if re.search(pat, name):
                    name_matched = True
                    break
            value_matched = False
            if re.search(r'(?i)(sk-[a-zA-Z0-9]{10,}|ghp_[a-zA-Z0-9]{10,}|gho_[a-zA-Z0-9]{10,})', value or ''):
                value_matched = True

            if name_matched or value_matched:
                preview = value[:6] + "****" + value[-4:] if value and len(value) > 10 else (value[:8] if value else "")
                item = {"name": name, "preview": preview, "matched_by_name": name_matched, "matched_by_value": value_matched}
                findings.append(item)
                if value:
                    suspicious.append(item)

        return {
            "ok": len(suspicious) == 0,
            "total_vars": len(os.environ),
            "findings": findings,
            "suspicious_count": len(suspicious),
            "recommendation": "需清理" if suspicious else "安全"
        }

    # ── 3. 依赖检测 ──
    def _check_deps(self):
        checks = {}
        all_ok = True
        for dep in self.deps:
            path = shutil.which(dep)
            if path:
                try:
                    r = subprocess.run([dep, "--version"], capture_output=True, text=True, timeout=5)
                    ver = r.stdout.strip().split('\n')[0][:80] or r.stderr.strip().split('\n')[0][:80]
                except:
                    ver = "available (no --version)"
                checks[dep] = {"status": "ok", "path": path, "version": ver}
            else:
                checks[dep] = {"status": "missing", "path": None, "version": None}
                all_ok = False
        return {"ok": all_ok, "checks": checks}

    # ── 4. SOP引用校验 (来自 sop_script_audit.py) ──
    def _extract_references(self, text, source_file):
        """从SOP文本中提取文件名引用"""
        refs = set()
        # 模式1: markdown 链接 [text](path)
        for m in re.finditer(r'\[([^\]]+)\]\(([^)]+)\)', text):
            path = m.group(2).strip()
            if not any(re.match(p, path) for p in [re.compile(x) for x in IGNORE_PATTERNS]):
                if len(path) < 200 and (path[0].isalnum() or path.startswith(('/', '.', '~'))):
                    refs.add(path)
        # 模式2: 内联代码 `path/to/file`
        for m in re.finditer(r'`([^`]+)`', text):
            path = m.group(1).strip()
            if len(path) > 200 or len(path) < 3:
                continue
            has_ext = any(path.endswith(ext) for ext in ('.py', '.md', '.sh', '.txt', '.json', '.yaml', '.yml', '.toml', '.cfg', '.conf'))
            has_slash = '/' in path
            if not (has_ext or has_slash):
                continue
            if not path[0].isalnum() and path[0] not in ('.', '/', '_', '~'):
                continue
            if any(c in path for c in ('\n', ' ')):
                continue
            if not any(re.match(p, path) for p in [re.compile(x) for x in IGNORE_PATTERNS]):
                refs.add(path)
        # 模式3: scripts/xxx.py 路径
        for m in re.finditer(r'(?:scripts|tools?|utils?|lib)/[\w./_-]+\.(?:py|sh|md|txt|json|yaml|yml|toml|cfg|conf)', text):
            refs.add(m.group(0))
        # 模式4: memory/ 下文件
        for m in re.finditer(r'memory/[\w./_-]+\.(?:md|py|txt)', text):
            refs.add(m.group(0))
        return sorted(refs)

    def _resolve_ref(self, ref, source_sop):
        """解析引用路径"""
        ref = ref.strip()
        if ref.startswith('/'):
            p = Path(ref)
            return (p.exists(), str(p))
        for base_dir in [MEMORY_DIR, SCRIPTS_DIR, GA_ROOT / "temp"]:
            candidate = base_dir / ref
            if candidate.exists():
                return (True, str(candidate))
            if ref.startswith('../'):
                alt = GA_ROOT / ref[3:]
                if alt.exists():
                    return (True, str(alt))
        ref_stem = Path(ref).stem
        if ref_stem in KNOWN_ALIASES:
            alias = KNOWN_ALIASES[ref_stem]
            for base_dir in [MEMORY_DIR, SCRIPTS_DIR]:
                candidate = base_dir / alias
                if candidate.exists():
                    return (True, str(candidate))
                if not alias.endswith('.md') and not alias.endswith('.py'):
                    for ext in ['.md', '.py']:
                        c2 = base_dir / f"{alias}{ext}"
                        if c2.exists():
                            return (True, str(c2))
        if ref_stem in DIRECTORY_NAMES:
            for base_dir in [MEMORY_DIR, SCRIPTS_DIR, GA_ROOT / "temp"]:
                candidate = base_dir / ref_stem
                if candidate.is_dir():
                    return (True, str(candidate))
        return (False, "(not found)")

    def _scan_sop(self, sop_path):
        """扫描单个SOP文件"""
        results = []
        try:
            text = sop_path.read_text(encoding='utf-8', errors='replace')
        except Exception as e:
            return [{"file": sop_path.name, "error": str(e)}]
        refs = self._extract_references(text, sop_path.name)
        for ref in refs:
            exists, resolved = self._resolve_ref(ref, sop_path.name)
            results.append({"sop_file": sop_path.name, "reference": ref, "exists": exists, "resolved_to": resolved, "is_drift": not exists})
        return results

    def _check_refs(self):
        """SOP引用完整性校验"""
        sop_files = sorted([f for f in MEMORY_DIR.iterdir() if f.suffix in ('.md', '.py') and not f.name.startswith('.')])
        all_results = []
        for sf in sop_files:
            all_results.extend(self._scan_sop(sf))

        # 过滤模板/变量引用
        filtered = []
        for r in all_results:
            ref = r.get("reference", "")
            if '{' in ref or '}' in ref:
                continue
            if re.match(r'^R\d+X?_', ref) or ref in ('input.txt', 'context.json', 'WHITEBOARD.md',
               'exploration_findings.md', 'goal_state.json', 'design-image-prompt-engineer.md'):
                continue
            non_ascii = sum(1 for c in ref if ord(c) > 127)
            if non_ascii > len(ref) * 0.3:
                continue
            filtered.append(r)

        drifts = [r for r in filtered if r.get("is_drift")]
        total = len(filtered)
        ok = len(drifts) == 0
        return {
            "ok": ok,
            "total_sops": len(sop_files),
            "total_refs": total,
            "drift_count": len(drifts),
            "drifts": drifts,
        }

    # ── 5. 脚本可用性扫描 ──
    def _check_scripts(self):
        """检查所有脚本基本可用性 (--help)"""
        checks = {}
        all_ok = True
        for f in sorted(SCRIPTS_DIR.iterdir()):
            if f.suffix == '.py' and not f.name.startswith('_') and not f.name.startswith('.'):
                script = f"scripts/{f.name}"
                try:
                    r = subprocess.run(
                        [sys.executable, str(f), "--help"],
                        capture_output=True, text=True, timeout=10
                    )
                    has_help = "--help" in r.stdout or "--help" in r.stderr or "usage:" in r.stdout.lower() or "用法" in r.stdout or r.returncode == 0
                    checks[script] = {"status": "ok" if has_help else "no_help", "exit_code": r.returncode}
                except subprocess.TimeoutExpired:
                    checks[script] = {"status": "timeout"}
                    all_ok = False
                except Exception as e:
                    checks[script] = {"status": "error", "error": str(e)}
                    all_ok = False
        return {"ok": all_ok, "total": len(checks), "checks": checks}

    # ── 6. 服务可达性 (新增) ──
    def _check_services(self):
        """检关键本地服务是否可达"""
        services = {
            "code-server (9090)": ("http://127.0.0.1:9090", None),
            "OpenLLM (9119)": ("http://127.0.0.1:9119", None),
            "hermes-dashboard": (None, "hermes-dashboard"),
        }
        checks = {}
        all_ok = True
        for name, (url, svc) in services.items():
            if url:
                try:
                    r = subprocess.run(
                        ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--connect-timeout", "3", url],
                        capture_output=True, text=True, timeout=5
                    )
                    code = r.stdout.strip()
                    ok = code.startswith("2") or code.startswith("3") or code == "000"
                    checks[name] = {"status": "ok" if ok else "unexpected", "http_code": code, "url": url}
                    if not ok:
                        all_ok = False
                except Exception as e:
                    checks[name] = {"status": "error", "error": str(e), "url": url}
                    all_ok = False
            if svc:
                try:
                    r = subprocess.run(["systemctl", "is-active", svc], capture_output=True, text=True, timeout=5)
                    active = r.stdout.strip() == "active"
                    checks[name] = {"status": "ok" if active else "inactive", "service": svc}
                    if not active:
                        all_ok = False
                except Exception as e:
                    checks[name] = {"status": "error", "error": str(e), "service": svc}
                    all_ok = False
        return {"ok": all_ok, "checks": checks}

    # ── 7. 磁盘余量 (新增) ──
    def _check_disk(self):
        """检查磁盘空间"""
        checks = {}
        all_ok = True
        try:
            r = subprocess.run(["df", "-h", "/"], capture_output=True, text=True, timeout=5)
            lines = r.stdout.strip().split('\n')
            if len(lines) >= 2:
                parts = lines[1].split()
                total = parts[1] if len(parts) > 1 else "?"
                used = parts[2] if len(parts) > 2 else "?"
                avail = parts[3] if len(parts) > 3 else "?"
                use_pct = parts[4] if len(parts) > 4 else "?"
                checks["root_fs"] = {
                    "total": total, "used": used, "avail": avail, "use_pct": use_pct,
                    "status": "ok" if int(use_pct.rstrip('%')) < 85 else "warning"
                }
                if int(use_pct.rstrip('%')) >= 85:
                    all_ok = False
            # RAM
            r2 = subprocess.run(["free", "-m"], capture_output=True, text=True, timeout=5)
            for line in r2.stdout.split('\n'):
                if line.startswith("Mem:"):
                    parts = line.split()
                    checks["memory"] = {
                        "total_mb": parts[1], "used_mb": parts[2], "avail_mb": parts[6],
                        "status": "ok" if int(parts[6]) > 200 else "warning"
                    }
                    if int(parts[6]) <= 200:
                        all_ok = False
                    break
        except Exception as e:
            checks["error"] = str(e)
            all_ok = False
        return {"ok": all_ok, "checks": checks}

    # ── 8. 密钥存在性 (新增) ──
    def _check_keys(self):
        """检查密钥文件完整性"""
        checks = {}
        all_ok = True
        key_files = [
            ("mykey.py", GA_ROOT / "mykey.py"),
            ("mykey_template_en.py", GA_ROOT / "mykey_template_en.py"),
        ]
        for name, path in key_files:
            exists = path.exists()
            checks[name] = {"exists": exists, "path": str(path)}
            if not exists:
                all_ok = False
        # 检查密钥环境变量
        env_keys = [k for k in os.environ if any(p in k.upper() for p in ["OPENAI", "ANTHROPIC", "API_KEY", "SECRET"])]
        checks["env_keys_found"] = len(env_keys)
        return {"ok": all_ok, "key_files": checks, "env_keys_count": len(env_keys)}

    # ── 9. 依赖完整性增强 (新增) ──
    def _check_deps_full(self):
        """更全面的依赖检查"""
        base = self._check_deps()
        extra_deps = ["node", "npm", "vim", "tmux", "systemctl", "docker"]
        extra_checks = {}
        for dep in extra_deps:
            path = shutil.which(dep)
            extra_checks[dep] = {"status": "ok" if path else "missing", "path": path}
        base["extra_checks"] = extra_checks
        base["ok"] = base["ok"] and all(c["status"] == "ok" for c in extra_checks.values())
        return base

    # ── 主入口 ──
    def run(self):
        # Determine which checks to run
        run_all = self.full or (self.only is None)
        
        # Explicit --only takes precedence
        checks_to_run = []
        if self.full:
            checks_to_run = ['net', 'env', 'deps', 'refs', 'scripts', 'services', 'disk', 'keys', 'deps_full']
        elif self.only:
            checks_to_run = [self.only]
        else:
            checks_to_run = ['net', 'env', 'deps']

        for c in checks_to_run:
            if c == 'net':
                self.results["checks"]["network"] = self._check_network()
            elif c == 'env':
                self.results["checks"]["environment"] = self._check_env()
            elif c == 'deps':
                self.results["checks"]["dependencies"] = self._check_deps()
            elif c == 'refs':
                self.results["checks"]["sop_references"] = self._check_refs()
            elif c == 'scripts':
                self.results["checks"]["script_health"] = self._check_scripts()
            elif c == 'services':
                self.results["checks"]["services"] = self._check_services()
            elif c == 'disk':
                self.results["checks"]["disk"] = self._check_disk()
            elif c == 'keys':
                self.results["checks"]["keys"] = self._check_keys()
            elif c == 'deps_full':
                self.results["checks"]["deps_full"] = self._check_deps_full()

        all_ok = all(c.get("ok", False) for c in self.results["checks"].values())
        self.results["overall"] = "pass" if all_ok else "fail"
        return self.results

    # ── 终端输出 ──
    def print_report(self):
        if self.json_output:
            print(json.dumps(self.results, indent=2, ensure_ascii=False))
            return

        r = self.results
        overall = r["overall"]
        status_char = "✅" if overall == "pass" else "❌"
        print(f"\n{self.bold('✦ 环境预检报告')}  {status_char}")
        print(f"  {r['hostname']} @ {r['timestamp']}\n")

        # 网络
        if "network" in r["checks"]:
            nc = r["checks"]["network"]
            nok = nc["ok"]
            print(f"  {self.green('✓') if nok else self.red('✗')} 网络连通性 ({len(nc['checks'])} URL)")
            for url, info in nc["checks"].items():
                url_short = url[:60] + "..." if len(url) > 60 else url
                if info["status"] == "ok":
                    print(f"     {self.green('✓')} {url_short} (HTTP {info['http_code']})")
                else:
                    print(f"     {self.red('✗')} {url_short} ({info.get('status','?')} HTTP {info.get('http_code','?')})")
            print()

        # 环境变量
        if "environment" in r["checks"]:
            ec = r["checks"]["environment"]
            eok = ec["ok"]
            print(f"  {self.green('✓') if eok else self.red('✗')} 环境变量 ({ec['total_vars']} 个变量, {ec['suspicious_count']} 个可疑)")
            for f in ec["findings"]:
                if f.get("matched_by_value") or f.get("matched_by_name"):
                    print(f"     {self.yellow('⚠')} {f['name']} = {f['preview']}")
            if ec["findings"]:
                print(f"     {self.yellow('建议')}: {ec['recommendation']}")
            print()

        # 依赖
        if "dependencies" in r["checks"]:
            dc = r["checks"]["dependencies"]
            dok = dc["ok"]
            print(f"  {self.green('✓') if dok else self.red('✗')} 依赖检测 ({len(dc['checks'])} 项)")
            for dep, info in dc["checks"].items():
                if info["status"] == "ok":
                    v = f" ({info['version']})" if info.get('version') else ""
                    print(f"     {self.green('✓')} {dep}{v}")
                else:
                    print(f"     {self.red('✗')} {dep} — 缺失!")
            print()

        # SOP引用校验
        if "sop_references" in r["checks"]:
            src = r["checks"]["sop_references"]
            sok = src["ok"]
            print(f"  {self.green('✓') if sok else self.red('✗')} SOP引用校验 ({src['total_sops']} SOP, {src['total_refs']} 引用, {src['drift_count']} 漂移)")
            if src["drifts"]:
                for d in src["drifts"][:10]:  # 最多显示10条
                    print(f"     {self.red('✗')} {d['sop_file']}: `{d['reference']}` → {d['resolved_to']}")
                if len(src["drifts"]) > 10:
                    print(f"     ... 还有 {len(src['drifts'])-10} 条漂移未显示")
            print()

        # 脚本健康度
        if "script_health" in r["checks"]:
            shc = r["checks"]["script_health"]
            shok = shc["ok"]
            total = shc["total"]
            bad = sum(1 for s in shc.get("checks", {}).values() if s.get("status") != "ok")
            print(f"  {self.green('✓') if shok else self.red('✗')} 脚本可用性 ({total} 脚本, {bad} 异常)")
            if shc.get("checks"):
                for name, info in shc["checks"].items():
                    if info.get("status") != "ok":
                        print(f"     {self.red('✗')} {name} ({info.get('status','?')})")
            print()

        # 服务可达性 (新增)
        if "services" in r["checks"]:
            svc = r["checks"]["services"]
            sok = svc["ok"]
            print(f"  {self.green('✓') if sok else self.red('✗')} 服务可达性 ({len(svc['checks'])} 项)")
            for name, info in svc["checks"].items():
                if info["status"] == "ok":
                    print(f"     {self.green('✓')} {name}")
                else:
                    print(f"     {self.red('✗')} {name} ({info.get('status','?')})")
            print()

        # 磁盘余量 (新增)
        if "disk" in r["checks"]:
            dc = r["checks"]["disk"]
            dok = dc["ok"]
            print(f"  {self.green('✓') if dok else self.red('✗')} 磁盘余量")
            for name, info in dc["checks"].items():
                if name == "root_fs":
                    status = self.green('✓') if info['status'] == 'ok' else self.red('✗')
                    print(f"     {status} 磁盘: {info['avail']} 可用 / {info['total']} ({info['use_pct']})")
                elif name == "memory":
                    status = self.green('✓') if info['status'] == 'ok' else self.red('✗')
                    print(f"     {status} 内存: {info['avail_mb']}MB 可用 / {info['total_mb']}MB")
                else:
                    print(f"     {name}: {info}")
            print()

        # 密钥存在性 (新增)
        if "keys" in r["checks"]:
            kc = r["checks"]["keys"]
            kok = kc["ok"]
            print(f"  {self.green('✓') if kok else self.red('✗')} 密钥完整性")
            for name, info in kc.get("key_files", {}).items():
                status = self.green('✓') if info['exists'] else self.red('✗')
                print(f"     {status} {name}")
            print(f"     环境变量密钥发现: {kc.get('env_keys_count', '?')} 个")
            print()

        # 依赖完整性增强 (新增)
        if "deps_full" in r["checks"]:
            dfc = r["checks"]["deps_full"]
            dfok = dfc["ok"]
            extra = dfc.get("extra_checks", {})
            print(f"  {self.green('✓') if dfok else self.red('✗')} 依赖完整性增强 ({len(extra)} 项)")
            for dep, info in extra.items():
                status = self.green('✓') if info['status'] == 'ok' else self.red('✗')
                print(f"     {status} {dep}")
            print()

        # 总体
        if overall == "pass":
            print(f"  {self.green('✅ 全部通过，可以开始任务。')}")
        else:
            print(f"  {self.red('❌ 存在需要处理的问题，建议先修复。')}")
        print()


def main():
    pa = argparse.ArgumentParser(
        description="preflight_check.py — 环境预检 + SOP引用校验 + 脚本可用性",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/preflight_check.py                           # 默认三验
  python scripts/preflight_check.py --full                    # 全量: 网络+环境+依赖+服务+磁盘+密钥+引用+脚本
  python scripts/preflight_check.py --refs                    # 仅SOP引用校验
  python scripts/preflight_check.py --only net                # 仅验网络
  python scripts/preflight_check.py --only env                # 仅验环境变量
  python scripts/preflight_check.py --only deps               # 仅验依赖
  python scripts/preflight_check.py --only services           # 仅验服务可达性
  python scripts/preflight_check.py --only disk               # 仅验磁盘余量
  python scripts/preflight_check.py --only keys               # 仅验密钥完整性
  python scripts/preflight_check.py --urls api.example.com    # 自定义URL
  python scripts/preflight_check.py --deps python3,git        # 自定义依赖
  python scripts/preflight_check.py --json                    # JSON输出
        """
    )
    pa.add_argument("--json", action="store_true", help="JSON格式输出")
    pa.add_argument("--no-color", action="store_true", help="禁用颜色")
    pa.add_argument("--only", choices=["net", "env", "deps", "refs", "scripts", "services", "disk", "keys", "deps_full"], help="只做单项检查")
    pa.add_argument("--urls", help="自定义URL列表(逗号分隔)")
    pa.add_argument("--deps", help="自定义依赖列表(逗号分隔)")
    pa.add_argument("--full", action="store_true", help="全量检查: 网络+环境+依赖+服务+磁盘+密钥+依赖增强+引用+脚本")

    args = pa.parse_args()

    urls = [u.strip() for u in args.urls.split(",") if u.strip()] if args.urls else None
    deps = [d.strip() for d in args.deps.split(",") if d.strip()] if args.deps else None

    checker = PreflightChecker(
        urls=urls,
        deps=deps,
        only=args.only,
        json_output=args.json,
        no_color=args.no_color,
        full=args.full,
    )
    checker.run()
    checker.print_report()

    sys.exit(0 if checker.results["overall"] == "pass" else 1)


if __name__ == "__main__":
    main()
