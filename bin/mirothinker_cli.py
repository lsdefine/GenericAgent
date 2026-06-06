#!/usr/bin/env python3
"""
MiroThinker CLI — 深度研究推理引擎

灵感来自 MiroThinker (dr.miromind.ai) 研究方法论：
分步推理 → 假设生成 → 自我质疑 → 结论综合

用法:
  python3 bin/mirothinker_cli.py "你的研究问题"
  python3 bin/mirothinker_cli.py "问题" --mode deep --json
  python3 bin/mirothinker_cli.py "问题" --strategy first-principles

参数:
  支持 --mode (quick|balanced|deep) 控制推理深度
  支持 --strategy (first-principles|analogy|deconstruction|multi-perspective)
  支持 --json 输出JSON格式
  支持 --out FILE 输出到文件
"""

import argparse
import json
import sys
import textwrap
import time
from datetime import datetime
from typing import List, Dict, Any, Optional


# ============================================================
# 推理引擎核心
# ============================================================

class MiroThinker:
    """MiroThinker 推理引擎"""

    # 思考策略
    STRATEGIES = {
        "first-principles": {
            "name": "第一性原理",
            "desc": "拆解到最基本的事实/原理，再重新构建",
            "prompt": "请从最基础的原理出发，识别哪些假设是确定的，哪些是需要验证的。"
        },
        "analogy": {
            "name": "类比推理",
            "desc": "将问题类比到已知领域，通过类比寻找洞见",
            "prompt": "请寻找类似问题或领域的解决方案，进行类比分析。"
        },
        "deconstruction": {
            "name": "解构分析",
            "desc": "将复杂问题拆解为独立子问题",
            "prompt": "请将问题拆解为最小可分析单元，逐一审查。"
        },
        "multi-perspective": {
            "name": "多视角",
            "desc": "从多个立场/学科/利益方角度审视",
            "prompt": "请从至少3个不同视角分析这个问题。"
        }
    }

    # 深度模型
    MODES = {
        "quick": {
            "name": "快速",
            "hypotheses": 2,
            "questions_per": 1,
            "detail_level": "low"
        },
        "balanced": {
            "name": "均衡",
            "hypotheses": 3,
            "questions_per": 2,
            "detail_level": "medium"
        },
        "deep": {
            "name": "深度",
            "hypotheses": 4,
            "questions_per": 3,
            "detail_level": "high"
        }
    }

    def __init__(self, question: str, mode: str = "balanced",
                 strategy: str = "first-principles", hermes_path: str = "hermes"):
        self.question = question.strip()
        self.mode = self.MODES.get(mode, self.MODES["balanced"])
        self.strategy = self.STRATEGIES.get(strategy, self.STRATEGIES["first-principles"])
        self.hermes_path = hermes_path
        self.result = {
            "metadata": {
                "question": self.question,
                "mode": mode,
                "strategy": strategy,
                "timestamp": datetime.now().isoformat()
            },
            "stages": [],
            "synthesis": ""
        }
        self._start_time = time.time()

    def _elapsed(self) -> float:
        return time.time() - self._start_time

    def _call_hermes(self, prompt: str, timeout: int = 120) -> str:
        """调用Hermes CLI进行推理"""
        import subprocess
        try:
            cmd = [self.hermes_path, "chat", "-q", prompt, "-Q"]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            output = r.stdout
            # 提取响应内容
            lines = output.split('\n')
            result = []
            in_response = False
            for line in lines:
                if '╰' in line and '─' in line:
                    in_response = True
                    continue
                if in_response:
                    if line.startswith('Resume this session') or line.startswith('Session:'):
                        break
                    result.append(line)
            return '\n'.join(result).strip()
        except subprocess.TimeoutExpired:
            return f"[TIMEOUT: {timeout}s] Hermes响应超时"
        except FileNotFoundError:
            return "[Hermes CLI not found] 请确保hermes命令可用"
        except Exception as e:
            return f"[Error: {e}]"

    def _create_prompt(self, stage: str, context: Dict[str, Any] = None) -> str:
        """创建各阶段的提示词"""
        if stage == "decompose":
            return textwrap.dedent(f"""\
            请对以下问题进行分步推理，拆解为关键子问题。
            
            问题: {self.question}
            
            分析策略: {self.strategy['name']} — {self.strategy['desc']}
            分析深度: {self.mode['detail_level']}
            
            请按以下结构输出:
            1. 问题本质: 这个问题的核心是什么？
            2. 关键维度: 列出需要分析的3-5个维度
            3. 子问题: 拆解为可独立分析的子问题
            4. 已知与未知: 明确已知事实和未知领域
            
            输出格式: 使用Markdown标题组织。""")
        
        elif stage == "hypotheses":
            return textwrap.dedent(f"""\
            基于以下分解，生成{self.mode['hypotheses']}个可验证的假设。
            每个假设需要：清晰的断言 + 可验证性评估 + 初步证据。
            
            研究问题: {self.question}
            分解: {context.get('decompose', '')[:500]}
            
            请生成{self.mode['hypotheses']}个不同方向的假设:
            - 假设1: [断言] | 可信度: [高/中/低] | 验证方法: [...]
            - 假设2: ...
            
            确保假设之间互不重叠，覆盖不同解释可能性。""")
        
        elif stage == "questioning":
            hypotheses = context.get('hypotheses', '')[:800]
            return textwrap.dedent(f"""\
            请对以下每个假设进行严格自我质疑，找出漏洞和盲点。
            每个假设至少提出{self.mode['questions_per']}个质疑。
            
            研究问题: {self.question}
            假设: {hypotheses}
            
            对每个假设:
            - 质疑1: [质疑内容] | 严重程度: [致命/重要/轻微]
            - 质疑2: ...
            - 抗辩: [可能的反论证]
            
            要无情！找出每个假设的致命弱点。""")
        
        elif stage == "synthesis":
            return textwrap.dedent(f"""\
            综合以上分析，给出最终结论。
            
            研究问题: {self.question}
            
            分解: {context.get('decompose', '')[:300]}
            假设: {context.get('hypotheses', '')[:500]}
            质疑: {context.get('questioning', '')[:500]}
            
            请输出:
            ## 综合分析
            [权衡各假设，指出最强解释]
            
            ## 结论
            [明确的结论陈述]
            
            ## 不确定性
            [仍存在的风险和盲点]
            
            ## 下一步建议
            [验证/行动建议]""")
        
        return ""

    def decompose(self) -> str:
        """阶段1: 分步推理"""
        prompt = self._create_prompt("decompose")
        print(f"  📐 分步推理中... ", end="", flush=True)
        result = self._call_hermes(prompt)
        print(f"({len(result)} chars)")
        self.result["stages"].append({
            "stage": "decompose",
            "name": "分步推理",
            "output": result,
            "elapsed_s": round(self._elapsed(), 2)
        })
        return result

    def hypothesize(self, context: Dict[str, Any]) -> str:
        """阶段2: 假设生成"""
        prompt = self._create_prompt("hypotheses", context)
        count = self.mode['hypotheses']
        print(f"  🧪 生成{count}个假设... ", end="", flush=True)
        result = self._call_hermes(prompt)
        print(f"({len(result)} chars)")
        self.result["stages"].append({
            "stage": "hypotheses",
            "name": "假设生成",
            "output": result,
            "elapsed_s": round(self._elapsed(), 2)
        })
        return result

    def question(self, context: Dict[str, Any]) -> str:
        """阶段3: 自我质疑"""
        prompt = self._create_prompt("questioning", context)
        print(f"  🔍 自我质疑中... ", end="", flush=True)
        result = self._call_hermes(prompt)
        print(f"({len(result)} chars)")
        self.result["stages"].append({
            "stage": "questioning",
            "name": "自我质疑",
            "output": result,
            "elapsed_s": round(self._elapsed(), 2)
        })
        return result

    def synthesize(self, context: Dict[str, Any]) -> str:
        """阶段4: 结论综合"""
        prompt = self._create_prompt("synthesis", context)
        print(f"  🎯 综合结论中... ", end="", flush=True)
        result = self._call_hermes(prompt, timeout=180)
        print(f"({len(result)} chars)")
        self.result["synthesis"] = result
        self.result["stages"].append({
            "stage": "synthesis",
            "name": "结论综合",
            "output": result,
            "elapsed_s": round(self._elapsed(), 2)
        })
        return result

    def run(self) -> Dict[str, Any]:
        """执行完整推理流程"""
        total_stages = 4
        print(f"\n{'='*60}")
        print(f"🧠 MiroThinker 深度推理")
        print(f"{'='*60}")
        print(f"📝 问题: {self.question}")
        print(f"⚙️  模式: {self.mode['name']} | 策略: {self.strategy['name']}")
        print(f"{'='*60}\n")

        # 阶段1: 分解
        print(f"[1/{total_stages}] 分步推理")
        d = self.decompose()

        # 阶段2: 假设
        print(f"\n[2/{total_stages}] 假设生成")
        h = self.hypothesize({"decompose": d})

        # 阶段3: 质疑
        print(f"\n[3/{total_stages}] 自我质疑")
        q = self.question({"decompose": d, "hypotheses": h})

        # 阶段4: 综合
        print(f"\n[4/{total_stages}] 结论综合")
        s = self.synthesize({"decompose": d, "hypotheses": h, "questioning": q})

        self.result["metadata"]["total_elapsed_s"] = round(self._elapsed(), 2)
        
        print(f"\n{'='*60}")
        print(f"✅ 推理完成 ({self.result['metadata']['total_elapsed_s']:.1f}s)")
        print(f"{'='*60}\n")

        return self.result

    def to_markdown(self, result: Dict[str, Any] = None) -> str:
        """将结果转为Markdown报告"""
        if result is None:
            result = self.result
        
        lines = []
        meta = result["metadata"]
        
        lines.append(f"# MiroThinker 推理报告")
        lines.append(f"")
        lines.append(f"**问题**: {meta['question']}")
        lines.append(f"**模式**: {meta['mode']} | **策略**: {meta['strategy']}")
        lines.append(f"**耗时**: {meta.get('total_elapsed_s', '—')}s")
        lines.append(f"**时间**: {meta['timestamp']}")
        lines.append(f"")
        lines.append(f"---")
        lines.append(f"")
        
        for stage in result["stages"]:
            lines.append(f"## {stage['stage']}: {stage['name']}")
            lines.append(f"")
            lines.append(f"*耗时: {stage['elapsed_s']}s*")
            lines.append(f"")
            lines.append(stage["output"])
            lines.append(f"")
            lines.append(f"---")
            lines.append(f"")
        
        if result.get("synthesis"):
            lines.append(f"# 🎯 综合结论")
            lines.append(f"")
            lines.append(result["synthesis"])
            lines.append(f"")
        
        return "\n".join(lines)


# ============================================================
# CLI
# ============================================================

def print_stage_summary(result: Dict[str, Any]):
    """打印阶段摘要"""
    meta = result["metadata"]
    stages = result["stages"]
    
    print(f"\n{'='*60}")
    print(f"📋 推理摘要")
    print(f"{'='*60}")
    print(f"  问题: {meta['question']}")
    print(f"  模式: {meta['mode']} | 策略: {meta['strategy']}")
    print(f"  总耗时: {meta.get('total_elapsed_s', '—')}s")
    print(f"")
    for s in stages:
        icon = {"decompose": "📐", "hypotheses": "🧪", "questioning": "🔍", "synthesis": "🎯"}.get(s["stage"], "•")
        print(f"  {icon} {s['name']:　<6} ({s['elapsed_s']:.1f}s, {len(s['output'])} chars)")
    
    if result.get("synthesis"):
        synthesis_preview = result["synthesis"][:200].replace('\n', ' ')
        print(f"\n  🎯 结论预览: {synthesis_preview}...")

def main():
    parser = argparse.ArgumentParser(
        description="🧠 MiroThinker CLI — 深度研究推理引擎",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            使用示例:
              python3 bin/mirothinker_cli.py "为什么Transformer比RNN更有效?"
              python3 bin/mirothinker_cli.py "分析内存泄漏原因" --mode deep
              python3 bin/mirothinker_cli.py "最佳实践" --strategy analogy --json
              python3 bin/mirothinker_cli.py "复杂问题" --out report.md
        """)
    )
    
    parser.add_argument("question", nargs="*", help="研究问题")
    parser.add_argument("--mode", choices=["quick", "balanced", "deep"],
                       default="balanced", help="推理深度 (默认: balanced)")
    parser.add_argument("--strategy", 
                       choices=list(MiroThinker.STRATEGIES.keys()),
                       default="first-principles",
                       help="推理策略 (默认: first-principles)")
    parser.add_argument("--json", action="store_true",
                       help="输出JSON格式到stdout")
    parser.add_argument("--out", type=str, default="",
                       help="输出报告到文件")
    parser.add_argument("--hermes", type=str, default="hermes",
                       help="Hermes CLI路径 (默认: hermes)")
    parser.add_argument("--list-strategies", action="store_true",
                       help="列出可用推理策略")
    
    args = parser.parse_args()
    
    # 列出策略
    if args.list_strategies:
        print("📋 可用推理策略:\n")
        for key, val in MiroThinker.STRATEGIES.items():
            print(f"  {key:<24} {val['name']}")
            print(f"  {'':24} {val['desc']}")
            print()
        return
    
    # 获取问题
    if not args.question:
        parser.print_help()
        sys.exit(1)
    
    question = " ".join(args.question)
    
    # 执行推理
    thinker = MiroThinker(question, mode=args.mode, 
                         strategy=args.strategy,
                         hermes_path=args.hermes)
    result = thinker.run()
    
    # 输出
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        markdown = thinker.to_markdown(result)
        print(markdown)
        print_stage_summary(result)
    
    # 保存到文件
    if args.out:
        markdown = thinker.to_markdown(result)
        with open(args.out, 'w', encoding='utf-8') as f:
            f.write(markdown)
        print(f"\n💾 报告已保存: {args.out}")


if __name__ == "__main__":
    main()
