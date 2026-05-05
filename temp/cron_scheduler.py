#!/usr/bin/env python3
"""Cron Scheduler - Cron expression parser with timezone support and concurrency control"""
import time
import threading
from typing import Callable, Dict, List, Optional
from datetime import datetime
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

class CronExpression:
    """Parse standard cron expressions (minute hour day month weekday)"""
    
    def __init__(self, expression: str):
        parts = expression.strip().split()
        if len(parts) != 5:
            raise ValueError(f"Invalid cron expression: {expression}")
        self.minute = self._parse_field(parts[0], 0, 59)
        self.hour = self._parse_field(parts[1], 0, 23)
        self.day = self._parse_field(parts[2], 1, 31)
        self.month = self._parse_field(parts[3], 1, 12)
        self.weekday = self._parse_field(parts[4], 0, 6)  # 0=Monday
        self.expression = expression
    
    @staticmethod
    def _parse_field(field: str, min_val: int, max_val: int) -> set:
        if field == "*":
            return set(range(min_val, max_val + 1))
        values = set()
        for part in field.split(","):
            if "/" in part:
                base, step = part.split("/", 1)
                start = min_val if base == "*" else int(base)
                step = int(step)
                values.update(range(start, max_val + 1, step))
            elif "-" in part:
                start, end = map(int, part.split("-", 1))
                values.update(range(start, end + 1))
            else:
                values.add(int(part))
        return values
    
    def matches(self, dt: datetime) -> bool:
        return (dt.minute in self.minute and
                dt.hour in self.hour and
                dt.day in self.day and
                dt.month in self.month and
                dt.weekday() in self.weekday)  # weekday() returns 0=Monday


class CronJob:
    def __init__(self, name: str, cron: str, handler: Callable, timezone: str = "UTC"):
        self.name = name
        self.cron = CronExpression(cron)
        self.handler = handler
        self.timezone = ZoneInfo(timezone)
        self.enabled = True
        self.last_run = None
        self.run_count = 0
    
    def should_run(self, dt: datetime) -> bool:
        if not self.enabled:
            return False
        dt_tz = dt.astimezone(self.timezone)
        if self.last_run and dt_tz.date() == self.last_run.date() and dt_tz.hour == self.last_run.hour and dt_tz.minute == self.last_run.minute:
            return False
        return self.cron.matches(dt_tz)
    
    def execute(self):
        try:
            self.handler()
            self.last_run = datetime.now(self.timezone)
            self.run_count += 1
        except Exception as e:
            print(f"Job {self.name} failed: {e}")


class CronScheduler:
    """Scheduler with timezone support and concurrency control"""
    
    def __init__(self, max_concurrent: int = 5):
        self.jobs: Dict[str, CronJob] = {}
        self.max_concurrent = max_concurrent
        self._running = 0
        self._lock = threading.Lock()
        self._thread = None
        self._stop_event = threading.Event()
    
    def add_job(self, name: str, cron: str, handler: Callable, timezone: str = "UTC"):
        self.jobs[name] = CronJob(name, cron, handler, timezone)
    
    def remove_job(self, name: str):
        self.jobs.pop(name, None)
    
    def enable_job(self, name: str):
        if name in self.jobs:
            self.jobs[name].enabled = True
    
    def disable_job(self, name: str):
        if name in self.jobs:
            self.jobs[name].enabled = False
    
    def tick(self):
        """Check and run due jobs (call periodically)"""
        now = datetime.now()
        for job in self.jobs.values():
            if job.should_run(now):
                with self._lock:
                    if self._running >= self.max_concurrent:
                        continue
                    self._running += 1
                
                def run_job(j=job):
                    try:
                        j.execute()
                    finally:
                        with self._lock:
                            self._running -= 1
                threading.Thread(target=run_job, daemon=True).start()
    
    def get_stats(self) -> Dict:
        return {
            name: {
                "cron": job.cron.expression,
                "enabled": job.enabled,
                "run_count": job.run_count,
                "last_run": str(job.last_run) if job.last_run else None
            }
            for name, job in self.jobs.items()
        }


if __name__ == "__main__":
    scheduler = CronScheduler(max_concurrent=3)
    
    results = []
    def task1():
        results.append("task1 ran")
        print("Task 1 executed!")
    
    def task2():
        results.append("task2 ran")
        print("Task 2 executed!")
    
    # Add jobs
    scheduler.add_job("every_minute", "* * * * *", task1)
    scheduler.add_job("noon_daily", "0 12 * * *", task2, timezone="Asia/Shanghai")
    
    print(f"Jobs added: {list(scheduler.jobs.keys())}")
    
    # Test tick (should trigger every_minute job)
    scheduler.tick()
    time.sleep(0.1)
    print(f"Results after tick: {results}")
    
    # Test disable
    scheduler.disable_job("every_minute")
    scheduler.tick()
    print(f"After disable: {len(results)} runs (should still be 1)")
    
    print(f"Stats: {scheduler.get_stats()}")
    print("Cron scheduler ready.")
