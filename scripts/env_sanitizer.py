#!/usr/bin/env python3
"""
env_sanitizer.py — 环境变量密钥检测与清理
=============================================
检测环境变量中的密钥模式，支持白名单 & 自动sanitize。

依赖: 无(Python标准库)
用法:
  python scripts/env_sanitizer.py scan              # 扫描当前环境变量
  python scripts/env_sanitizer.py scan --pid 1234   # 扫描指定进程的环境
  python scripts/env_sanitizer.py sanitize          # 扫描 + 输出sanitized建议
  python scripts/env_sanitizer.py check --name MY_KEY # 检查单个变量
  python scripts/env_sanitizer.py list-whitelist    # 列出白名单
  python scripts/env_sanitizer.py add-whitelist MY_KEY # 将变量加入白名单
"""

import os
import re
import sys
import json
import argparse
from pathlib import Path

# ── 密钥模式定义 ─────────────────────────────────────────────
SECRET_PATTERNS = {
    "GitHub Token": [
        r'gh[ps]_[0-9a-zA-Z]{36}',
        r'github_pat_[0-9a-zA-Z_]{22,}',
        r'gho_[0-9a-zA-Z_]{36}',
    ],
    "API Key (通用)": [
        r'sk-[0-9a-zA-Z]{20,}',
        r'[Aa][Pp][Ii]_?[Kk][Ee][Yy]=.{16,}',
        r'[Aa][Pp][Ii]_?[Ss][Ee][Cc][Rr][Ee][Tt]=.{16,}',
    ],
    "AWS Key": [
        r'AKIA[0-9A-Z]{16}',
        r'(?i)aws_secret_access_key=.+',
        r'(?i)aws_access_key_id=.+',
    ],
    "Cloudflare Token": [
        r'cfut_[0-9a-zA-Z_]{30,}',
        r'[Cc][Ff][-_]?[Tt][Oo][Kk][Ee][Nn]=.+',
    ],
    "通用Secret/Password": [
        r'(?i)(?:secret|password|token|key)\s*=\s*[''"]?[A-Za-z0-9_\-\.]{16,}',
        r'(?i)(?:secret|password|token|key)\s*[:=]\s*.{16,}',
    ],
    "JWT": [
        r'eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+',
    ],
    "私钥特征": [
        r'-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----',
    ],
    "连接字符串": [
        r'mongodb(?:\+srv)?://[^@]+@',
        r'postgres(?:ql)?://[^:]+:[^@]+@',
        r'mysql://[^:]+:[^@]+@',
        r'redis://:[^@]+@',
    ],
}

# ── 白名单配置 ───────────────────────────────────────────────
# 环境变量名完全匹配（不区分大小写）
DEFAULT_WHITELIST = {
    # GA系统白名单
    "AGNES_API_KEY",
    "AUXILIARY_VISION_API_KEY",
    "AUXILIARY_VISION_BASE_URL",
    "BROWSERLESS_TOKEN",
    "CLOUDFLARE_API_TOKEN",
    "FEISHU_APP_SECRET",
    "FEISHU_APP_ID",
    "HERMES_SESSION_KEY",
    "HERMES_REDACT_SECRETS",
    "MEM0_API_KEY",
    # 安全相关
    "PATH",
    "HOME",
    "USER",
    "SHELL",
    "LANG",
    "DISPLAY",
    "TERM",
    "LOGNAME",
    "PWD",
    "OLDPWD",
}

# ── WhiteListManager ─────────────────────────────────────────
class WhiteListManager:
    """管理白名单（存~/.config/env_sanitizer/whitelist.json）"""

    def __init__(self):
        self.config_dir = Path.home() / ".config" / "env_sanitizer"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.whitelist_file = self.config_dir / "whitelist.json"
        self._whitelist = self._load()

    def _load(self) -> set:
        if self.whitelist_file.exists():
            try:
                data = json.loads(self.whitelist_file.read_text())
                return set(data.get("whitelist", []))
            except:
                pass
        return set(DEFAULT_WHITELIST)

    def _save(self):
        self.whitelist_file.write_text(json.dumps({
            "whitelist": sorted(self._whitelist),
            "version": "1.0",
        }, indent=2))

    def get(self) -> set:
        return self._whitelist

    def add(self, name: str) -> bool:
        name = name.upper()
        if name in self._whitelist:
            return False
        self._whitelist.add(name)
        self._save()
        return True

    def remove(self, name: str) -> bool:
        name = name.upper()
        if name not in self._whitelist:
            return False
        self._whitelist.discard(name)
        self._save()
        return True

    def reset(self):
        self._whitelist = set(DEFAULT_WHITELIST)
        self._save()


# ── EnvScanner ──────────────────────────────────────────────
class EnvScanner:
    """环境变量扫描器"""

    def __init__(self, whitelist: set = None):
        self.whitelist = whitelist or set()
        self.findings = []  # list of dict

    def scan_environ(self, env: dict = None) -> list:
        """扫描环境变量字典"""
        if env is None:
            env = dict(os.environ)
        self.findings = []
        for name, value in env.items():
            if name.upper() in {w.upper() for w in self.whitelist}:
                continue
            matches = self._check_value(name, value)
            if matches:
                self.findings.append({
                    "name": name,
                    "value_preview": self._mask(value),
                    "value_length": len(value),
                    "matches": matches,
                    "severity": "high" if any(m[0] in ("GitHub Token", "AWS Key") for m in matches) else "medium",
                })
        return self.findings

    def scan_process(self, pid: int) -> list:
        """扫描进程的环境变量"""
        try:
            environ_path = f"/proc/{pid}/environ"
            if not os.path.exists(environ_path):
                return []
            raw = open(environ_path, "rb").read()
            # environ文件以null分隔
            parts = raw.split(b"\x00")
            env = {}
            for part in parts:
                if not part:
                    continue
                try:
                    decoded = part.decode("utf-8", errors="replace")
                except:
                    continue
                if "=" in decoded:
                    k, v = decoded.split("=", 1)
                    env[k] = v
            return self.scan_environ(env)
        except (PermissionError, FileNotFoundError):
            return []

    def _check_value(self, name: str, value: str) -> list:
        """检测单个值中匹配的密钥模式"""
        matches = []
        for category, patterns in SECRET_PATTERNS.items():
            for pattern in patterns:
                try:
                    found = re.findall(pattern, value)
                    if found:
                        matches.append((category, pattern, found[:3]))
                except re.error:
                    continue
        return matches

    def _mask(self, value: str, keep_front: int = 4, keep_back: int = 4) -> str:
        """隐藏密钥中间部分"""
        if len(value) <= keep_front + keep_back + 6:
            return value[:keep_front] + "..." + value[-keep_back:]

        # 如果是key=value格式
        if "=" in value:
            k, v = value.split("=", 1)
            return f"{k}={self._mask(v, keep_front, keep_back)}"

        return value[:keep_front] + "****" + value[-keep_back:]

    def report_text(self) -> str:
        """生成文本报告"""
        if not self.findings:
            return "✅ 未发现敏感环境变量泄露"

        lines = [
            "⚠️  发现 {} 个敏感环境变量\n".format(len(self.findings)),
            f"{'变量名':<40} {'值预览':<30} {'严重度':<8} {'匹配模式数':<10}",
            "-" * 90,
        ]
        for f in self.findings:
            lines.append(f"{f['name']:<40} {f['value_preview']:<30} {f['severity']:<8} {len(f['matches']):<10}")
        lines.append("")
        lines.append("详细匹配:")
        for f in self.findings:
            lines.append(f"\n  {f['name']}:")
            for cat, pat, examples in f['matches']:
                lines.append(f"    - {cat}: {pat}")
        return "\n".join(lines)

    def report_json(self) -> str:
        return json.dumps(self.findings, indent=2, ensure_ascii=False)

    def sanitize_commands(self) -> list:
        """生成清理命令"""
        cmds = []
        for f in self.findings:
            cmds.append(f"unset {f['name']}")
            cmds.append(f"# 或: export {f['name']}='<redacted>'")
        return cmds


# ── CLI ─────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="环境变量密钥检测与清理工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例:\n  python scripts/env_sanitizer.py scan\n  python scripts/env_sanitizer.py scan --pid 1\n  python scripts/env_sanitizer.py sanitize\n  python scripts/env_sanitizer.py check --name GITHUB_TOKEN",
    )
    parser.add_argument("action", nargs="?", default="scan",
                        choices=["scan", "sanitize", "check", "list-whitelist",
                                 "add-whitelist", "remove-whitelist", "reset-whitelist"],
                        help="执行动作")
    parser.add_argument("--pid", type=int, help="目标进程PID（默认扫描当前环境）")
    parser.add_argument("--name", type=str, help="变量名（用于check/add-whitelist/remove-whitelist）")
    parser.add_argument("--json", action="store_true", help="JSON格式输出")
    parser.add_argument("--no-color", action="store_true", help="禁用颜色")

    args, extra = parser.parse_known_args()

    wlm = WhiteListManager()

    # ── 处理白名单管理的名称参数 ──
    # 对于add/remove/check，如果未提供--name，尝试从extra获取
    name = args.name
    if not name and extra:
        # 取第一个非选项参数作为名称
        for a in extra:
            if not a.startswith('-'):
                name = a
                break

    # ── 白名单管理 ──
    if args.action == "list-whitelist":
        print("当前白名单:")
        for n in sorted(wlm.get()):
            print(f"  {n}")
        return

    elif args.action == "add-whitelist":
        if not name:
            print("❌ 必须提供变量名: python scripts/env_sanitizer.py add-whitelist VAR_NAME")
            sys.exit(1)
        if wlm.add(name):
            print(f"✅ 已加入白名单: {name.upper()}")
        else:
            print(f"ℹ️  已存在白名单中: {name.upper()}")
        return

    elif args.action == "remove-whitelist":
        if not name:
            print("❌ 必须提供变量名: python scripts/env_sanitizer.py remove-whitelist VAR_NAME")
            sys.exit(1)
        if wlm.remove(name):
            print(f"✅ 已从白名单移除: {name.upper()}")
        else:
            print(f"❌ 不在白名单中: {name.upper()}")
        return

    elif args.action == "reset-whitelist":
        wlm.reset()
        print("✅ 白名单已重置为默认")
        return

    # ── 扫描 ──
    scanner = EnvScanner(whitelist=wlm.get())

    if args.pid:
        findings = scanner.scan_process(args.pid)
        label = f"进程 PID={args.pid}"
    else:
        findings = scanner.scan_environ()
        label = "当前环境变量"

    if args.json:
        print(scanner.report_json())
        return

    print(f"🔍 扫描: {label}")
    print(scanner.report_text())

    # ── sanitize ──
    if args.action == "sanitize" and findings:
        print("\n" + "=" * 60)
        print("🧹 建议清理命令:")
        for cmd in scanner.sanitize_commands():
            print(f"  {cmd}")
        print()
        print("💡 白名单管理:")
        print(f"  添加白名单: python scripts/env_sanitizer.py add-whitelist VAR_NAME")
        print(f"  查看白名单: python scripts/env_sanitizer.py list-whitelist")


if __name__ == "__main__":
    main()
