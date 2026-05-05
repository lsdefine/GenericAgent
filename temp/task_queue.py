#!/usr/bin/env python3
"""Async Task Queue - asyncio-based task dispatch with retry and priority support"""
import asyncio
import functools
import time
from typing import Callable, Any, Optional, Dict, List
from datetime import datetime
from enum import IntEnum

class TaskPriority(IntEnum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3

class Task:
    """Represents an async task"""
    def __init__(self, name: str, coro: Any, priority: TaskPriority = TaskPriority.NORMAL, max_retries: int = 3):
        self.name = name
        self.coro = coro
        self.priority = priority
        self.max_retries = max_retries
        self.attempts = 0
        self.created_at = datetime.now()
    
    def __lt__(self, other):
        return self.priority > other.priority  # Higher priority first

class AsyncTaskQueue:
    """Async task queue with priority and retry"""
    
    def __init__(self):
        self.queue: List[Task] = []
        self.results: Dict[str, Any] = {}
        self.errors: Dict[str, str] = {}
        self._lock = asyncio.Lock()
    
    async def enqueue(self, name: str, coro: Any, priority: TaskPriority = TaskPriority.NORMAL, max_retries: int = 3):
        """Add a task to the queue"""
        async with self._lock:
            task = Task(name, coro, priority, max_retries)
            self.queue.append(task)
            self.queue.sort()
    
    async def process_queue(self):
        """Process all tasks in priority order"""
        while self.queue:
            async with self._lock:
                task = self.queue.pop(0)
            try:
                result = await self._execute_with_retry(task)
                self.results[task.name] = result
                print(f"[OK] {task.name} completed")
            except Exception as e:
                self.errors[task.name] = str(e)
                print(f"[FAIL] {task.name}: {e}")
    
    async def _execute_with_retry(self, task: Task) -> Any:
        """Execute task with retry logic"""
        last_error = None
        for attempt in range(task.max_retries + 1):
            task.attempts = attempt
            try:
                if asyncio.iscoroutine(task.coro):
                    return await task.coro
                elif callable(task.coro):
                    result = task.coro()
                    if asyncio.iscoroutine(result):
                        return await result
                    return result
                else:
                    return task.coro
            except Exception as e:
                last_error = e
                if attempt < task.max_retries:
                    await asyncio.sleep(0.01 * (2 ** attempt))  # Backoff
        raise last_error
    
    def get_status(self) -> Dict:
        """Get queue status"""
        return {
            "pending": len(self.queue),
            "completed": len(self.results),
            "failed": len(self.errors),
            "results": self.results,
            "errors": self.errors
        }


if __name__ == "__main__":
    async def main():
        queue = AsyncTaskQueue()
        
        async def fast_task():
            return "fast"
        
        async def slow_task():
            await asyncio.sleep(0.05)
            return "slow"
        
        def failing_task():
            raise ValueError("intentional failure")
        
        await queue.enqueue("fast", fast_task(), TaskPriority.HIGH)
        await queue.enqueue("slow", slow_task(), TaskPriority.NORMAL)
        await queue.enqueue("critical", fast_task(), TaskPriority.CRITICAL)
        await queue.enqueue("failing", failing_task, max_retries=1)
        
        await queue.process_queue()
        
        status = queue.get_status()
        print(f"\nStatus: {status['completed']} completed, {status['failed']} failed")
        print("Async task queue ready.")
    
    asyncio.run(main())
