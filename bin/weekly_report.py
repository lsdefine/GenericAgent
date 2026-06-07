#!/usr/bin/env python3
"""
Weekly Report Generator — 自动周报生成器

从 history.txt + TODO.txt 生成结构化周报：
- 总体统计（报告数/类型分布/完成率）
- 分类统计（产出/规划/验证/冲浪/环境/探索）
- 趋势分析（按天的活动分布）
- 待办追踪（TODO完成进度）
- 重点成就（高Impact条目）

用法:
  python3 bin/weekly_report.py                     # 输出Markdown周报
  python3 bin/weekly_report.py --json              # JSON输出
  python3 bin/weekly_report.py --days 7            # 最近7天
  python3 bin/weekly_report.py --serve             # 启动HTTP服务
  python3 bin/weekly_report.py --html              # 输出HTML
"""

import os
import sys
import re
import json
import argparse
import subprocess
from datetime import datetime, timedelta
from collections import Counter, defaultdict
from pathlib import Path

# ─── 路径 ───────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
HISTORY_FILE = ROOT / "temp" / "autonomous_reports" / "history.txt"
TODO_FILE = ROOT / "temp" / "TODO.txt"
REPORTS_DIR = ROOT / "temp" / "autonomous_reports"

# 类型分组
TYPE_GROUPS = {
    "产出": ["产出"],
    "规划": ["规划"],
    "验证": ["验证", "测试"],
    "冲浪": ["冲浪"],
    "环境": ["环境"],
    "探索": ["探索", "分析"],
    "实验": ["实验"],
}

TYPE_ICONS = {
    "产出": "🚀",
    "规划": "📋",
    "验证": "✅",
    "冲浪": "🌊",
    "环境": "🔧",
    "探索": "🔍",
    "实验": "🧪",
    "分析": "📊",
    "测试": "🧪",
    "其他": "📌",
}

def parse_history_line(line: str):
    """解析 history.txt 单行"""
    line = line.strip()
    if not line or line.startswith("#") or line.startswith("---"):
        return None
    # R63 | 2026-06-05 | 产出 | 浏览器交互闭环脚本
    m = re.match(r'^R(\d+)\s*\|\s*(\S+)\s*\|\s*(\S+)\s*\|\s*(.*)$', line)
    if m:
        num, date, rtype, title = m.groups()
        return {
            "num": int(num),
            "date": date,
            "type": rtype,
            "title": title.strip(),
            "impact": 0,  # 从内容推断
            "group": _map_group(rtype),
        }
    return None

def _map_group(rtype: str) -> str:
    for group, types in TYPE_GROUPS.items():
        if rtype in types:
            return group
    return "其他"

def parse_todo():
    """解析 TODO.txt 返回 (pending, done)"""
    if not TODO_FILE.exists():
        return [], []
    pending, done = [], []
    for line in TODO_FILE.read_text().splitlines():
        line = line.strip()
        if line.startswith("[ ]"):
            pending.append(line)
        elif line.startswith("[x]"):
            done.append(line)
    return pending, done

def get_trends(records, days=14):
    """按天统计活动"""
    daily = Counter()
    for r in records:
        daily[r["date"]] += 1
    # 填充日期范围
    today = datetime.now()
    result = []
    for i in range(days - 1, -1, -1):
        d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        result.append((d, daily.get(d, 0)))
    return result

def estimate_impact(title: str, rtype: str) -> int:
    """根据标题关键词估算影响力 0-5"""
    keywords_high = ["创建", "构建", "完整", "全链路", "生产化", "验收", "闭环"]
    keywords_med = ["修复", "增强", "集成", "部署", "分析", "测试"]
    keywords_low = ["阅读", "扫描", "探索", "规划"]
    
    score = 1
    for kw in keywords_high:
        if kw in title:
            score += 2
            break
    for kw in keywords_med:
        if kw in title:
            score += 1
            break
    if rtype in ("产出", "验证"):
        score += 1
    if "超时" in title or "修复" in title:
        score += 1
    return min(score, 5)

def build_report(days: int = 7, root: Path = ROOT):
    """构建周报数据"""
    if not HISTORY_FILE.exists():
        return {"error": f"history.txt not found at {HISTORY_FILE}"}
    
    lines = HISTORY_FILE.read_text().splitlines()
    all_records = []
    for line in lines:
        r = parse_history_line(line)
        if r:
            r["impact"] = estimate_impact(r["title"], r["type"])
            all_records.append(r)
    
    # 时间过滤
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    records = [r for r in all_records if r["date"] >= cutoff]
    
    # 统计
    total = len(records)
    by_group = Counter(r["group"] for r in records)
    by_type = Counter(r["type"] for r in records)
    by_date = Counter(r["date"] for r in records)
    
    top_impact = sorted(records, key=lambda x: x["impact"], reverse=True)[:10]
    
    pending, done = parse_todo()
    done_new = sum(1 for d in done if any(r["title"] in d for r in records))
    
    # 趋势
    trends = get_trends(records, days)
    
    return {
        "period": f"最近{days}天",
        "date_range": f"{cutoff} ~ {datetime.now().strftime('%Y-%m-%d')}",
        "total_reports": total,
        "total_all_time": len(all_records),
        "by_group": dict(by_group.most_common()),
        "by_type": dict(by_type.most_common()),
        "by_date": dict(by_date),
        "trends": trends,
        "top_impact": [
            {
                "num": r["num"],
                "date": r["date"],
                "type": r["type"],
                "title": r["title"],
                "impact": r["impact"],
                "group": r["group"],
            }
            for r in top_impact
        ],
        "todo_pending": len(pending),
        "todo_done": len(done),
        "todo_done_new": done_new,
        "avatar_line": _get_avatar_line(),
    }

def _get_avatar_line() -> str:
    """获取最新一条记录作为头像"""
    if not HISTORY_FILE.exists():
        return ""
    lines = HISTORY_FILE.read_text().splitlines()
    for line in reversed(lines):
        r = parse_history_line(line)
        if r:
            icon = TYPE_ICONS.get(r["group"], "📌")
            return f"{icon} `R{r['num']}` {r['title'][:60]}"
    return ""

def to_markdown(data: dict) -> str:
    """生成 Markdown 周报"""
    if "error" in data:
        return f"❌ {data['error']}"
    
    lines = []
    lines.append(f"# 📊 自主智能周报 v{datetime.now().strftime('%Y%m%d')}")
    lines.append(f"")
    lines.append(f"> **周期**: {data['date_range']}")
    lines.append(f"> **报告总数**: {data['total_reports']} / 累计 {data['total_all_time']}")
    lines.append(f"> **待办完成**: {data['todo_done_new']} / 总计 {data['todo_done']} ✅")
    lines.append(f"")
    
    # 最新动态
    lines.append(f"## 🆕 最新动态")
    lines.append(f"")
    lines.append(f"{_get_avatar_line()}")
    lines.append(f"")
    
    # 类型分布
    lines.append(f"## 📈 类型分布")
    lines.append(f"")
    lines.append(f"| 类别 | 数量 | 占比 |")
    lines.append(f"|------|:----:|:----:|")
    for group, count in data["by_group"].items():
        icon = TYPE_ICONS.get(group, "📌")
        pct = count / data["total_reports"] * 100 if data["total_reports"] > 0 else 0
        bar = "█" * int(pct / 10) + "░" * (10 - int(pct / 10))
        lines.append(f"| {icon} {group} | {count} | {pct:.1f}% {bar} |")
    lines.append(f"")
    
    # 趋势
    lines.append(f"## 📅 逐日趋势")
    lines.append(f"")
    max_count = max(c for _, c in data["trends"]) if data["trends"] else 1
    for date_str, count in data["trends"]:
        bar_len = int(count / max_count * 20) if max_count > 0 else 0
        bar = "█" * bar_len + "░" * (20 - bar_len)
        lines.append(f"  {date_str} {bar} {count}")
    lines.append(f"")
    
    # 重点成就
    lines.append(f"## 🏆 重点成就 Top 5")
    lines.append(f"")
    for i, r in enumerate(data["top_impact"][:5], 1):
        icon = TYPE_ICONS.get(r["group"], "📌")
        stars = "⭐" * r["impact"]
        lines.append(f"{i}. {icon} `R{r['num']}` {r['title'][:80]} {stars}")
    lines.append(f"")
    
    # 待办状态
    lines.append(f"## ✅ 待办追踪")
    lines.append(f"")
    lines.append(f"- 总待办: {data['todo_pending']} | 已完成: {data['todo_done']}")
    lines.append(f"- 本周期新增完成: {data['todo_done_new']}")
    lines.append(f"- 完成率: {data['todo_done'] / (data['todo_pending'] + data['todo_done']) * 100:.1f}%" if (data['todo_pending'] + data['todo_done']) > 0 else "- 完成率: N/A")
    lines.append(f"")
    
    # 详细记录
    lines.append(f"## 📋 本周期全记录")
    lines.append(f"")
    lines.append(f"| # | 日期 | 类型 | 摘要 |")
    lines.append(f"|---|:----:|:----:|------|")
    for r in reversed(data["top_impact"]):
        icon = TYPE_ICONS.get(r["group"], "📌")
        lines.append(f"| R{r['num']} | {r['date']} | {icon} {r['type']} | {r['title'][:60]} |")
    lines.append(f"")
    
    lines.append(f"---")
    lines.append(f"*Generated by weekly_report.py at {datetime.now().strftime('%Y-%m-%d %H:%M')}*")
    
    return "\n".join(lines)

def to_html(md: str) -> str:
    """简单的 Markdown → HTML 转换"""
    html = []
    html.append("<!DOCTYPE html><html><head><meta charset='utf-8'>")
    html.append("<style>")
    html.append("body{font-family:system-ui,-apple-system,sans-serif;max-width:800px;margin:0 auto;padding:20px;background:#fafafa}")
    html.append("h1{color:#1a1a2e;border-bottom:2px solid #e94560;padding-bottom:8px}")
    html.append("h2{color:#16213e;margin-top:24px}")
    html.append("table{border-collapse:collapse;width:100%}")
    html.append("th,td{border:1px solid #ddd;padding:8px;text-align:left}")
    html.append("th{background:#16213e;color:#fff}")
    html.append("tr:nth-child(even){background:#f5f5f5}")
    html.append(".bar{color:#0f3460}")
    html.append("</style></head><body>")
    
    in_table = False
    for line in md.splitlines():
        if line.startswith("# ") or line.startswith("## "):
            level = 1 if line.startswith("# ") else 2
            text = line.lstrip("# ").strip()
            html.append(f"<h{level}>{text}</h{level}>")
        elif line.startswith("|"):
            if not in_table:
                html.append("<table>")
                in_table = True
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if line.startswith("|---"):
                continue
            elif any("---" in c for c in cells):
                continue
            else:
                is_header = any(c.isupper() for c in cells)
                tag = "th" if is_header else "td"
                html.append(f"<tr>{''.join(f'<{tag}>{c}</{tag}>' for c in cells)}</tr>")
        elif line.strip() == "" and in_table:
            html.append("</table>")
            in_table = False
        elif line.startswith("---"):
            html.append("<hr>")
        elif line.startswith("> "):
            html.append(f"<blockquote>{line[2:]}</blockquote>")
        elif line.strip():
            # 处理bar行
            if "█" in line or "░" in line:
                html.append(f"<pre class='bar'>{line}</pre>")
            else:
                html.append(f"<p>{line}</p>")
    
    if in_table:
        html.append("</table>")
    
    html.append("</body></html>")
    return "\n".join(html)

def serve_html(port: int = 8888):
    """启动HTTP服务展示周报"""
    html_content = None
    
    from http.server import HTTPServer, BaseHTTPRequestHandler
    
    class ReportHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            if html_content is None:
                self.wfile.write(b"<h1>Generating report...</h1>")
            else:
                self.wfile.write(html_content.encode("utf-8"))
        
        def log_message(self, format, *args):
            pass
    
    data = build_report()
    md = to_markdown(data)
    html_content = to_html(md)
    
    server = HTTPServer(("0.0.0.0", port), ReportHandler)
    print(f"🌐 周报服务: http://localhost:{port}")
    print("Press Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


def main():
    parser = argparse.ArgumentParser(
        description="📊 自动化周报生成器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 bin/weekly_report.py                  # Markdown周报(最近7天)
  python3 bin/weekly_report.py --json           # JSON格式
  python3 bin/weekly_report.py --days 14        # 最近14天
  python3 bin/weekly_report.py --html > report.html
  python3 bin/weekly_report.py --serve          # HTTP服务(默认8888)
  python3 bin/weekly_report.py --output week.md # 保存到文件
        """
    )
    parser.add_argument("--json", action="store_true", help="JSON输出")
    parser.add_argument("--html", action="store_true", help="HTML输出")
    parser.add_argument("--days", type=int, default=7, help="统计天数")
    parser.add_argument("--serve", action="store_true", help="启动HTTP服务")
    parser.add_argument("--output", "-o", type=str, help="保存到文件")
    parser.add_argument("--port", type=int, default=8888, help="HTTP端口")
    
    args = parser.parse_args()
    
    if args.serve:
        serve_html(args.port)
        return
    
    data = build_report(days=args.days)
    
    if args.json:
        output = json.dumps(data, indent=2, ensure_ascii=False)
    elif args.html:
        md = to_markdown(data)
        output = to_html(md)
    else:
        output = to_markdown(data)
    
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"✅ 周报已保存: {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()
