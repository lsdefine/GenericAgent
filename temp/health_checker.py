#!/usr/bin/env python3
"""Health Checker - Service health monitoring with ping, TCP, HTTP checks"""
import time
import threading
from typing import Callable, Dict, Optional, List
from enum import Enum

class HealthStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"

class HealthCheck:
    def __init__(self, name: str, check_fn: Callable, interval: float = 30.0,
                 timeout: float = 5.0, unhealthy_threshold: int = 3):
        self.name = name
        self.check_fn = check_fn
        self.interval = interval
        self.timeout = timeout
        self.unhealthy_threshold = unhealthy_threshold
        self.status = HealthStatus.HEALTHY
        self.consecutive_failures = 0
        self.last_check = None
        self.last_error = None
        self._stop_event = threading.Event()
        self._thread = None
    
    def run_check(self) -> bool:
        try:
            result = self.check_fn()
            if result:
                self.consecutive_failures = 0
                self.status = HealthStatus.HEALTHY
            else:
                self.consecutive_failures += 1
                if self.consecutive_failures >= self.unhealthy_threshold:
                    self.status = HealthStatus.UNHEALTHY
                else:
                    self.status = HealthStatus.DEGRADED
            return result
        except Exception as e:
            self.consecutive_failures += 1
            self.last_error = str(e)
            if self.consecutive_failures >= self.unhealthy_threshold:
                self.status = HealthStatus.UNHEALTHY
            else:
                self.status = HealthStatus.DEGRADED
            return False
    
    def get_stats(self) -> dict:
        return {
            "name": self.name, "status": self.status.value,
            "failures": self.consecutive_failures, "last_error": self.last_error
        }

class HealthChecker:
    def __init__(self):
        self.checks: Dict[str, HealthCheck] = {}
        self._lock = threading.Lock()
    
    def add_check(self, check: HealthCheck):
        self.checks[check.name] = check
    
    def check_all(self) -> Dict[str, dict]:
        results = {}
        for name, check in self.checks.items():
            check.run_check()
            results[name] = check.get_stats()
        return results
    
    def overall_status(self) -> str:
        if not self.checks:
            return "healthy"
        statuses = [c.status for c in self.checks.values()]
        if any(s == HealthStatus.UNHEALTHY for s in statuses):
            return "unhealthy"
        if any(s == HealthStatus.DEGRADED for s in statuses):
            return "degraded"
        return "healthy"
    
    def get_report(self) -> dict:
        return {"overall": self.overall_status(), "checks": self.check_all()}


if __name__ == "__main__":
    call_count = 0
    def db_check():
        global call_count
        call_count += 1
        return call_count < 4
    
    checker = HealthChecker()
    checker.add_check(HealthCheck("database", db_check, unhealthy_threshold=3))
    checker.add_check(HealthCheck("cache", lambda: True))
    
    # First 3 checks - should pass then degrade
    for i in range(4):
        report = checker.get_report()
        print(f"Check {i+1}: overall={report['overall']}, db={report['checks']['database']['status']}")
        time.sleep(0.01)
    
    print("Health checker ready.")
