#!/usr/bin/env python3
"""Performance Metrics Collector"""
import time, logging
logging.basicConfig(level=logging.INFO)

class PerformanceMetrics:
    def __init__(self):
        self.metrics = {}

    def log(self, name, value, unit="ms"):
        self.metrics.setdefault(name, []).append((time.time(), value, unit))

    def summary(self):
        s = {}
        for k, vs in self.metrics.items():
            vals = [v for _, v, _ in vs]
            s[k] = {"count": len(vals), "avg": sum(vals)/len(vals), "min": min(vals), "max": max(vals)}
        return s

    def save_report(self, path="benchmark_report.md"):
        s = self.summary()
        lines = ["# Benchmark Report\n\n| Metric | Count | Avg | Min | Max |", "|---|---|---|---|---|"]
        for k, v in s.items():
            lines.append(f"| {k} | {v['count']} | {v['avg']:.2f} | {v['min']:.2f} | {v['max']:.2f} |")
        with open(path, 'w') as f: f.write("\n".join(lines))
        logging.info(f"Report saved to {path}")

if __name__ == "__main__":
    pm = PerformanceMetrics()
    pm.log("latency", 12.5)
    pm.log("latency", 15.3)
    pm.log("throughput", 100)
    pm.save_report()
