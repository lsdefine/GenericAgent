#!/usr/bin/env python3
"""Benchmark Runner"""
import time, resource, logging, statistics
logging.basicConfig(level=logging.INFO)

class BenchmarkRunner:
    def __init__(self):
        self.results = []

    def measure(self, func, *args, n_runs=3, **kwargs):
        times = []
        for _ in range(n_runs):
            start = time.perf_counter()
            func(*args, **kwargs)
            elapsed = time.perf_counter() - start
            times.append(elapsed)
        return {"mean": statistics.mean(times), "min": min(times), "max": max(times), "n_runs": n_runs}

    def measure_memory(self, func, *args, **kwargs):
        mem_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        func(*args, **kwargs)
        mem_after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return {"delta_kb": mem_after - mem_before}

    def run_suite(self, suite_name, test_cases):
        logging.info(f"Running {suite_name}: {len(test_cases)} cases")
        for name, func, args, kwargs in test_cases:
            t = self.measure(func, *args, **kwargs, n_runs=2)
            m = self.measure_memory(func, *args, **kwargs)
            self.results.append({"name": name, "suite": suite_name, "time": t, "memory": m})
            logging.info(f"  {name}: {t['mean']*1000:.2f}ms, +{m['delta_kb']}KB")

    def report(self):
        return self.results

if __name__ == "__main__":
    br = BenchmarkRunner()
    def dummy(x): return sum(range(x))
    br.run_suite("baseline", [("sum_1k", dummy, [1000], {}), ("sum_100k", dummy, [100000], {})])
    print(f"Results: {len(br.results)} benchmarks")
