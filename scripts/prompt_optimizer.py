#!/usr/bin/env python3
"""
prompt_optimizer.py — Prompt优化循环工具箱

基于prompt_optimization_loop_sop.md的5步循环:
①评分 → ②分析 → ③修复 → ④重评 → ⑤提交

用法:
  python prompt_optimizer.py init                    # 初始化跟踪项目
  python prompt_optimizer.py save <name> <file>       # 保存prompt版本
  python prompt_optimizer.py list                     # 列出所有版本
  python prompt_optimizer.py score <file>              # 评分(维度A/B/C/D)
  python prompt_optimizer.py ab <v1> <v2> [--input x] # A/B测试
  python prompt_optimizer.py diff <v1> <v2>            # 对比版本差异
  python prompt_optimizer.py history                   # 评分历史
  python prompt_optimizer.py stats                     # 质量统计

API:
  from prompt_optimizer import PromptOptimizer
  po = PromptOptimizer(work_dir="./prompt_lab")
  po.save_version("v1", content, name="my_prompt")
  result = po.score(content)
  ab_result = po.ab_test(content_a, content_b, test_input="...")
"""

import os, sys, json, time, hashlib, difflib, argparse, re
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Tuple

_CODE_ROOT = Path(__file__).resolve().parent

# ==================== 评分标准 ====================

QUALITY_DIMENSIONS = {
    "A": {"name": "结构完整性", "weight": 0.25, "items": {
        "A1": {"desc": "frontmatter存在(yaml头部)", "check": lambda s: bool(re.search(r'^---\s*\n', s))},
        "A2": {"desc": "tags数组存在", "check": lambda s: bool(re.search(r'tags\s*:', s))},
        "A3": {"desc": "角色身份段存在(你是谁/你的角色)", "check": lambda s: bool(re.search(r'(角色|你是谁|你的职责|身份)', s))},
        "A4": {"desc": "关键规则段存在", "check": lambda s: bool(re.search(r'(关键规则|规则|原则)', s))},
        "A5": {"desc": "边界段存在(✅/❌)", "check": lambda s: bool(re.search(r'(✅|❌|工作范围|限制)', s))},
    }},
    "B": {"name": "内容质量", "weight": 0.30, "items": {
        "B1": {"desc": "职责描述清晰", "check": lambda s: len(s) > 200},
        "B2": {"desc": "边界明确", "check": lambda s: bool(re.search(r'(不做|不|禁止|不要)', s))},
        "B3": {"desc": "上下文占位符存在", "check": lambda s: bool(re.search(r'\{task_text|\{context|\{input\}', s))},
        "B4": {"desc": "输出规范存在", "check": lambda s: bool(re.search(r'(输出|格式|output|format)', s, re.I))},
        "B5": {"desc": "防越界规则存在", "check": lambda s: bool(re.search(r'(不修改|不提供|不执行|❌)', s))},
        "B6": {"desc": "示例/模板存在", "check": lambda s: bool(re.search(r'(示例|例如|比如|例子|template|example)', s, re.I))},
    }},
    "C": {"name": "一致性", "weight": 0.20, "items": {
        "C1": {"desc": "命名规范(文件名匹配role_id)", "check": lambda s: True},  # 由调用方提供
        "C2": {"desc": "目录分类合理", "check": lambda s: True},
        "C3": {"desc": "引用一致性", "check": lambda s: bool(re.search(r'(extends|继承|include|base)', s))},
    }},
    "D": {"name": "可用性", "weight": 0.25, "items": {
        "D1": {"desc": "至少有3个✅(允许行为)", "check": lambda s: s.count('✅') >= 3},
        "D2": {"desc": "至少有2个❌(禁止行为)", "check": lambda s: s.count('❌') >= 2},
        "D3": {"desc": "无过时语法", "check": lambda s: not bool(re.search(r'(LEGACY|DEPRECATED|老版本)', s, re.I))},
        "D4": {"desc": "总字符>500", "check": lambda s: len(s) > 500},
    }},
}


class PromptOptimizer:
    """Prompt优化循环工具箱"""

    def __init__(self, work_dir: str = None, use_aggregator: bool = False):
        self.work_dir = Path(work_dir or str(_CODE_ROOT / "_prompt_lab"))
        os.makedirs(self.work_dir, exist_ok=True)
        self._meta_file = self.work_dir / "_meta.json"
        self._history_file = self.work_dir / "_history.jsonl"
        self.use_aggregator = use_aggregator
        self._load_meta()

    def _load_meta(self):
        if self._meta_file.exists():
            with open(self._meta_file) as f:
                self.meta = json.load(f)
        else:
            self.meta = {
                "created_at": time.time(),
                "versions": [],
                "next_id": 1,
                "project": os.path.basename(self.work_dir)
            }
            self._save_meta()

    def _save_meta(self):
        with open(self._meta_file, 'w') as f:
            json.dump(self.meta, f, indent=2, ensure_ascii=False)

    def _log_history(self, entry: dict):
        with open(self._history_file, 'a') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')

    def save_version(self, content: str, name: str = None, source_file: str = None) -> dict:
        """保存prompt版本"""
        vid = self.meta["next_id"]
        self.meta["next_id"] += 1
        
        version = {
            "id": vid,
            "name": name or f"v{vid}",
            "source": source_file or "(直接输入)",
            "content_len": len(content),
            "content_hash": hashlib.md5(content.encode()).hexdigest()[:12],
            "created_at": time.time(),
        }
        
        # 保存内容到文件
        ver_file = self.work_dir / f"v{vid}_{(name or 'unnamed').replace(' ', '_')}.prompt"
        with open(ver_file, 'w') as f:
            f.write(content)
        
        version["path"] = str(ver_file)
        self.meta["versions"].append(version)
        self._save_meta()
        
        print(f"✅ 已保存版本 v{vid}: {ver_file.name} ({version['content_len']} chars)")
        return version

    def list_versions(self) -> List[dict]:
        """列出所有版本"""
        if not self.meta["versions"]:
            print("📭 没有保存的版本")
            return []
        
        print(f"\n📋 Prompt版本列表 ({len(self.meta['versions'])}个):")
        print(f"{'ID':>4s} {'名称':20s} {'大小':>8s} {'Hash':15s} {'时间':20s}")
        print("-"*70)
        for v in reversed(self.meta["versions"]):
            t = datetime.fromtimestamp(v['created_at']).strftime('%m-%d %H:%M')
            print(f"{v['id']:>4d} {v['name']:20s} {v['content_len']:>8d} {v['content_hash']:15s} {t:20s}")
        return self.meta["versions"]

    def get_version(self, vid_or_name) -> Optional[dict]:
        """按ID或名称获取版本"""
        for v in self.meta["versions"]:
            if str(v['id']) == str(vid_or_name) or v['name'] == vid_or_name:
                return v
        # 尝试前缀匹配
        for v in self.meta["versions"]:
            if str(vid_or_name) in v['name'] or str(vid_or_name) in str(v['id']):
                return v
        return None

    def score(self, content: str, name: str = "unnamed", filepath: str = "") -> dict:
        """对prompt内容进行质量评分"""
        # ── Aggregator模式: 使用 engine/metrics/metrics_aggregator 评分 ──
        if self.use_aggregator:
            try:
                sys.path.insert(0, str(_CODE_ROOT.parent / "engine" / "metrics"))
                from metrics_aggregator import score_prompt
                agg = score_prompt(content, filepath)
                # 转换格式到内部格式
                dim_map = {"A": "结构完整性", "B": "内容质量", "C": "一致性", "D": "可用性"}
                result = {
                    "name": name,
                    "timestamp": time.time(),
                    "total_score": round(agg["total"], 2),  # aggregator已归一化到0-10
                    "grade": {"A": "A 🏆", "B": "B 👍", "C": "C ⚠️", "D": "D ❌"}.get(agg["grade"], "C ⚠️"),
                    "dimensions": {},
                    "weaknesses": agg["all_issues"],
                    "_aggregator": agg,
                }
                for dim_key, dim_name in dim_map.items():
                    raw = agg["dimensions"].get(dim_key, 0.0)
                    result["dimensions"][dim_key] = {
                        "name": dim_name,
                        "weight": 0.25,
                        "score": raw / 10.0,
                        "passed": f"{'-'}/-",
                        "items": {},
                    }
                return result
            except ImportError as e:
                print(f"⚠️ aggregator导入失败: {e}，回退内部评分")
            finally:
                sys.path.pop(0)
        
        # ── 内部评分模式 ──
        result = {
            "name": name,
            "timestamp": time.time(),
            "total_score": 0.0,
            "grade": "",
            "dimensions": {},
            "weaknesses": []
        }
        
        weighted_sum = 0.0
        
        for dim_key, dim in QUALITY_DIMENSIONS.items():
            dim_result = {
                "name": dim["name"],
                "weight": dim["weight"],
                "score": 0.0,
                "items": {}
            }
            
            passed = 0
            total = len(dim["items"])
            
            for item_key, item in dim["items"].items():
                try:
                    ok = item["check"](content)
                except:
                    ok = False
                
                dim_result["items"][item_key] = {
                    "desc": item["desc"],
                    "passed": ok,
                    "score": 1.0 if ok else 0.0
                }
                if ok:
                    passed += 1
                else:
                    result["weaknesses"].append(f"{item_key} ({item['desc']})")
            
            dim_result["score"] = passed / total if total > 0 else 0.0
            dim_result["passed"] = f"{passed}/{total}"
            result["dimensions"][dim_key] = dim_result
            weighted_sum += dim_result["score"] * dim["weight"]
        
        result["total_score"] = round(weighted_sum * 10, 2)  # 归一化到1-10
        if result["total_score"] >= 8.0:
            result["grade"] = "A 🏆"
        elif result["total_score"] >= 6.0:
            result["grade"] = "B 👍"
        elif result["total_score"] >= 4.0:
            result["grade"] = "C ⚠️"
        else:
            result["grade"] = "D ❌"
        
        return result

    def format_score(self, result: dict) -> str:
        """格式化评分结果"""
        lines = []
        lines.append(f"\n{'='*50}")
        lines.append(f"📊 Prompt评分: {result['name']}")
        lines.append(f"   总分: {result['total_score']}/10.0 | 等级: {result['grade']}")
        lines.append(f"   时间: {datetime.fromtimestamp(result['timestamp']).strftime('%H:%M:%S')}")
        lines.append(f"{'='*50}")
        
        for dim_key, dim in result["dimensions"].items():
            bar = "█" * int(dim["score"] * 10) + "░" * (10 - int(dim["score"] * 10))
            lines.append(f"\n  {dim_key}. {dim['name']} [{bar}] {dim['passed']} ({dim['score']*10:.1f}/10)")
            for item_key, item in dim["items"].items():
                icon = "✅" if item["passed"] else "❌"
                lines.append(f"     {icon} {item_key}: {item['desc']}")
        
        if result["weaknesses"]:
            lines.append(f"\n  ⚠️ 弱项 ({len(result['weaknesses'])}个):")
            for w in result["weaknesses"][:10]:
                lines.append(f"     - {w}")
        
        return '\n'.join(lines)

    def score_file(self, filepath: str) -> dict:
        """对文件评分"""
        with open(filepath) as f:
            content = f.read()
        result = self.score(content, name=os.path.basename(filepath), filepath=filepath)
        
        # 记录历史
        entry = {
            "type": "score",
            "file": filepath,
            "name": os.path.basename(filepath),
            **result
        }
        self._log_history(entry)
        
        return result

    def ab_test(self, content_a: str, content_b: str, test_input: str = "",
                name_a: str = "A", name_b: str = "B") -> dict:
        """A/B测试 — 对比两个prompt版本
        
        注意: 实际效果需要LLM调用才能评估。
        这里提供结构化的对比框架和元评估。
        """
        score_a = self.score(content_a, name=name_a)
        score_b = self.score(content_b, name=name_b)
        
        result = {
            "test_input": test_input,
            "timestamp": time.time(),
            "version_a": score_a,
            "version_b": score_b,
            "diff": {
                "score_diff": round(score_b["total_score"] - score_a["total_score"], 2),
                "dimension_diffs": {}
            }
        }
        
        for dim in ["A", "B", "C", "D"]:
            a_s = score_a["dimensions"][dim]["score"]
            b_s = score_b["dimensions"][dim]["score"]
            result["diff"]["dimension_diffs"][dim] = round(b_s - a_s, 2)
        
        # 记录历史
        entry = {**result, "type": "ab_test"}
        self._log_history(entry)
        
        return result

    def format_ab_result(self, result: dict) -> str:
        """格式化A/B测试结果"""
        lines = []
        lines.append(f"\n{'='*50}")
        lines.append(f"🔄 A/B Test 结果")
        lines.append(f"   测试输入: {result['test_input'] or '(无)'}")
        lines.append(f"{'='*50}")
        
        # 对比表
        lines.append(f"\n  {'维度':10s} {'版本A':>8s} {'版本B':>8s} {'差异':>8s}")
        lines.append(f"  {'-'*35}")
        a = result["version_a"]
        b = result["version_b"]
        lines.append(f"  {'总分':10s} {a['total_score']:>8.1f} {b['total_score']:>8.1f} {result['diff']['score_diff']:>+8.1f}")
        
        for dim in ["A", "B", "C", "D"]:
            a_s = a["dimensions"][dim]["score"] * 10
            b_s = b["dimensions"][dim]["score"] * 10
            diff = result["diff"]["dimension_diffs"][dim] * 10
            lines.append(f"  {dim+'.'+a['dimensions'][dim]['name']:10s} {a_s:>8.1f} {b_s:>8.1f} {diff:>+8.1f}")
        
        # 弱项对比
        wsp = "\n  ".join(result["version_a"]["weaknesses"][:5])
        if wsp:
            lines.append(f"\n  版本A弱项:\n    {wsp}")
        wsp = "\n  ".join(result["version_b"]["weaknesses"][:5])
        if wsp:
            lines.append(f"\n  版本B弱项:\n    {wsp}")
        
        # 判胜负
        diff = result['diff']['score_diff']
        if diff > 0.5:
            lines.append(f"\n  🏆 版本B 明显优于 版本A (+{diff:.1f})")
        elif diff < -0.5:
            lines.append(f"\n  🏆 版本A 明显优于 版本B ({diff:.1f})")
        else:
            lines.append(f"\n  ⚖️ 无明显差异 ({diff:.1f})，建议增大样本量")
        
        return '\n'.join(lines)

    def diff_versions(self, vid_a, vid_b) -> str:
        """对比两个版本的差异"""
        va = self.get_version(vid_a)
        vb = self.get_version(vid_b)
        
        if not va or not vb:
            return "❌ 版本不存在"
        
        with open(va['path']) as f:
            content_a = f.read()
        with open(vb['path']) as f:
            content_b = f.read()
        
        lines_a = content_a.splitlines()
        lines_b = content_b.splitlines()
        
        diff = list(difflib.unified_diff(
            lines_a, lines_b,
            fromfile=f"v{va['id']}:{va['name']}",
            tofile=f"v{vb['id']}:{vb['name']}",
            lineterm=''
        ))
        
        lines = []
        lines.append(f"\n📝 版本对比: v{va['id']}({va['name']}) ↔ v{vb['id']}({vb['name']})")
        lines.append(f"   大小: {va['content_len']} → {vb['content_len']} chars\n")
        lines.append('\n'.join(diff[:80]))  # 限制显示行数
        
        if len(diff) > 80:
            lines.append(f"\n... 还有 {len(diff) - 80} 行差异")
        
        return '\n'.join(lines)

    def history(self, n: int = 10) -> List[dict]:
        """查看评分历史"""
        if not self._history_file.exists():
            print("📭 没有历史记录")
            return []
        
        entries = []
        with open(self._history_file) as f:
            for line in f:
                if line.strip():
                    entries.append(json.loads(line))
        
        entries = entries[-n:]
        print(f"\n📊 评分历史 (最近{len(entries)}条):")
        for e in entries:
            if e.get("type") == "ab_test":
                print(f"  🔄 A/B Test | {e['version_a']['name']} vs {e['version_b']['name']} | diff={e['diff']['score_diff']:+.1f}")
            else:
                print(f"  📝 {e.get('name','?')} | 总分={e.get('total_score','?'):.1f} | 等级={e.get('grade','?')}")
        return entries

    def stats(self) -> dict:
        """质量统计"""
        if not self._history_file.exists():
            print("📭 没有数据")
            return {}
        
        scores = []
        with open(self._history_file) as f:
            for line in f:
                if line.strip():
                    e = json.loads(line)
                    if e.get("type") == "score":
                        scores.append(e["total_score"])
        
        if not scores:
            print("📭 没有评分数据")
            return {}
        
        stats = {
            "count": len(scores),
            "avg": round(sum(scores) / len(scores), 2),
            "min": min(scores),
            "max": max(scores),
            "latest": scores[-1],
            "grades": {}
        }
        
        for s in scores:
            if s >= 8:
                g = "A"
            elif s >= 6:
                g = "B"
            elif s >= 4:
                g = "C"
            else:
                g = "D"
            stats["grades"][g] = stats["grades"].get(g, 0) + 1
        
        print(f"\n📈 质量统计 ({stats['count']}次评分):")
        print(f"   平均分: {stats['avg']:.2f}")
        print(f"   最高分: {stats['max']:.2f}")
        print(f"   最低分: {stats['min']:.2f}")
        print(f"   最新分: {stats['latest']:.2f}")
        print(f"   等级分布: ", end="")
        for g in ["A", "B", "C", "D"]:
            cnt = stats["grades"].get(g, 0)
            bar = "█" * cnt
            print(f"{g}:{cnt}({bar}) ", end="")
        print()
        
        return stats
    
    # ── 弱项→修复建议映射 ──────────────────────────
    
    _FIX_SUGGESTIONS = {
        "A1": "在文件顶部添加 `---` frontmatter分隔符，包含role_id和tags",
        "A2": "在frontmatter中添加 `tags: [category, function]` 数组",
        "A3": "在frontmatter中添加 `role_id:` 字段标识角色ID",
        "A4": "添加 `## 你的角色` 或 `## 工作范围` 段描述职责",
        "A5": "添加 ✅/❌ 边界段，明确允许和禁止行为",
        "B1": "扩展职责描述，用 `✅ 你只做以下事情：` 明确范围",
        "B2": "添加 `❌ 你不做以下事情：` 列举禁止行为",
        "B3": "在适当位置添加 `{task_text}` 或 `{context}` 占位符",
        "B4": "添加 `## 输出格式` 段和 `{output_spec}` 占位符",
        "B5": "添加防越界规则：`❌ 不修改原始内容 / 不提供替代实现 / 不执行新步骤`",
        "B6": "添加示例或模板段落，用 `示例：` 或 `例如：` 引导",
        "C1": "确保文件名匹配 `role_id`，按功能目录分类",
        "C2": "将文件放入正确的功能分类目录",
        "C3": "添加 `extends: _base` 或 `include:` 引用基础模板",
        "D1": "至少列出3个 ✅ 允许行为",
        "D2": "至少列出2个 ❌ 禁止行为",
        "D3": "移除过时语法标记(LEGACY/DEPRECATED)",
        "D4": "扩展内容至500字符以上，增加具体指令",
    }
    
    def suggest_fix(self, weaknesses: list) -> list:
        """根据弱项列表生成修复建议"""
        suggestions = []
        for w in weaknesses:
            key = w.split(" ")[0] if " " in w else w
            suggestion = self._FIX_SUGGESTIONS.get(key, f"修复: {w}")
            suggestions.append({"weakness": w, "fix": suggestion, "key": key})
        return suggestions
    
    def optimize(self, file_path: str, auto_fix: bool = False) -> dict:
        """完整优化循环: 评分→分析→修复→重评"""
        with open(file_path) as f:
            content = f.read()
        
        # Step 1: 评分
        print(f"\n{'='*50}")
        print(f"🔍 第1步: 评分 — {os.path.basename(file_path)}")
        print(f"{'='*50}")
        result = self.score(content, name=os.path.basename(file_path))
        print(self.format_score(result))
        
        # Step 2: 分析弱项
        print(f"\n{'='*50}")
        print(f"📋 第2步: 弱项分析 ({len(result['weaknesses'])}项)")
        print(f"{'='*50}")
        if not result["weaknesses"]:
            print("  ✅ 无弱项！Prompt质量优秀")
            return {"status": "excellent", "score": result}
        
        suggestions = self.suggest_fix(result["weaknesses"])
        for s in suggestions:
            print(f"  ❌ {s['weakness']}")
            print(f"     → 💡 {s['fix']}")
            print()
        
        # Step 3: 修复建议汇总
        print(f"\n{'='*50}")
        print(f"🛠️  第3步: 修复优先级")
        print(f"{'='*50}")
        priority = {"P0": [], "P1": [], "P2": []}
        for s in suggestions:
            if s['key'].startswith('D') or result['total_score'] < 3.5:
                priority["P0"].append(s)
            elif s['key'].startswith('B'):
                priority["P1"].append(s)
            else:
                priority["P2"].append(s)
        
        for p, items in priority.items():
            if items:
                print(f"\n  {p} ({len(items)}项):")
                for s in items:
                    print(f"    - {s['fix']}")
        
        # Step 4: 预估修复后分数
        estimated = min(10.0, result['total_score'] + len(suggestions) * 0.3)
        print(f"\n  📈 预估修复后总分: {estimated:.1f}/10 (当前: {result['total_score']:.1f})")
        
        # Step 5: 提交流程提示
        print(f"\n{'='*50}")
        print(f"✅ 第4步: 下一步行动")
        print(f"{'='*50}")
        print(f"  1. 手动修复上述弱项")
        print(f"  2. 保存新版本: python prompt_optimizer.py save v2 {file_path}")
        print(f"  3. 重新评分验证: python prompt_optimizer.py score {file_path}")
        print(f"  4. A/B对比: python prompt_optimizer.py ab v1 v2")
        print(f"  5. 交付前自检: python scripts/pre_delivery_check.py check --task-type 产出 --outputs {file_path}")
        
        return {
            "status": "needs_improvement",
            "score": result,
            "weaknesses": result["weaknesses"],
            "suggestions": suggestions,
            "estimated_score": estimated
        }
    
    def init_project(self, name: str = None):
        """初始化prompt优化项目"""
        if name:
            self.meta["project"] = name
            self._save_meta()
        
        print(f"\n🚀 Prompt优化实验室已初始化")
        print(f"   目录: {self.work_dir}")
        print(f"   项目: {self.meta['project']}")
        print(f"\n快速开始:")
        print(f"  1. 保存第一个版本:")
        print(f"     python prompt_optimizer.py save v1 my_prompt.prompt")
        print(f"  2. 评分:")
        print(f"     python prompt_optimizer.py score my_prompt.prompt")
        print(f"  3. 优化循环:")
        print(f"     python prompt_optimizer.py optimize my_prompt.prompt")
        print(f"  4. A/B测试:")
        print(f"     python prompt_optimizer.py ab v1 v2 --input \"测试输入\"")
        
        return str(self.work_dir)


# ==================== CLI ====================

def main():
    parser = argparse.ArgumentParser(description="Prompt优化循环工具箱")
    parser.add_argument("--dir", help="工作目录", default=None)
    parser.add_argument("--aggregator", action="store_true", help="使用metrics_aggregator评分引擎(替代内部评分)")
    
    subparsers = parser.add_subparsers(dest="command")
    
    subparsers.add_parser("init", help="初始化项目")
    subparsers.add_parser("list", help="版本列表")
    subparsers.add_parser("history", help="评分历史")
    subparsers.add_parser("stats", help="质量统计")
    
    save_p = subparsers.add_parser("save", help="保存版本")
    save_p.add_argument("name", help="版本名称")
    save_p.add_argument("file", help="prompt文件路径")
    
    score_p = subparsers.add_parser("score", help="评分")
    score_p.add_argument("file", help="prompt文件")
    
    suggest_p = subparsers.add_parser("suggest-fix", help="根据弱项生成修复建议")
    suggest_p.add_argument("file", help="prompt文件")
    
    optimize_p = subparsers.add_parser("optimize", help="完整优化循环: 评分→分析→修复建议→重评预估")
    optimize_p.add_argument("file", help="prompt文件")
    
    optimize_auto_p = subparsers.add_parser("optimize-auto", help="自动优化循环: 评分→分析→保存→重评")
    optimize_auto_p.add_argument("file", help="prompt文件")
    optimize_auto_p.add_argument("--name", default="auto-optimized", help="新版本名称")
    
    ab_p = subparsers.add_parser("ab", help="A/B测试")
    ab_p.add_argument("version_a")
    ab_p.add_argument("version_b")
    ab_p.add_argument("--input", default="", help="测试输入")
    
    diff_p = subparsers.add_parser("diff", help="版本对比")
    diff_p.add_argument("version_a")
    diff_p.add_argument("version_b")
    
    args = parser.parse_args()
    
    po = PromptOptimizer(work_dir=args.dir, use_aggregator=args.aggregator)
    
    if args.command == "init":
        po.init_project()
    
    elif args.command == "list":
        po.list_versions()
    
    elif args.command == "history":
        po.history()
    
    elif args.command == "stats":
        po.stats()
    
    elif args.command == "save":
        with open(args.file) as f:
            content = f.read()
        po.save_version(content, name=args.name, source_file=args.file)
    
    elif args.command == "score":
        result = po.score_file(args.file)
        print(po.format_score(result))
    
    elif args.command == "suggest-fix":
        with open(args.file) as f:
            content = f.read()
        result = po.score(content, name=os.path.basename(args.file))
        suggestions = po.suggest_fix(result["weaknesses"])
        print(f"\n📋 弱项修复建议 ({len(suggestions)}项):")
        for s in suggestions:
            print(f"  ❌ {s['weakness']}")
            print(f"     → 💡 {s['fix']}")
            print()
        if not suggestions:
            print("  ✅ 无弱项！")
    
    elif args.command == "optimize":
        po.optimize(args.file)
    
    elif args.command == "optimize-auto":
        with open(args.file) as f:
            content = f.read()
        print(f"\n{'='*50}")
        print(f"🔍 第1步: 评分 — {os.path.basename(args.file)}")
        print(f"{'='*50}")
        result = po.score(content, name=args.name)
        print(po.format_score(result))
        
        if result["weaknesses"]:
            suggestions = po.suggest_fix(result["weaknesses"])
            print(f"\n{'='*50}")
            print(f"📋 第2步: 弱项修复建议 ({len(suggestions)}项)")
            print(f"{'='*50}")
            for s in suggestions:
                print(f"  ❌ {s['weakness']}")
                print(f"     → 💡 {s['fix']}")
                print()
            print(f"\n  💡 手动修复后执行: python prompt_optimizer.py score {args.file} --aggregator")
        else:
            print("\n  ✅ 无弱项！Prompt质量优秀")
        
        # 保存新版本
        po.save_version(content, name=args.name, source_file=args.file)
        print(f"\n  ✅ 保存为版本: {args.name}")
    
    elif args.command == "ab":
        # 从版本库读取
        va = po.get_version(args.version_a)
        vb = po.get_version(args.version_b)
        if not va or not vb:
            print("❌ 版本不存在，先从文件读取...")
            print("   提示: 先用 save 保存版本")
            return
        
        with open(va['path']) as f:
            ca = f.read()
        with open(vb['path']) as f:
            cb = f.read()
        
        result = po.ab_test(ca, cb, test_input=args.input,
                           name_a=va['name'], name_b=vb['name'])
        print(po.format_ab_result(result))
    
    elif args.command == "diff":
        print(po.diff_versions(args.version_a, args.version_b))
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
