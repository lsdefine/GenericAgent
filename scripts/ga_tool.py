#!/usr/bin/env python3
"""
ga_tool.py — GA 统一脚本入口 CLI 🧰

按功能域分组管理所有脚本，支持 list/run/help/completion。

用法:
  python3 scripts/ga_tool.py list [category]    # 列出脚本（可按筛选）
  python3 scripts/ga_tool.py run <script> [args...]  # 运行脚本
  python3 scripts/ga_tool.py help <script>      # 查看脚本说明
  python3 scripts/ga_tool.py completion         # 输出 bash completion 脚本

示例:
  python3 scripts/ga_tool.py list
  python3 scripts/ga_tool.py list 系统
  python3 scripts/ga_tool.py run health_server --port 8081
  python3 scripts/ga_tool.py run svc list
"""

import os, sys, subprocess, json, re, textwrap
from pathlib import Path

GA_HOME = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = Path(GA_HOME) / "scripts"

# ── 功能域分类配置 ──
# 关键词 → 域映射（按文件名判断）
KEYWORD_MAP = {
    "系统运维":   ["auto_repair", "cleanup_disk", "system_snapshot", "system_utils",
                  "health_collector", "health_dashboard", "health_server", "svc",
                  "drift_detector", "preflight_check", "pre_delivery", "snapshot"],
    "告警通知":   ["agentmail", "feishu_bridge", "alert_manager", "notify"],
    "服务管理":   ["hermes", "svc", "manage_services"],
    "Vision/AI": ["vision", "describe_screenshot", "browser.vision", "ocr"],
    "浏览器交互": ["browser_click", "browser_interact"],
    "对抗训练":   ["adversarial"],
    "SOP/智能":   ["sop_", "brainstormer", "discriminator", "self_discriminator",
                  "solver_team", "supervisor_tool", "memory_tool"],
    "开发工具":   ["dep_scanner", "env_sanitizer", "model_router",
                  "prompt_optimizer", "api_tester", "arena_benchmark",
                  "ga_status_reporter", "whiteboard_protocol", "benchmarker",
                  "archive_l4"],
    "冲浪/外部":  ["ai_cli", "browser", "hermes_tool", "sop_recommender",
                  "sop_graph", "sop_script_audit", "sop_dep_analyzer"],
}

def categorize_script(name: str) -> str:
    """根据文件名返回所属域"""
    name_lower = name.lower().replace(".py", "").replace(".sh", "")
    for domain, keywords in KEYWORD_MAP.items():
        for kw in keywords:
            if kw in name_lower:
                return domain
    return "其他"

def scan_scripts() -> dict:
    """扫描 scripts/ 目录，按域分组返回"""
    categories = {}
    for f in sorted(SCRIPTS_DIR.iterdir()):
        if f.suffix not in (".py", ".sh") or f.name.startswith("_"):
            continue
        domain = categorize_script(f.name)
        desc = _get_description(f)
        categories.setdefault(domain, []).append((f.name, desc))
    return categories

def _get_description(path: Path) -> str:
    """从脚本文件头提取一行描述"""
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line.startswith('"""') and len(line) > 3:
                    return line.replace('"""', '').strip()
                if line.startswith('# ') and '!' not in line:
                    return line[2:].strip()
    except:
        pass
    return ""

def cmd_list(args: list):
    """列出脚本"""
    categories = scan_scripts()
    filter_domain = " ".join(args) if args else None

    for domain in sorted(categories.keys()):
        if filter_domain and filter_domain not in domain:
            continue
        items = categories[domain]
        print(f"\n{'='*50}")
        print(f"  {domain} ({len(items)}项)")
        print(f"{'='*50}")
        for name, desc in items:
            desc_short = desc[:60] if desc else ""
            print(f"  📄 {name:<40s} {desc_short}")

    if filter_domain:
        total = sum(len(v) for k, v in categories.items() if filter_domain in k)
        print(f"\n匹配 {total} 个脚本")
    else:
        total = sum(len(v) for v in categories.values())
        print(f"\n总计 {total} 个脚本")

def cmd_run(args: list):
    """运行指定脚本"""
    if not args:
        print("❌ 请指定脚本名，如: ga-tool run health_server --port 8081")
        sys.exit(1)

    script_name = args[0]
    script_args = args[1:]

    # 尝试匹配完整路径
    candidates = []
    for f in SCRIPTS_DIR.iterdir():
        if f.name == script_name or f.name == script_name + ".py" or f.name == script_name + ".sh":
            candidates.append(f)
        elif f.name.startswith(script_name) and f.suffix in (".py", ".sh"):
            candidates.append(f)

    if not candidates:
        print(f"❌ 未找到脚本: {script_name}")
        print("   可用: python3 scripts/ga_tool.py list")
        sys.exit(1)

    # 优先精确匹配
    target = None
    for c in candidates:
        if c.name == script_name or c.name == f"{script_name}.py" or c.name == f"{script_name}.sh":
            target = c
            break
    if not target:
        target = candidates[0]

    # 执行
    cmd = [sys.executable, str(target)] if target.suffix == ".py" else ["bash", str(target)]
    cmd += script_args

    print(f"🚀 执行: {' '.join(cmd)}")
    sys.stdout.flush()
    result = subprocess.run(cmd, cwd=GA_HOME)
    sys.exit(result.returncode)

def cmd_help(args: list):
    """显示脚本帮助"""
    if not args:
        print("❌ 请指定脚本名: ga-tool help <script>")
        return

    script_name = args[0]
    for f in SCRIPTS_DIR.iterdir():
        if f.name.startswith(script_name) and f.suffix in (".py", ".sh") and not f.name.startswith("_"):
            print(f"📄 {f.name}")
            print("-" * 50)
            with open(f) as fh:
                content = fh.read()
            # 提取文档字符串
            if f.suffix == ".py":
                import ast
                try:
                    tree = ast.parse(content)
                    docstring = ast.get_docstring(tree)
                    if docstring:
                        print(docstring.strip())
                        return
                except:
                    pass
            # fallback: 打印前30行注释
            for i, line in enumerate(content.splitlines()[:30]):
                if line.startswith("#") or line.startswith('"""') or line.strip() == "":
                    print(line)
                else:
                    break
            return

    print(f"❌ 未找到: {script_name}")

def cmd_completion():
    """输出 bash completion 脚本"""
    # 获取所有脚本名（无后缀）
    scripts = []
    for f in sorted(SCRIPTS_DIR.iterdir()):
        if f.suffix in (".py", ".sh") and not f.name.startswith("_"):
            scripts.append(f.stem)  # 不含后缀

    completion_script = f"""# ga-tool bash completion
_ga_tool_completion() {{
    local cur=${{COMP_WORDS[COMP_CWORD]}}
    local prev=${{COMP_WORDS[COMP_CWORD-1]}}
    local opts="list run help completion"

    if [ $COMP_CWORD -eq 1 ]; then
        COMPREPLY=( $(compgen -W "$opts" -- "$cur") )
    elif [ $COMP_CWORD -ge 2 ]; then
        case "${{COMP_WORDS[1]}}" in
            list)
                local cats="系统运维 告警通知 服务管理 Vision/AI 浏览器交互 对抗训练 SOP/智能 开发工具 冲浪/外部 其他"
                COMPREPLY=( $(compgen -W "$cats" -- "$cur") )
                ;;
            run|help)
                local scripts="{' '.join(scripts)}"
                COMPREPLY=( $(compgen -W "$scripts" -- "$cur") )
                ;;
        esac
    fi
}}
complete -F _ga_tool_completion ga-tool
"""
    print(completion_script)

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    args = sys.argv[2:]

    if cmd == "list":
        cmd_list(args)
    elif cmd == "run":
        cmd_run(args)
    elif cmd == "help":
        cmd_help(args)
    elif cmd == "completion":
        cmd_completion()
    elif cmd in ("-h", "--help"):
        print(__doc__)
    else:
        print(f"❌ 未知命令: {cmd}")
        print("   可用: list, run, help, completion")
        sys.exit(1)

if __name__ == "__main__":
    main()
