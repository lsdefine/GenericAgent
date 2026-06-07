#!/usr/bin/env python3
"""
arena_benchmark_suite.py — Arena 标准化基准测试套件 🎪

基于 arena_sop + solver_team_proto 的标准化性能基线采集工具。

用法:
  python arena_benchmark_suite.py list               # 列出所有测试用例
  python arena_benchmark_suite.py run <测试名>        # 运行单个测试
  python arena_benchmark_suite.py run all              # 运行全量测试套件
  python arena_benchmark_suite.py baseline             # 显示当前基线
  python arena_benchmark_suite.py compare --before <文件> --after <文件>  # 对比两次基线
"""

import os, sys, json, time, subprocess, textwrap
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

# 将 benchmarker.py 作为基础设施
SCRIPT_DIR = Path(__file__).resolve().parent
CODE_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

try:
    from benchmarker import Benchmark, BenchmarkResult
except ImportError:
    print("⚠️  benchmarker.py 未找到，请确保 scripts/benchmarker.py 存在")
    sys.exit(1)

# ==================== 基准测试用例定义 ====================

BENCHMARK_TASKS = {
    "architect_design": {
        "title": "架构师 — 系统设计",
        "description": "设计一个简单的Web服务架构（认证+API+存储三层）",
        "roles": ["architect"],
        "timeout": 300,
        "iterations": 1,
        "expected_output": "架构设计方案文档",
        "weight": 1.0,
    },
    "hunter_research": {
        "title": "资料猎手 — 信息采集",
        "description": "调研当前流行的Python Web框架（FastAPI/Flask/Django）的优缺点对比",
        "roles": ["hunter"],
        "timeout": 300,
        "iterations": 1,
        "expected_output": "技术调研报告",
        "weight": 1.0,
    },
    "researcher_analysis": {
        "title": "调研专家 — 竞品分析",
        "description": "分析GitHub Copilot、Codeium、Amazon CodeWhisperer三款AI编程助手的核心差异",
        "roles": ["researcher"],
        "timeout": 300,
        "iterations": 1,
        "expected_output": "竞品分析报告",
        "weight": 1.0,
    },
    "writer_doc": {
        "title": "技术写手 — 文档写作",
        "description": "写一篇面向初学者的Docker入门指南（包含安装、基本命令、Dockerfile编写）",
        "roles": ["writer"],
        "timeout": 300,
        "iterations": 1,
        "expected_output": "技术文章",
        "weight": 1.0,
    },
    "coder_script": {
        "title": "编码专家 — 脚本开发",
        "description": "编写一个Python脚本：监控当前目录下文件变化，输出新增/修改/删除的文件列表",
        "roles": ["coder"],
        "timeout": 300,
        "iterations": 1,
        "expected_output": "Python脚本 + 使用说明",
        "weight": 1.0,
    },
    # 多角色团队管线（端到端）
    "team_pipeline": {
        "title": "团队管线 — 完整端到端",
        "description": "全团队协作：架构师设计→猎手资料→写手文档→编码实现→判别者验收",
        "roles": ["architect", "hunter", "writer", "coder", "discriminator"],
        "timeout": 600,
        "iterations": 1,
        "expected_output": "全流程报告",
        "weight": 2.0,
    },
}


# ==================== 基准测试运行器 ====================

class ArenaBenchmarkSuite:
    """Arena 标准化基准测试套件"""

    def __init__(self, work_dir: Optional[str] = None):
        self.work_dir = Path(work_dir) if work_dir else CODE_ROOT / "temp" / "arena_benchmark"
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.baseline_file = self.work_dir / "baseline.json"
        self.results = {}

    def list_tasks(self):
        """列出所有可用的基准测试用例"""
        print(f"\n{'='*60}")
        print(f"  🎪 Arena 标准化基准测试套件")
        print(f"{'='*60}")
        for name, task in BENCHMARK_TASKS.items():
            print(f"\n  📋 {name}")
            print(f"     标题: {task['title']}")
            print(f"     角色: {', '.join(task['roles'])}")
            print(f"     超时: {task['timeout']}s")
            print(f"     描述: {task['description'][:60]}...")
        print(f"\n  共 {len(BENCHMARK_TASKS)} 个测试用例")
        return BENCHMARK_TASKS

    def run_single(self, test_name: str, iterations: int = 1) -> Dict:
        """运行单个基准测试，支持多轮迭代统计方差"""
        if test_name not in BENCHMARK_TASKS:
            print(f"❌ 未知测试: {test_name}")
            print(f"   可用测试: {', '.join(BENCHMARK_TASKS.keys())}")
            return {}

        task = BENCHMARK_TASKS[test_name]
        task_iters = iterations  # CLI 传入，覆盖 task 定义
        print(f"\n  🚀 运行基准测试: {test_name} (x{task_iters}轮)")
        print(f"  {'='*50}")
        print(f"  任务: {task['description'][:80]}...")
        print(f"  角色: {', '.join(task['roles'])}")
        print(f"  超时: {task['timeout']}s")

        samples = []
        for i in range(task_iters):
            def _run_solver():
                t0 = time.time()
                try:
                    solver_path = str(SCRIPT_DIR / "solver_team_proto.py")
                    roles_str = ",".join(task['roles'])
                    result = subprocess.run(
                        [sys.executable, solver_path, "run", task['description'],
                         "--roles", roles_str, "--iterations", str(task['iterations']),
                         "--timeout", str(task['timeout'])],
                        capture_output=True, text=True, timeout=task['timeout'] + 30,
                        cwd=str(CODE_ROOT)
                    )
                    elapsed = time.time() - t0
                    return {
                        "success": result.returncode == 0,
                        "elapsed": elapsed,
                        "returncode": result.returncode,
                        "stdout_len": len(result.stdout),
                        "stderr_len": len(result.stderr),
                    }
                except subprocess.TimeoutExpired:
                    return {"success": False, "elapsed": task['timeout'] + 30, "error": "timeout"}
                except Exception as e:
                    return {"success": False, "elapsed": time.time() - t0, "error": str(e)}

            result = _run_solver()
            samples.append(result)
            print(f"    轮次 {i+1}/{task_iters}: {'✅' if result.get('success') else '❌'} "
                  f"{result.get('elapsed', 0):.1f}s")

        # 方差统计
        elapsed_list = [s.get("elapsed", 0) for s in samples if s.get("success")]
        if elapsed_list:
            mean = sum(elapsed_list) / len(elapsed_list)
            variance = sum((e - mean) ** 2 for e in elapsed_list) / len(elapsed_list)
            stddev = variance ** 0.5
        else:
            mean = 0
            stddev = 0

        test_result = {
            "test_name": test_name,
            "title": task['title'],
            "roles": task['roles'],
            "timestamp": datetime.now().isoformat(),
            "iterations": task_iters,
            "samples": samples,
            "success": any(s.get("success") for s in samples),
            "elapsed_s": round(mean, 2),
            "elapsed_stddev": round(stddev, 2),
            "elapsed_list": [round(e, 2) for e in elapsed_list],
            "weight": task['weight'],
        }

        self.results[test_name] = test_result
        _print_result(test_result)
        return test_result

    def run_all(self, iterations: int = 1) -> Dict[str, Dict]:
        """运行全部基准测试"""
        print(f"\n{'='*60}")
        print(f"  🎪 Arena 全量基准测试开始")
        print(f"  {datetime.now().isoformat()}")
        print(f"{'='*60}")

        for name in BENCHMARK_TASKS:
            self.run_single(name, iterations=iterations)
            print()

        self._save_results()
        self._print_summary()
        return self.results

    def show_baseline(self):
        """显示已保存的基线数据"""
        if not self.baseline_file.exists():
            print("⚠️  暂无保存的基线数据")
            return {}
        with open(self.baseline_file) as f:
            baseline = json.load(f)
        print(f"\n{'='*60}")
        print(f"  📊 Arena 性能基线 (保存于 {baseline.get('timestamp', '?')})")
        print(f"{'='*60}")
        for name, data in baseline.get("results", {}).items():
            _print_result(data)
        print(f"\n  综合得分: {baseline.get('score', 0):.1f}")
        return baseline

    def _save_results(self):
        """保存测试结果为基线"""
        score = sum(
            r.get("weight", 1) * (100 if r.get("success") else 0) / (1 + r.get("elapsed_s", 300) / 300)
            for r in self.results.values()
        )
        baseline = {
            "timestamp": datetime.now().isoformat(),
            "tests_run": len(self.results),
            "tests_passed": sum(1 for r in self.results.values() if r.get("success")),
            "score": round(score, 1),
            "results": self.results,
        }
        with open(self.baseline_file, "w") as f:
            json.dump(baseline, f, indent=2, ensure_ascii=False)
        print(f"\n  💾 基线已保存到: {self.baseline_file}")

    def _print_summary(self):
        """打印汇总"""
        passed = sum(1 for r in self.results.values() if r.get("success"))
        total = len(self.results)
        avg_time = sum(r.get("elapsed_s", 0) for r in self.results.values()) / max(total, 1)
        print(f"{'='*60}")
        print(f"  📊 汇总: {passed}/{total} 通过 | 平均耗时 {avg_time:.1f}s")
        print(f"{'='*60}")

    def compare_baselines(self, before_file: str, after_file: str):
        """对比两次基线"""
        with open(before_file) as f:
            before = json.load(f)
        with open(after_file) as f:
            after = json.load(f)

        print(f"\n{'='*60}")
        print(f"  📊 基线对比")
        print(f"{'='*60}")
        print(f"  Before: {before.get('timestamp', '?')} (得分: {before.get('score', 0)})")
        print(f"  After:  {after.get('timestamp', '?')} (得分: {after.get('score', 0)})")
        print()

        before_results = before.get("results", {})
        after_results = after.get("results", {})

        for name in BENCHMARK_TASKS:
            br = before_results.get(name, {})
            ar = after_results.get(name, {})
            bt = br.get("elapsed_s", 0)
            at = ar.get("elapsed_s", 0)
            diff = at - bt
            arrow = "⬆" if diff > 5 else ("⬇" if diff < -5 else "➡")
            print(f"  {name:20s}  Before: {bt:>6.1f}s  After: {at:>6.1f}s  {arrow} ({diff:+.1f}s)")

        score_diff = after.get("score", 0) - before.get("score", 0)
        print(f"\n  综合得分变化: {score_diff:+.1f}")

    def _scan_baseline_history(self) -> list:
        """扫描历史基线文件, 按时间排序"""
        history = []
        # 先加载当前 baseline.json
        if self.baseline_file.exists():
            with open(self.baseline_file) as f:
                data = json.load(f)
                data['_file'] = str(self.baseline_file)
                data['_label'] = 'latest'
                history.append(data)
        # 扫描历史 baseline_*.json
        for fpath in sorted(self.work_dir.glob("baseline_*.json")):
            with open(fpath) as f:
                data = json.load(f)
                data['_file'] = str(fpath)
                data['_label'] = fpath.stem.replace('baseline_', '')
                history.append(data)
        return history

    def generate_trend(self, output_html: str = None):
        """生成趋势图 HTML (Chart.js)"""
        if output_html is None:
            output_html = str(self.work_dir / "arena_trend.html")

        history = self._scan_baseline_history()
        if not history:
            print("⚠️  没有基线数据, 生成示例趋势图")
            self._generate_demo_trend(output_html)
            return

        # 构建图表数据
        labels = []
        datasets = {}
        for h in history:
            label = h.get('_label', h.get('timestamp', 'unknown'))[:16]
            labels.append(label)
            for name, result in h.get('results', {}).items():
                if name not in datasets:
                    datasets[name] = []
                datasets[name].append({
                    'elapsed': result.get('elapsed_s', 0),
                    'stddev': result.get('elapsed_stddev', 0),
                    'success': result.get('success', False),
                })

        # 生成 HTML
        html = self._build_trend_html(labels, datasets, history)
        with open(output_html, 'w') as f:
            f.write(html)
        print(f"✅ 趋势图已生成: {output_html}")

    def _build_trend_html(self, labels: list, datasets: dict, history: list) -> str:
        """构建 Chart.js 趋势图 HTML"""
        colors = ['#4e79a7', '#f28e2c', '#e15759', '#76b7b2', '#59a14f',
                  '#edc949', '#af7aa1', '#ff9da7', '#9c755f', '#bab0ac']
        ds_json = []
        for i, (name, points) in enumerate(datasets.items()):
            color = colors[i % len(colors)]
            data_str = json.dumps([p['elapsed'] for p in points])
            err_str = json.dumps([p['stddev'] for p in points])
            ds_json.append(f"""
            {{
                label: '{name}',
                data: {data_str},
                errorBars: {err_str},
                backgroundColor: '{color}88',
                borderColor: '{color}',
                borderWidth: 2,
                tension: 0.3,
                pointRadius: 5
            }}""")

        score_list = json.dumps([h.get('score', 0) for h in history])
        labels_json = json.dumps(labels)

        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>Arena 基准趋势</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family: -apple-system, sans-serif; background: #f8f9fa; padding: 30px; }}
h1 {{ color: #1a1a2e; margin-bottom: 20px; }}
.chart-container {{ background: white; border-radius: 12px; padding: 20px; margin-bottom: 30px;
  box-shadow: 0 2px 12px rgba(0,0,0,.08); }}
.summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 30px; }}
.card {{ background: white; border-radius: 10px; padding: 20px; box-shadow: 0 2px 8px rgba(0,0,0,.06); }}
.card h3 {{ color: #666; font-size: 14px; text-transform: uppercase; }}
.card .value {{ font-size: 28px; font-weight: 700; color: #1a1a2e; margin-top: 8px; }}
</style></head>
<body>
<h1>📊 Arena 基准测试趋势</h1>
<div class="summary">
  <div class="card"><h3>基线数</h3><div class="value">{len(history)}</div></div>
  <div class="card"><h3>测试项</h3><div class="value">{len(datasets)}</div></div>
  <div class="card"><h3>最新得分</h3><div class="value">{history[-1].get('score', 0) if history else 0:.1f}</div></div>
</div>

<div class="chart-container">
  <canvas id="trendChart"></canvas>
</div>

<div class="chart-container">
  <canvas id="scoreChart"></canvas>
</div>

<script>
const labels = {labels_json};
const datasets = [{','.join(ds_json)}];
const scoreData = {score_list};

// 耗时趋势图（含误差条）
const ctx1 = document.getElementById('trendChart').getContext('2d');
new Chart(ctx1, {{
  type: 'line',
  data: {{ labels, datasets }},
  options: {{
    responsive: true,
    plugins: {{
      title: {{ display: true, text: '各测试耗时趋势 (s)', font: {{ size: 16 }} }},
      legend: {{ position: 'bottom' }}
    }},
    scales: {{
      y: {{ beginAtZero: true, title: {{ display: true, text: '耗时 (s)' }} }}
    }}
  }}
}});

// 综合得分趋势
const ctx2 = document.getElementById('scoreChart').getContext('2d');
new Chart(ctx2, {{
  type: 'bar',
  data: {{
    labels,
    datasets: [{{
      label: '综合得分',
      data: scoreData,
      backgroundColor: '#4e79a788',
      borderColor: '#4e79a7',
      borderWidth: 2,
      borderRadius: 6
    }}]
  }},
  options: {{
    responsive: true,
    plugins: {{
      title: {{ display: true, text: '综合得分趋势', font: {{ size: 16 }} }},
      legend: {{ display: false }}
    }},
    scales: {{
      y: {{ beginAtZero: true, title: {{ display: true, text: '得分' }} }}
    }}
  }}
}});
</script>
</body></html>"""
        return html

    def _generate_demo_trend(self, output_html: str):
        """生成示例趋势图（demo 模式）"""
        demo_labels = ["基线A", "基线B", "基线C", "基线D", "基线E"]
        demo_datasets = {
            "architect_design": [45.2, 42.8, 40.1, 38.5, 36.2],
            "hunter_research": [52.1, 50.3, 48.7, 45.9, 44.0],
            "writer_doc": [38.7, 36.5, 35.2, 33.8, 32.1],
            "coder_script": [65.3, 62.1, 58.9, 55.4, 52.8],
            "team_pipeline": [180.5, 175.2, 168.3, 162.7, 158.4],
        }
        labels = demo_labels
        datasets = {}
        for name, values in demo_datasets.items():
            datasets[name] = [{'elapsed': v, 'stddev': v * 0.08, 'success': True} for v in values]
        demo_history = [
            {'timestamp': f'2026-05-{d:02d}', 'score': 60 + i * 5, '_label': lbl}
            for i, (d, lbl) in enumerate(zip([10, 17, 24, 31, 38], demo_labels))
        ]
        html = self._build_trend_html(labels, datasets, demo_history)
        with open(output_html, 'w') as f:
            f.write(html)
        print(f"✅ 示例趋势图已生成: {output_html} (首次运行请执行实际基准测试)")


def _print_result(r: dict):
    """单行打印测试结果（含方差信息）"""
    status = "✅" if r.get("success") else "❌"
    name = r.get("test_name", "?")
    title = r.get("title", "")
    elapsed = r.get("elapsed_s", 0)
    stddev = r.get("elapsed_stddev", 0)
    weight = r.get("weight", 1)
    score = weight * (100 if r.get("success") else 0) / (1 + elapsed / 300)
    iters = r.get("iterations", 1)
    var_str = f" ±{stddev:.1f}s" if stddev > 0 and iters > 1 else ""
    print(f"  {status} {name:20s} | {title:30s} | {elapsed:>6.1f}s{var_str:12s} | 得分 {score:.1f} (x{iters})")


# ==================== 入口 ====================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Arena 标准化基准测试套件")
    parser.add_argument("action", choices=["list", "run", "baseline", "compare", "trend"],
                        help="操作类型")
    parser.add_argument("target", nargs="?", default="all",
                        help="测试名 (或 'all')")
    parser.add_argument("--iterations", "-n", type=int, default=1,
                        help="每项跑 N 轮 (默认1, 推荐5+ 用于方差统计)")
    parser.add_argument("--before", help="对比的基线文件 (before)")
    parser.add_argument("--after", help="对比的基线文件 (after)")
    parser.add_argument("--output", "-o", help="trend 输出 HTML 文件路径")

    args = parser.parse_args()
    suite = ArenaBenchmarkSuite()

    if args.action == "list":
        suite.list_tasks()
    elif args.action == "run":
        if args.target == "all":
            suite.run_all(iterations=args.iterations)
        else:
            suite.run_single(args.target, iterations=args.iterations)
    elif args.action == "baseline":
        suite.show_baseline()
    elif args.action == "compare":
        if not args.before or not args.after:
            print("❌ compare 需要 --before 和 --after 参数")
            return
        suite.compare_baselines(args.before, args.after)
    elif args.action == "trend":
        suite.generate_trend(args.output)


if __name__ == "__main__":
    main()
