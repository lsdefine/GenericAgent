"""R216: Advanced Rate Limiter - Distributed + Fixed/Sliding Window + Sliding Log + Quota Management.
Demonstrates multiple rate limiting algorithms.
"""
import time, threading
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict
import hashlib

class FixedWindowLimiter:
    """Simple fixed window counter."""
    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.windows: Dict[str, Tuple[int, float]] = {}
        self.lock = threading.Lock()
    
    def allow(self, key: str = "default") -> bool:
        now = time.time()
        window_start = int(now / self.window_seconds) * self.window_seconds
        
        with self.lock:
            current_count, stored_start = self.windows.get(key, (0, 0))
            if stored_start != window_start:
                self.windows[key] = (1, window_start)
                return True
            if current_count < self.max_requests:
                self.windows[key] = (current_count + 1, window_start)
                return True
            return False

class SlidingLogLimiter:
    """Sliding log with exact request timestamps."""
    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.logs: Dict[str, List[float]] = defaultdict(list)
        self.lock = threading.Lock()
    
    def allow(self, key: str = "default") -> bool:
        now = time.time()
        with self.lock:
            # Remove old entries
            cutoff = now - self.window_seconds
            self.logs[key] = [t for t in self.logs[key] if t > cutoff]
            
            if len(self.logs[key]) < self.max_requests:
                self.logs[key].append(now)
                return True
            return False

class SlidingWindowCounterLimiter:
    """Approximate sliding window using weighted fixed windows."""
    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.windows: Dict[str, Tuple[int, int, float]] = {}  # (prev_count, curr_count, curr_start)
        self.lock = threading.Lock()
    
    def allow(self, key: str = "default") -> bool:
        now = time.time()
        window_start = int(now / self.window_seconds) * self.window_seconds
        prev_window_start = window_start - self.window_seconds
        
        with self.lock:
            prev_count, curr_count, stored_start = self.windows.get(key, (0, 0, 0))
            
            if stored_start == window_start:
                # Still in same window
                elapsed = now - window_start
                weight = 1 - (elapsed / self.window_seconds)
                estimated = prev_count * weight + curr_count
                if estimated < self.max_requests:
                    self.windows[key] = (prev_count, curr_count + 1, window_start)
                    return True
                return False
            else:
                # New window
                if stored_start == prev_window_start:
                    self.windows[key] = (curr_count, 1, window_start)
                else:
                    self.windows[key] = (0, 1, window_start)
                return True

@dataclass
class RateLimitResult:
    allowed: bool
    remaining: int
    reset_at: float
    limit: int

class RateLimiterManager:
    """Manages multiple rate limiters with different strategies."""
    
    def __init__(self):
        self.limiters: Dict[str, object] = {}
        self.quotas: Dict[str, int] = {}
        self.usage: Dict[str, int] = defaultdict(int)
    
    def add_limiter(self, name: str, limiter_type: str, **kwargs):
        if limiter_type == "fixed_window":
            self.limiters[name] = FixedWindowLimiter(**kwargs)
        elif limiter_type == "sliding_log":
            self.limiters[name] = SlidingLogLimiter(**kwargs)
        elif limiter_type == "sliding_window_counter":
            self.limiters[name] = SlidingWindowCounterLimiter(**kwargs)
    
    def set_quota(self, key: str, max_total: int):
        self.quotas[key] = max_total
        self.usage[key] = 0
    
    def check(self, limiter_name: str, quota_key: str = None) -> RateLimitResult:
        if quota_key and quota_key in self.quotas:
            if self.usage[quota_key] >= self.quotas[quota_key]:
                return RateLimitResult(False, 0, 0, self.quotas[quota_key])
        
        if limiter_name not in self.limiters:
            return RateLimitResult(True, 999, 0, 999)
        
        limiter = self.limiters[limiter_name]
        allowed = limiter.allow()
        
        if allowed and quota_key:
            self.usage[quota_key] += 1
        
        remaining = max(0, (self.quotas.get(quota_key, 999) - self.usage.get(quota_key, 0)) if quota_key else 999)
        return RateLimitResult(allowed, remaining, time.time() + 60, self.quotas.get(quota_key, 999))
    
    def get_usage(self, quota_key: str) -> Dict:
        return {
            "used": self.usage.get(quota_key, 0),
            "limit": self.quotas.get(quota_key, 0),
            "remaining": max(0, self.quotas.get(quota_key, 0) - self.usage.get(quota_key, 0))
        }

def run_limiter_demo():
    print("=== R216 Advanced Rate Limiter ===")
    
    manager = RateLimiterManager()
    
    # Add different limiter types
    manager.add_limiter("api_fixed", "fixed_window", max_requests=5, window_seconds=60)
    manager.add_limiter("api_sliding_log", "sliding_log", max_requests=5, window_seconds=60)
    manager.add_limiter("api_sliding_counter", "sliding_window_counter", max_requests=5, window_seconds=60)
    
    # Set quotas
    manager.set_quota("user_123", 10)
    manager.set_quota("user_456", 3)
    
    # Test fixed window
    print("1. Fixed Window (max 5):")
    results = [manager.check("api_fixed").allowed for _ in range(7)]
    print(f"   Results: {results}")
    
    # Test sliding log
    print("2. Sliding Log (max 5):")
    results = [manager.check("api_sliding_log").allowed for _ in range(7)]
    print(f"   Results: {results}")
    
    # Test sliding window counter
    print("3. Sliding Window Counter (max 5):")
    results = [manager.check("api_sliding_counter").allowed for _ in range(7)]
    print(f"   Results: {results}")
    
    # Test quota enforcement
    print("4. Quota Enforcement (user_456, limit 3):")
    results = [manager.check("api_fixed", "user_456").allowed for _ in range(5)]
    print(f"   Results: {results}")
    usage = manager.get_usage("user_456")
    print(f"   Usage: {usage}")
    
    print("\nR216 Advanced Rate Limiter ready.")

run_limiter_demo()
