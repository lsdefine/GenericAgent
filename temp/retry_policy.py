#!/usr/bin/env python3
"""Retry Policy - Exponential backoff with jitter and configurable retry strategies"""
import time
import random
import functools
from typing import Callable, Any, Optional, Tuple, Type

class RetryPolicy:
    """
    Retry execution with configurable strategies:
    - Fixed delay
    - Exponential backoff
    - Exponential backoff with jitter
    
    Features: max_retries, retryable exceptions, backoff_factor, max_delay, on_retry callback
    """
    def __init__(self, max_retries: int = 3, strategy: str = "exponential",
                 backoff_factor: float = 1.0, max_delay: float = 60.0,
                 retryable_exceptions: Optional[Tuple[Type[Exception], ...]] = None,
                 on_retry: Optional[Callable] = None):
        self.max_retries = max_retries
        self.strategy = strategy
        self.backoff_factor = backoff_factor
        self.max_delay = max_delay
        self.retryable_exceptions = retryable_exceptions or (Exception,)
        self.on_retry = on_retry
    
    def calculate_delay(self, attempt: int) -> float:
        if self.strategy == "fixed":
            return self.backoff_factor
        elif self.strategy == "exponential":
            delay = self.backoff_factor * (2 ** attempt)
            return min(delay, self.max_delay)
        elif self.strategy == "jitter":
            delay = self.backoff_factor * (2 ** attempt)
            delay = min(delay, self.max_delay)
            return random.uniform(0, delay)
        return self.backoff_factor
    
    def execute(self, func: Callable, *args, **kwargs) -> Any:
        last_exception = None
        for attempt in range(self.max_retries + 1):
            try:
                return func(*args, **kwargs)
            except self.retryable_exceptions as e:
                last_exception = e
                if attempt < self.max_retries:
                    delay = self.calculate_delay(attempt)
                    if self.on_retry:
                        self.on_retry(attempt, e, delay)
                    if delay > 0:
                        time.sleep(delay)
        raise last_exception
    
    def decorate(self, func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return self.execute(func, *args, **kwargs)
        return wrapper


if __name__ == "__main__":
    attempts = []
    
    def flaky_service():
        attempts.append(1)
        if len(attempts) < 3:
            raise ConnectionError(f"Attempt {len(attempts)} failed")
        return "success"
    
    retry_log = []
    def on_retry(attempt, error, delay):
        retry_log.append(f"Retry {attempt}: {error}, delay={delay:.2f}s")
    
    policy = RetryPolicy(
        max_retries=3,
        strategy="jitter",
        backoff_factor=0.1,
        retryable_exceptions=(ConnectionError,),
        on_retry=on_retry
    )
    
    result = policy.execute(flaky_service)
    print(f"Result: {result}")
    print(f"Attempts: {len(attempts)}")
    print(f"Retry log: {retry_log}")
    
    # Test decorator
    @policy.decorate
    def another_flaky():
        attempts.append(1)
        if len(attempts) < 5:
            raise ValueError("Still failing")
        return "decorated success"
    
    try:
        another_flaky()
    except ValueError as e:
        print(f"Exhausted retries: {e}")
    
    print("Retry policy ready.")
