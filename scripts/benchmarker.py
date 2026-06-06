#!/usr/bin/env python3
"""
benchmarker.py — 性能基准测试工具 ⚡

基于 discriminator_performance_benchmarker_sop.md 实现统计严谨的性能评估。

用法:
  # 基准测试一个表达式
  python benchmarker.py run 'sum(range(1000))'

  # 基准测试一个文件
  python benchmarker.py run myscript.py

  # 对比优化前后
  python benchmarker.py compare 'old_impl()' 'new_impl()'

  # 作为模块导入
  from benchmarker import Benchmark, compare

依赖: 无（仅需 Python 标准库）
"""

import argparse
import importlib.util
import json
import math
import sys
import textwrap
import time
import timeit
from dataclasses import dataclass, field
from statistics import mean, median, stdev
from typing import Callable, Optional


# ========== 统计数据类 ==========

@dataclass
class BenchmarkResult:
    """一次基准测试的完整结果"""
    name: str
    samples: list[float]  # 每次运行的耗时（秒）
    runs: int
    warmup: int
    setup: str = ""
    unit: str = "s"

    # 计算属性
    _computed: dict = field(default_factory=dict, repr=False)

    def __post_init__(self):
        self._compute()

    def _compute(self):
        if not self.samples:
            self._computed = {"error": "no samples"}
            return

        n = len(self.samples)
        avg = mean(self.samples)
        med = median(self.samples)
        std = stdev(self.samples) if n > 1 else 0.0
        min_v = min(self.samples)
        max_v = max(self.samples)
        p25 = sorted(self.samples)[int(n * 0.25)]
        p75 = sorted(self.samples)[int(n * 0.75)]
        p95 = sorted(self.samples)[int(n * 0.95)]
        p99 = sorted(self.samples)[int(n * 0.99)]

        # 置信区间 (95% CI, 使用 t-distribution 近似)
        ci_bounds = (0.0, 0.0)
        if n > 1 and std > 0:
            # z-score for 95%: 1.96 (large sample approximation)
            margin = 1.96 * std / math.sqrt(n)
            ci_bounds = (avg - margin, avg + margin)

        # 变异系数 (CV): 标准差/均值 × 100%
        cv = (std / avg * 100) if avg > 0 else 0.0

        self._computed = {
            "n": n,
            "mean": avg,
            "median": med,
            "std": std,
            "min": min_v,
            "max": max_v,
            "p25": p25,
            "p75": p75,
            "p95": p95,
            "p99": p99,
            "ci_95_lower": ci_bounds[0],
            "ci_95_upper": ci_bounds[1],
            "cv_percent": cv,
        }

    @property
    def mean(self) -> float:
        return self._computed.get("mean", 0.0)

    @property
    def std(self) -> float:
        return self._computed.get("std", 0.0)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "runs": self.runs,
            "warmup": self.warmup,
            "setup": self.setup,
            "unit": self.unit,
            "stats": self._computed.copy(),
            "samples": self.samples,
        }

    def summary_line(self) -> str:
        """一行摘要"""
        s = self._computed
        cv = s.get("cv_percent", 0)
        ci_low = s.get("ci_95_lower", 0)
        ci_high = s.get("ci_95_upper", 0)
        unit = self.unit
        return (
            f"{self.name:>20}  "
            f"mean={s['mean']:.4f}{unit}  "
            f"median={s['median']:.4f}{unit}  "
            f"std={s['std']:.4f}{unit}  "
            f"cv={cv:.1f}%  "
            f"95%CI=[{ci_low:.4f},{ci_high:.4f}]  "
            f"n={s['n']}"
        )

    def to_markdown_report(self, title: str = "性能基准测试报告") -> str:
        """生成符合 SOP 格式的 Markdown 评审报告"""
        s = self._computed
        lines = []
        lines.append(f"## ⚡ {title}")
        lines.append("")
        lines.append(f"**测试对象**: `{self.name}`")
        lines.append(f"**运行次数**: {self.runs} 次（预热 {self.warmup} 次）")
        lines.append(f"**设置**: `{self.setup or '(无)'}`")
        lines.append("")

        # 统计摘要表
        lines.append("### 统计摘要")
        lines.append("")
        lines.append("| 指标 | 值 | 单位 |")
        lines.append("|------|-----|------|")
        lines.append(f"| 样本量 | {s['n']} | - |")
        lines.append(f"| 均值 | {s['mean']:.6f} | {self.unit} |")
        lines.append(f"| 中位数 | {s['median']:.6f} | {self.unit} |")
        lines.append(f"| 标准差 | {s['std']:.6f} | {self.unit} |")
        lines.append(f"| 最小值 | {s['min']:.6f} | {self.unit} |")
        lines.append(f"| 最大值 | {s['max']:.6f} | {self.unit} |")
        lines.append(f"| P25 | {s['p25']:.6f} | {self.unit} |")
        lines.append(f"| P75 | {s['p75']:.6f} | {self.unit} |")
        lines.append(f"| P95 | {s['p95']:.6f} | {self.unit} |")
        lines.append(f"| P99 | {s['p99']:.6f} | {self.unit} |")
        lines.append(f"| 变异系数 (CV) | {s['cv_percent']:.2f}% | - |")
        lines.append(f"| 95% 置信区间 | [{s['ci_95_lower']:.6f}, {s['ci_95_upper']:.6f}] | {self.unit} |")
        lines.append("")

        # 结论
        lines.append("### 结论")
        lines.append("")
        if s['cv_percent'] < 5:
            lines.append("✅ **稳定性良好** — 变异系数 < 5%，测试结果可靠。")
        elif s['cv_percent'] < 15:
            lines.append("🔶 **稳定性一般** — 变异系数 5%~15%，建议增加样本量。")
        else:
            lines.append("❌ **波动较大** — 变异系数 > 15%，结果可能不可靠。建议排查干扰因素后重测。")
        lines.append("")

        # 原始数据
        lines.append("### 原始样本")
        lines.append("")
        lines.append(f"```")
        for i, val in enumerate(self.samples):
            lines.append(f"  Run {i+1:4d}: {val:.6f}{self.unit}")
        lines.append("```")
        lines.append("")

        return "\n".join(lines)


@dataclass
class ComparisonResult:
    """对比基准测试结果"""
    baseline: BenchmarkResult
    candidate: BenchmarkResult
    improvement_pct: float = 0.0
    is_significant: bool = False

    def __post_init__(self):
        b = self.baseline.mean
        c = self.candidate.mean
        if b > 0:
            self.improvement_pct = (b - c) / b * 100

        # 统计显著性: 均值差 > 2 × 联合标准误差
        se_b = self.baseline.std / math.sqrt(self.baseline._computed.get("n", 1)) if self.baseline.std > 0 else 0
        se_c = self.candidate.std / math.sqrt(self.candidate._computed.get("n", 1)) if self.candidate.std > 0 else 0
        pooled_se = math.sqrt(se_b**2 + se_c**2) if (se_b > 0 or se_c > 0) else 0
        self.is_significant = pooled_se > 0 and abs(b - c) > 2 * pooled_se

    def to_markdown(self) -> str:
        lines = []
        lines.append("## ⚡ 性能对比报告")
        lines.append("")
        lines.append(f"### 基线: `{self.baseline.name}`")
        lines.append(f"### 候选: `{self.candidate.name}`")
        lines.append("")

        # 摘要
        lines.append("| 指标 | 基线 | 候选 | 变化 |")
        lines.append("|------|------|------|------|")
        b, c = self.baseline, self.candidate
        lines.append(f"| 均值 | {b.mean:.6f}s | {c.mean:.6f}s | {self.improvement_pct:+.2f}% |")
        lines.append(f"| 中位数 | {b._computed['median']:.6f}s | {c._computed['median']:.6f}s | - |")
        lines.append(f"| 标准差 | {b.std:.6f}s | {c.std:.6f}s | - |")
        lines.append(f"| 变异系数 | {b._computed['cv_percent']:.2f}% | {c._computed['cv_percent']:.2f}% | - |")
        lines.append(f"| 样本量 | {b._computed['n']} | {c._computed['n']} | - |")
        lines.append("")

        # 结论
        diff = abs(self.improvement_pct)
        if self.improvement_pct > 0:
            lines.append(f"✅ **候选方案比基线快 {diff:.1f}%**")
        elif self.improvement_pct < 0:
            lines.append(f"❌ **候选方案比基线慢 {diff:.1f}%**")
        else:
            lines.append("➖ **无显著差异**")

        if self.is_significant:
            lines.append("- 差异具有**统计显著性**（均值差 > 2×联合标准误差）")
        else:
            lines.append("- ⚠️ 差异**未达统计显著性**，建议增加样本量后重测")
        lines.append("")

        # 详细
        lines.append("### 基线详细")
        lines.append("")
        lines.append(b.summary_line())
        lines.append("")
        lines.append("### 候选详细")
        lines.append("")
        lines.append(c.summary_line())
        lines.append("")

        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "baseline": self.baseline.to_dict(),
            "candidate": self.candidate.to_dict(),
            "improvement_pct": self.improvement_pct,
            "is_significant": self.is_significant,
        }


# ========== 基准测试引擎 ==========

class Benchmark:
    """性能基准测试引擎"""

    def __init__(
        self,
        stmt: str,
        setup: str = "pass",
        name: Optional[str] = None,
        warmup: int = 3,
        runs: int = 10,
        global_ns: Optional[dict] = None,
    ):
        self.stmt = stmt
        self.setup = setup
        self.name = name or (stmt[:50] if len(stmt) > 50 else stmt)
        self.warmup = warmup
        self.runs = runs
        self.global_ns = global_ns or {}

    def run(self) -> BenchmarkResult:
        """执行基准测试"""
        samples = []

        # 预热
        if self.warmup > 0:
            for _ in range(self.warmup):
                timeit.timeit(
                    self.stmt,
                    setup=self.setup,
                    globals=self.global_ns,
                    number=1,
                )

        # 正式测试
        for _ in range(self.runs):
            elapsed = timeit.timeit(
                self.stmt,
                setup=self.setup,
                globals=self.global_ns,
                number=1,
            )
            samples.append(elapsed)

        return BenchmarkResult(
            name=self.name,
            samples=samples,
            runs=self.runs,
            warmup=self.warmup,
            setup=self.setup,
        )

    @staticmethod
    def run_func(
        func: Callable,
        args: tuple = (),
        kwargs: Optional[dict] = None,
        name: Optional[str] = None,
        warmup: int = 3,
        runs: int = 10,
    ) -> BenchmarkResult:
        """对可调用对象进行基准测试"""
        kwargs = kwargs or {}
        samples = []

        # 预热
        for _ in range(warmup):
            func(*args, **kwargs)

        # 正式测试
        for _ in range(runs):
            start = time.perf_counter()
            func(*args, **kwargs)
            elapsed = time.perf_counter() - start
            samples.append(elapsed)

        return BenchmarkResult(
            name=name or getattr(func, "__name__", "anonymous"),
            samples=samples,
            runs=runs,
            warmup=warmup,
        )


def compare(
    stmt_a: str,
    stmt_b: str,
    setup: str = "pass",
    name_a: Optional[str] = None,
    name_b: Optional[str] = None,
    warmup: int = 3,
    runs: int = 10,
    global_ns: Optional[dict] = None,
) -> ComparisonResult:
    """对比两个实现的性能"""
    ns = global_ns or {}

    bench_a = Benchmark(stmt_a, setup, name_a, warmup, runs, ns)
    bench_b = Benchmark(stmt_b, setup, name_b, warmup, runs, ns)

    result_a = bench_a.run()
    result_b = bench_b.run()

    return ComparisonResult(baseline=result_a, candidate=result_b)


# ========== CLI ==========

def main():
    parser = argparse.ArgumentParser(
        description="⚡ 性能基准测试工具 — 基于 discriminator_performance_benchmarker_sop",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            示例:
              benchmarker.py run 'sum(range(1000))'
              benchmarker.py run 'sorted(data)' --setup 'import random; data=[random.random() for _ in range(1000)]'
              benchmarker.py run myscript.py -n 20 -w 5 --json
              benchmarker.py compare 'list(range(1000))' '[x for x in range(1000)]'
              benchmarker.py compare 'old_impl()' 'new_impl()' --setup 'from mymod import old_impl, new_impl'
        """),
    )

    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # run 命令
    run_parser = subparsers.add_parser("run", help="执行基准测试")
    run_parser.add_argument("stmt", help="要测试的语句或脚本文件路径")
    run_parser.add_argument("-s", "--setup", default="pass", help="设置语句")
    run_parser.add_argument("-n", "--runs", type=int, default=10, help="运行次数（默认 10）")
    run_parser.add_argument("-w", "--warmup", type=int, default=3, help="预热次数（默认 3）")
    run_parser.add_argument("--name", default=None, help="测试名称")
    run_parser.add_argument("--json", action="store_true", help="JSON 输出")
    run_parser.add_argument("--indent", action="store_true", help="JSON 缩进")
    run_parser.add_argument("--report", action="store_true", help="输出详细 Markdown 报告")

    # compare 命令
    cmp_parser = subparsers.add_parser("compare", help="对比两个实现")
    cmp_parser.add_argument("stmt_a", help="基线实现")
    cmp_parser.add_argument("stmt_b", help="候选实现")
    cmp_parser.add_argument("-s", "--setup", default="pass", help="设置语句")
    cmp_parser.add_argument("--name-a", default=None, help="基线名称")
    cmp_parser.add_argument("--name-b", default=None, help="候选名称")
    cmp_parser.add_argument("-n", "--runs", type=int, default=10, help="运行次数")
    cmp_parser.add_argument("-w", "--warmup", type=int, default=3, help="预热次数")
    cmp_parser.add_argument("--json", action="store_true", help="JSON 输出")
    cmp_parser.add_argument("--indent", action="store_true", help="JSON 缩进")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return

    if args.command == "run":
        stmt = args.stmt
        # 如果 stmt 是文件路径，读取其内容
        if stmt.endswith(".py") and not stmt.startswith((" ", "'", '"')):
            try:
                with open(stmt) as f:
                    stmt = f.read()
                if not args.name:
                    args.name = f"file:{stmt}"
            except FileNotFoundError:
                pass  # 不是文件，当作表达式

        bench = Benchmark(
            stmt=stmt,
            setup=args.setup,
            name=args.name,
            warmup=args.warmup,
            runs=args.runs,
        )

        result = bench.run()

        if args.json:
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2 if args.indent else None))
        elif args.report:
            print(result.to_markdown_report())
        else:
            print(result.summary_line())

    elif args.command == "compare":
        stmt_a, stmt_b = args.stmt_a, args.stmt_b

        cmp_result = compare(
            stmt_a=stmt_a,
            stmt_b=stmt_b,
            setup=args.setup,
            name_a=args.name_a,
            name_b=args.name_b,
            warmup=args.warmup,
            runs=args.runs,
        )

        if args.json:
            print(json.dumps(cmp_result.to_dict(), ensure_ascii=False, indent=2 if args.indent else None))
        else:
            print(cmp_result.to_markdown())


if __name__ == "__main__":
    main()
