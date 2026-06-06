#!/usr/bin/env python3
"""
brainstormer.py — 头脑风暴实战工具 💡

基于 brainstorming_sop.md 将模糊方向转化为结构化候选方案。

用法:
  python brainstormer.py article "Hermes 高阶技巧"
  python brainstormer.py architecture "通知系统设计"
  python brainstormer.py feature "CLI管理工具"
  python brainstormer.py debug "系统响应变慢"
  python brainstormer.py open "做个开源项目"

依赖:
  pip install requests pyyaml

输出: 结构化 Markdown + JSON 两种格式
"""

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

# ========== 场景定义 ==========

SCENARIOS = {
    "article": {
        "name": "文章写作",
        "count_range": (5, 10),
        "key_fields": ["target_reader", "length", "difficulty"],
        "dimensions": ["入门教程", "进阶技巧", "最佳实践", "踩坑实录", "原理剖析", "对比分析"],
        "prompt_template": """你是一位资深技术写作编辑。针对主题「{topic}」，请生成{count}个有实质差异的文章选题。

要求：
1. 每个选题必须有独特角度，覆盖入门→进阶→专家不同层次
2. 不要换皮（不能是"技巧一"和"技巧二"的区别）
3. 每个选题格式：
   - 标题：吸引人的标题
   - 一句话：核心卖点
   - 目标读者：入门/进阶/专家
   - 篇幅：短(1500-2500)/中(2500-4000)/长(4000+)
   - 难度：★~★★★
   - 独特角度：这个选题和其他有何不同

请以 JSON 数组格式输出，每个元素包含 title, one_liner, target_reader, length, difficulty, unique_angle 字段。""",
    },
    "architecture": {
        "name": "架构设计",
        "count_range": (3, 5),
        "key_fields": ["complexity", "timeline", "pros", "cons"],
        "dimensions": ["简单 vs 复杂", "单体 vs 分布式", "推 vs 拉", "同步 vs 异步", "中心化 vs 去中心化"],
        "prompt_template": """你是一位系统架构师。针对「{topic}」，请给出{count}种有实质差异的架构方案。

要求：
1. 每种方案必须基于不同的技术路径（如选型完全不同）
2. 不能是同一种思路的微调
3. 每种方案格式：
   - 方案名：简短有力的名称
   - 一句话：核心思路
   - 复杂度：低/中/高
   - 实施周期：天/周/月
   - 优势：列出2-3个
   - 劣势：列出1-2个
   - 适用场景：最适合什么场景

请以 JSON 数组格式输出。""",
    },
    "feature": {
        "name": "功能规划",
        "count_range": (3, 6),
        "key_fields": ["benefit", "effort", "priority"],
        "dimensions": ["用户需求", "技术债", "扩展性", "性能", "安全"],
        "prompt_template": """你是一位产品经理。针对「{topic}」，请列出{count}个可做的新功能方向。

要求：
1. 每个方向必须有明确价值主张
2. 覆盖不同维度（不能全是性能优化）
3. 每个功能格式：
   - 名称：功能名称
   - 一句话：解决什么问题
   - 收益：高/中/低
   - 工作量：小/中/大（人天）
   - 优先级：P0/P1/P2
   - 说明：为什么做这个

请以 JSON 数组格式输出。""",
    },
    "debug": {
        "name": "问题排查",
        "count_range": (3, 5),
        "key_fields": ["probability", "verification_cost"],
        "dimensions": ["慢在哪里", "可能瓶颈", "数据流追踪", "配置问题", "资源竞争"],
        "prompt_template": """你是一位运维专家。针对问题「{topic}」，请列出{count}个可能的根因路径。

要求：
1. 按可能性从高到低排序
2. 每个路径是可验证的（有明确的排查步骤）
3. 每个根因路径格式：
   - 路径名：简短的根因描述
   - 可能性：高/中/低
   - 验证成本：低/中/高
   - 验证步骤：具体的检查方法（1-3步）
   - 修复建议：如果确认是这个原因怎么修

请以 JSON 数组格式输出。""",
    },
    "open": {
        "name": "开放探索",
        "count_range": (5, 8),
        "key_fields": ["type", "feasibility", "value_proposition"],
        "dimensions": ["项目类型", "技术栈", "目标用户", "盈利模式"],
        "prompt_template": """你是一位创业顾问。针对方向「{topic}」，请生成{count}个具体的项目想法。

要求：
1. 每个想法必须独特，不能是已有项目的克隆
2. 覆盖不同类型（工具/平台/SaaS/开源等）
3. 每个想法格式：
   - 项目名：简短有力
   - 一句话：做什么
   - 类型：工具/平台/SaaS/开源/其他
   - 可行性：高/中/低
   - 价值主张：为什么有人需要
   - 初始步骤：MVP怎么做（1-3步）

请以 JSON 数组格式输出。""",
    },
}


# ========== 数据类 ==========

@dataclass
class Candidate:
    """单个候选"""
    title: str
    one_liner: str
    fields: dict = field(default_factory=dict)


@dataclass
class BrainstormSession:
    """一次头脑风暴的结果"""
    scenario: str
    topic: str
    candidates: list[Candidate] = field(default_factory=list)
    raw_response: str = ""
    model_used: str = ""
    duration_ms: int = 0

    def to_markdown(self) -> str:
        """按 brainstorming_sop 格式输出 Markdown"""
        scenario_info = SCENARIOS.get(self.scenario, {})
        scenario_name = scenario_info.get("name", self.scenario.capitalize())

        lines = []
        lines.append(f"## 💡 头脑风暴：{self.topic}")
        lines.append("")
        lines.append(f"基于「{self.topic}」，使用 `{self.model_used}` 生成（{self.duration_ms}ms）：")
        lines.append("")

        for i, cand in enumerate(self.candidates, 1):
            lines.append(f"### 候选 {i}：{cand.title}")
            lines.append("")
            lines.append(f"**{cand.one_liner}**")
            lines.append("")
            for key, val in cand.fields.items():
                if val:  # skip empty fields
                    lines.append(f"- **{key}**：{val}")
            lines.append("")

        lines.append("---")
        lines.append("")
        lines.append("👇 您可以：")
        lines.append("- **选数字** → 直接展开这个方向")
        lines.append("- **组合** → A+B 混搭")
        lines.append("- **觉得类型不对** → 换一批方向")
        lines.append("- **新增** → 提新想法继续 brainstorm")
        lines.append("")

        return "\n".join(lines)

    def to_json(self, indent: bool = False) -> str:
        """JSON 输出"""
        data = {
            "scenario": self.scenario,
            "topic": self.topic,
            "model": self.model_used,
            "duration_ms": self.duration_ms,
            "candidates": [
                {"title": c.title, "one_liner": c.one_liner, **c.fields}
                for c in self.candidates
            ],
        }
        return json.dumps(data, ensure_ascii=False, indent=2 if indent else None)


# ========== LLM 客户端 ==========

class LLMClient:
    """调用本地 OpenLLM API 或任意 OpenAI 兼容端点"""

    def __init__(self, base_url: str = None, model: str = None, api_key: str = None):
        self.base_url = (base_url or os.environ.get("BRAINSTORMER_API_URL", "http://localhost:11343/v1")).rstrip("/")
        self.model = model or os.environ.get("BRAINSTORMER_MODEL", "deepseek/deepseek-v4-flash")
        self.api_key = api_key or os.environ.get("BRAINSTORMER_API_KEY", "not-needed")

    def chat(self, messages: list[dict], max_tokens: int = 4096, temperature: float = 0.7) -> dict:
        """调用聊天补全 API"""
        import requests

        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        resp = requests.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            headers=headers,
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()


# ========== 核心逻辑 ==========

class Brainstormer:
    """头脑风暴引擎"""

    def __init__(self, llm_client: Optional[LLMClient] = None, dry_run: bool = False):
        self.llm = llm_client or LLMClient()
        self.dry_run = dry_run

    def brainstorm(self, scenario: str, topic: str, count: Optional[int] = None) -> BrainstormSession:
        """
        执行一次头脑风暴。

        参数:
            scenario: 场景标识 (article/architecture/feature/debug/open)
            topic: 主题/方向
            count: 候选数量（不指定则用场景默认）

        返回:
            BrainstormSession 对象
        """
        if scenario not in SCENARIOS:
            valid = ", ".join(SCENARIOS.keys())
            raise ValueError(f"不支持场景 '{scenario}'，可选: {valid}")

        scenario_info = SCENARIOS[scenario]
        min_c, max_c = scenario_info["count_range"]
        count = max(min_c, min(max_c, count or max_c))

        prompt = scenario_info["prompt_template"].format(topic=topic, count=count)

        session = BrainstormSession(scenario=scenario, topic=topic)

        if self.dry_run:
            session.candidates = [
                Candidate(
                    title=f"示例候选 {i+1}",
                    one_liner=f"这是关于「{topic}」的一个想法（dry run）",
                    fields={"说明": "dry_run 模式，未实际调用 LLM"},
                )
                for i in range(count)
            ]
            session.model_used = "dry_run"
            return session

        # Phase 1: System prompt
        system_msg = {
            "role": "system",
            "content": (
                "你是一个头脑风暴助手。你的任务是生成有实质差异的候选方案。\n"
                "每个候选必须与其他候选有本质区别，不能是微调/换皮。\n"
                "请始终以 JSON 数组格式输出，不要包含其他文本。"
            ),
        }
        user_msg = {"role": "user", "content": prompt}

        start = time.time()
        try:
            raw = self.llm.chat([system_msg, user_msg])
            duration_ms = int((time.time() - start) * 1000)
            session.duration_ms = duration_ms

            content = raw.get("choices", [{}])[0].get("message", {}).get("content", "")
            session.raw_response = content
            session.model_used = raw.get("model", self.llm.model)

            # Parse JSON from response
            candidates = self._parse_candidates(content, scenario, count)
            session.candidates = candidates

        except Exception as e:
            session.raw_response = f"ERROR: {e}"
            session.candidates = [
                Candidate(
                    title="请求失败",
                    one_liner=str(e),
                    fields={"状态": "LLM 调用出错，请检查 OpenLLM 服务是否正常运行"},
                )
            ]

        return session

    def _parse_candidates(self, content: str, scenario: str, expected_count: int) -> list[Candidate]:
        """从 LLM 回复中解析候选列表"""
        # Try to parse JSON directly
        json_data = None

        # Strip code fences if present
        cleaned = content.strip()
        if cleaned.startswith("```"):
            # Remove markdown code blocks
            lines = cleaned.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()

        try:
            json_data = json.loads(cleaned)
        except json.JSONDecodeError:
            # Try to find JSON array in the text
            import re

            match = re.search(r"\[.*\]", cleaned, re.DOTALL)
            if match:
                try:
                    json_data = json.loads(match.group())
                except json.JSONDecodeError:
                    pass

        if not json_data:
            return [Candidate(title="解析失败", one_liner="LLM 返回格式不对", fields={"原始响应": content[:500]})]

        candidates = []
        if isinstance(json_data, list):
            for item in json_data[:expected_count]:
                if isinstance(item, dict):
                    title = item.get("title") or item.get("name") or item.get("路径名", "未命名")
                    one_liner = item.get("one_liner") or item.get("一句话") or item.get("核心思路", "")
                    fields = {k: v for k, v in item.items() if k not in ("title", "name", "one_liner", "一句话", "核心思路")}
                    candidates.append(Candidate(title=title, one_liner=one_liner, fields=fields))

        # Fallback: if parsing gave nothing, return raw
        if not candidates:
            candidates = [Candidate(title="解析结果为空", one_liner="检查 LLM 原始响应", fields={"raw": content[:300]})]

        return candidates


# ========== CLI ==========

def main():
    parser = argparse.ArgumentParser(
        description="💡 头脑风暴工具 — 将模糊方向转化为结构化方案",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例:
  brainstormer.py article "Hermes 高阶技巧"
  brainstormer.py architecture "通知系统" -c 3
  brainstormer.py feature "CLI工具" --json
  brainstormer.py debug "系统响应变慢" --model "deepseek/deepseek-v4-pro"
  brainstormer.py open "AI运维工具" --dry-run
""",
    )

    parser.add_argument("scenario", choices=list(SCENARIOS.keys()) + ["list"],
                        help="头脑风暴场景（用 'list' 查看详情）")
    parser.add_argument("topic", nargs="?", default="",
                        help="主题/方向（scenario=list 时忽略）")
    parser.add_argument("-c", "--count", type=int, default=None,
                        help="候选数量（默认按场景）")
    parser.add_argument("--json", action="store_true",
                        help="JSON 格式输出")
    parser.add_argument("--indent", action="store_true",
                        help="JSON 输出自动缩进")
    parser.add_argument("--model", default=None,
                        help="指定模型（默认 router/auto）")
    parser.add_argument("--api-url", default=None,
                        help="API 地址（默认 http://localhost:11343/v1）")
    parser.add_argument("--dry-run", action="store_true",
                        help="干跑模式，不实际调用 LLM")
    parser.add_argument("--raw", action="store_true",
                        help="同时输出 LLM 原始响应")

    args = parser.parse_args()

    if args.scenario == "list":
        print("可用场景:")
        for key, info in SCENARIOS.items():
            print(f"\n  {key} ({info['name']})")
            print(f"    候选数: {info['count_range'][0]}~{info['count_range'][1]}")
            print(f"    维度: {', '.join(info['dimensions'][:3])}...")
        return

    if not args.topic:
        print("❌ 错误：请指定主题", file=sys.stderr)
        parser.print_help()
        sys.exit(1)

    client = LLMClient(base_url=args.api_url, model=args.model)
    brainstormer = Brainstormer(llm_client=client, dry_run=args.dry_run)

    print(f"🧠 头脑风暴中… ({args.scenario}: {args.topic})", file=sys.stderr)
    result = brainstormer.brainstorm(args.scenario, args.topic, count=args.count)

    if args.json:
        print(result.to_json(indent=args.indent))
    else:
        print(result.to_markdown())

    if args.raw and result.raw_response:
        print("\n--- 原始响应 ---\n", file=sys.stderr)
        print(result.raw_response, file=sys.stderr)


if __name__ == "__main__":
    main()
