#!/usr/bin/env python3
"""Performance Profiler - Function-level profiling, memory analysis, and hot spot detection"""
import time
import functools
import tracemalloc
from typing import Dict, List, Optional, Callable
from datetime import datetime

class Profiler:
    """Function-level performance profiler"""
    
    def __init__(self):
        self.stats = {}
        self.memory_stats = {}
        tracemalloc.start()
    
    def profile(self, func: Callable) -> Callable:
        """Decorator to profile a function"""
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            func_name = func.__name__
            if func_name not in self.stats:
                self.stats[func_name] = {"calls": 0, "total_time": 0, "avg_time": 0}
            
            start = time.perf_counter()
            tracemalloc.clear_traces()
            result = func(*args, **kwargs)
            elapsed = time.perf_counter() - start
            
            current, peak = tracemalloc.get_traced_memory()
            self.stats[func_name]["calls"] += 1
            self.stats[func_name]["total_time"] += elapsed
            self.stats[func_name]["avg_time"] = self.stats[func_name]["total_time"] / self.stats[func_name]["calls"]
            
            if func_name not in self.memory_stats:
                self.memory_stats[func_name] = {"peak_memory": 0}
            self.memory_stats[func_name]["peak_memory"] = max(
                self.memory_stats[func_name].get("peak_memory", 0), peak
            )
            
            return result
        return wrapper
    
    def get_hotspots(self, top_n: int = 5) -> List[Dict]:
        """Get top N hot spots by total execution time"""
        sorted_stats = sorted(
            self.stats.items(), key=lambda x: x[1]["total_time"], reverse=True
        )
        return [
            {
                "name": name,
                "total_time": s["total_time"],
                "calls": s["calls"],
                "avg_time": s["avg_time"],
                "peak_memory_mb": self.memory_stats.get(name, {}).get("peak_memory", 0) / 1024 / 1024
            }
            for name, s in sorted_stats[:top_n]
        ]
    
    def generate_report(self) -> str:
        """Generate profiling report"""
        hotspots = self.get_hotspots()
        lines = [
            "# Performance Profile Report",
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "## Hot Spots",
            "| Function | Total Time (s) | Calls | Avg Time (s) | Peak Memory (MB) |",
            "|---|---|---|---|---|",
        ]
        for h in hotspots:
            lines.append(f"| {h['name']} | {h['total_time']:.4f} | {h['calls']} | {h['avg_time']:.4f} | {h['peak_memory_mb']:.2f} |")
        
        report = "\n".join(lines)
        filename = f"profiler_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        with open(filename, 'w') as f:
            f.write(report)
        return filename
    
    def reset(self):
        """Reset profiler stats"""
        self.stats.clear()
        self.memory_stats.clear()


if __name__ == "__main__":
    profiler = Profiler()
    
    @profiler.profile
    def slow_function(n):
        time.sleep(0.1)
        return sum(range(n))
    
    @profiler.profile
    def memory_intensive(n):
        data = [0] * n
        return len(data)
    
    @profiler.profile
    def fast_function():
        return 42
    
    # Run tests
    for _ in range(3):
        slow_function(1000)
    for _ in range(5):
        memory_intensive(100000)
    for _ in range(10):
        fast_function()
    
    report = profiler.generate_report()
    print(f"Report: {report}")
    
    hotspots = profiler.get_hotspots()
    print(f"\nTop hot spots:")
    for h in hotspots:
        print(f"  {h['name']}: {h['total_time']:.4f}s, {h['calls']} calls")
    
    # Cleanup
    for f in os.listdir("."):
        if f.startswith("profiler_report_"):
            os.remove(f)
    print("Profiler ready.")
