#!/usr/bin/env python3
"""Rate Limiter - Token Bucket and Sliding Window algorithms"""
import time
import threading
from typing import Optional

class TokenBucket:
    def __init__(self, rate: float, capacity: float):
        self.rate = rate
        self.capacity = capacity
        self.tokens = capacity
        self.last_refill = time.monotonic()
        self._lock = threading.Lock()
    
    def consume(self, tokens: float = 1.0) -> bool:
        with self._lock:
            self._refill()
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False
    
    def _refill(self):
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last_refill = now

class SlidingWindowLimiter:
    def __init__(self, max_requests: int, window_seconds: float):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests = []
        self._lock = threading.Lock()
    
    def allow(self) -> bool:
        with self._lock:
            now = time.monotonic()
            cutoff = now - self.window_seconds
            self._requests = [t for t in self._requests if t > cutoff]
            if len(self._requests) < self.max_requests:
                self._requests.append(now)
                return True
            return False

class RateLimiter:
    def __init__(self, name: str, algorithm: str = "token_bucket",
                 rate: float = 10.0, capacity: float = 10.0,
                 max_requests: int = 100, window_seconds: float = 60.0):
        self.name = name
        if algorithm == "token_bucket":
            self._limiter = TokenBucket(rate, capacity)
            self._algorithm = "token_bucket"
        else:
            self._limiter = SlidingWindowLimiter(max_requests, window_seconds)
            self._algorithm = "sliding_window"
    
    def allow(self, tokens: float = 1.0) -> bool:
        if self._algorithm == "token_bucket":
            return self._limiter.consume(tokens)
        return self._limiter.allow()
    
    def get_stats(self) -> dict:
        if isinstance(self._limiter, TokenBucket):
            return {"algorithm": "token_bucket", "tokens": round(self._limiter.tokens, 2), "rate": self._limiter.rate}
        return {"algorithm": "sliding_window", "active_requests": len(self._limiter._requests)}


if __name__ == "__main__":
    tb = RateLimiter("tb", algorithm="token_bucket", rate=10, capacity=5)
    allowed = 0
    for _ in range(8):
        if tb.allow():
            allowed += 1
    print(f"Token bucket: {allowed}/8 allowed (capacity=5)")
    
    sw = RateLimiter("sw", algorithm="sliding_window", max_requests=3, window_seconds=1.0)
    allowed = 0
    for _ in range(5):
        if sw.allow():
            allowed += 1
    print(f"Sliding window: {allowed}/5 allowed (max=3)")
    
    print("Rate limiter ready.")
