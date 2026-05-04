#!/usr/bin/env python3
"""
Performance Benchmarking Suite for GenericAgent
自动化性能基准测试: 脚本执行/内存/IO/网络延迟
支持: 多轮测试、基线对比、趋势分析、报告导出
"""

import os
import sys
import time
import json
import psutil
import subprocess
import statistics
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional, Callable
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

class BenchmarkResult:
    def __init__(self, name: str, unit: str):
        self.name = name
        self.unit = unit
        self.values = []
        self.timestamps = []
    
    def add(self, value: float):
        self.values.append(value)
        self.timestamps.append(time.time())
    
    @property
    def mean(self): return statistics.mean(self.values) if self.values else 0
    @property
    def median(self): return statistics.median(self.values) if self.values else 0
    @property
    def stdev(self): return statistics.stdev(self.values) if len(self.values) > 1 else 0
    @property
    def min(self): return min(self.values) if self.values else 0
    @property
    def max(self): return max(self.values) if self.values else 0
    @property
    def p95(self):
        if not self.values: return 0
        s = sorted(self.values)
        return s[int(len(s) * 0.95)]
    
    def to_dict(self):
        return {
            'name': self.name, 'unit': self.unit,
            'mean': round(self.mean, 3), 'median': round(self.median, 3),
            'stdev': round(self.stdev, 3), 'min': round(self.min, 3),
            'max': round(self.max, 3), 'p95': round(self.p95, 3),
            'samples': len(self.values)
        }

class BenchmarkSuite:
    def __init__(self, baseline_file: str = "benchmark_baseline.json"):
        self.results: Dict[str, BenchmarkResult] = {}
        self.baseline_file = baseline_file
        self.baseline = self._load_baseline()
        self.process = psutil.Process(os.getpid())
    
    def _load_baseline(self) -> Dict:
        if os.path.exists(self.baseline_file):
            with open(self.baseline_file) as f:
                return json.load(f)
        return {}
    
    def save_baseline(self):
        data = {k: v.to_dict() for k, v in self.results.items()}
        with open(self.baseline_file, 'w') as f:
            json.dump(data, f, indent=2)
        logger.info(f"Baseline saved to {self.baseline_file}")
    
    def benchmark_function(self, name: str, func: Callable, args=(), kwargs={}, iterations: int = 100):
        result = BenchmarkResult(name, 'ms')
        for _ in range(iterations):
            start = time.perf_counter()
            func(*args, **kwargs)
            elapsed = (time.perf_counter() - start) * 1000
            result.add(elapsed)
        self.results[name] = result
        return result
    
    def benchmark_script(self, name: str, script_path: str, iterations: int = 10):
        result = BenchmarkResult(name, 's')
        for _ in range(iterations):
            start = time.perf_counter()
            subprocess.run([sys.executable, script_path], capture_output=True, timeout=60)
            elapsed = time.perf_counter() - start
            result.add(elapsed)
        self.results[name] = result
        return result
    
    def benchmark_io(self, name: str, size_mb: int = 10, iterations: int = 5):
        result = BenchmarkResult(name, 'MB/s')
        test_file = "_bench_test.dat"
        data = os.urandom(size_mb * 1024 * 1024)
        
        for _ in range(iterations):
            start = time.perf_counter()
            with open(test_file, 'wb') as f:
                f.write(data)
            with open(test_file, 'rb') as f:
                f.read()
            elapsed = time.perf_counter() - start
            throughput = (size_mb * 2) / elapsed
            result.add(throughput)
            os.remove(test_file)
        
        self.results[name] = result
        return result
    
    def benchmark_memory(self, name: str = "memory_snapshot"):
        result = BenchmarkResult(name, 'MB')
        mem_info = self.process.memory_info()
        result.add(mem_info.rss / 1024 / 1024)
        self.results[name] = result
        return result
    
    def compare_with_baseline(self) -> Dict[str, Dict]:
        comparisons = {}
        for name, result in self.results.items():
            if name in self.baseline:
                bl = self.baseline[name]
                diff = result.mean - bl.get('mean', 0)
                pct = (diff / bl['mean'] * 100) if bl['mean'] else 0
                comparisons[name] = {
                    'current': result.mean,
                    'baseline': bl['mean'],
                    'diff': round(diff, 3),
                    'change_pct': round(pct, 2),
                    'status': 'REGRESSION' if pct > 10 else 'IMPROVEMENT' if pct < -10 else 'STABLE'
                }
        return comparisons
    
    def generate_report(self) -> Dict:
        report = {
            'timestamp': datetime.now().isoformat(),
            'benchmarks': {k: v.to_dict() for k, v in self.results.items()},
            'comparison': self.compare_with_baseline()
        }
        return report
    
    def export_report(self, path: str = "benchmark_report.json"):
        report = self.generate_report()
        with open(path, 'w') as f:
            json.dump(report, f, indent=2)
        logger.info(f"Report exported to {path}")
        return report

if __name__ == '__main__':
    suite = BenchmarkSuite()
    
    print("=== Running Benchmarks ===")
    
    # Function benchmark
    def sample_work():
        total = 0
        for i in range(1000):
            total += i * 2
        return total
    
    r1 = suite.benchmark_function("sample_work", sample_work, iterations=200)
    print(f"sample_work: {r1.mean:.2f}ms (p95: {r1.p95:.2f}ms)")
    
    # Memory benchmark
    r2 = suite.benchmark_memory()
    print(f"Memory: {r2.mean:.1f}MB RSS")
    
    # IO benchmark (smaller for speed)
    r3 = suite.benchmark_io("io_test", size_mb=1, iterations=3)
    print(f"IO: {r3.mean:.1f} MB/s")
    
    print("\n=== Full Report ===")
    report = suite.export_report()
    print(json.dumps(report['benchmarks'], indent=2))
    
    if report['comparison']:
        print("\n=== Baseline Comparison ===")
        print(json.dumps(report['comparison'], indent=2))
    
    # Save as new baseline
    suite.save_baseline()
