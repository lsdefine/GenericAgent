#!/usr/bin/env python3
"""Memory Profiler"""
import tracemalloc, logging
logging.basicConfig(level=logging.INFO)

class MemoryProfiler:
    def __init__(self):
        self.snapshots = []

    def start(self):
        tracemalloc.start()

    def snapshot(self, label=""):
        current, peak = tracemalloc.get_traced_memory()
        snap = {"label": label, "current_kb": current/1024, "peak_kb": peak/1024}
        self.snapshots.append(snap)
        logging.info(f"  {label}: current={snap['current_kb']:.1f}KB, peak={snap['peak_kb']:.1f}KB")
        return snap

    def stop(self):
        tracemalloc.stop()

    def diff(self, idx1, idx2):
        if idx1 >= len(self.snapshots) or idx2 >= len(self.snapshots):
            return None
        return self.snapshots[idx2]["current_kb"] - self.snapshots[idx1]["current_kb"]

if __name__ == "__main__":
    mp = MemoryProfiler()
    mp.start()
    mp.snapshot("init")
    data = [i**2 for i in range(10000)]
    mp.snapshot("after_computation")
    mp.stop()
