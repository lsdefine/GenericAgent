#!/usr/bin/env python3
"""
Distributed Task Queue for GenericAgent
轻量级分布式任务队列: 支持多Worker、优先级、重试、结果持久化
无外部依赖, 基于文件/SQLite实现, 可水平扩展
"""

import os
import sys
import json
import time
import uuid
import signal
import logging
import threading
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, asdict

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

DB_FILE = "task_queue.db"

@dataclass
class Task:
    id: str
    name: str
    priority: int
    status: str
    payload: str
    result: str
    created_at: str
    started_at: str
    completed_at: str
    retry_count: int
    max_retries: int
    error: str

class TaskQueue:
    def __init__(self, db_path: str = DB_FILE):
        self.db_path = db_path
        self._handlers: Dict[str, Callable] = {}
        self._running = False
        self._init_db()
    
    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    priority INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'pending',
                    payload TEXT,
                    result TEXT,
                    created_at TEXT,
                    started_at TEXT,
                    completed_at TEXT,
                    retry_count INTEGER DEFAULT 0,
                    max_retries INTEGER DEFAULT 3,
                    error TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_status_priority ON tasks(status, priority)")
    
    def register_handler(self, task_name: str, handler: Callable):
        self._handlers[task_name] = handler
    
    def enqueue(self, name: str, payload: Any = None, priority: int = 0, max_retries: int = 3) -> str:
        task_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO tasks (id, name, priority, status, payload, created_at, max_retries) VALUES (?,?,?,?,?,?,?)",
                (task_id, name, priority, 'pending', json.dumps(payload), now, max_retries)
            )
        logger.info(f"Enqueued task {name} ({task_id[:8]}...), priority={priority}")
        return task_id
    
    def get_task(self, task_id: str) -> Optional[Dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            return dict(row) if row else None
    
    def _dequeue(self) -> Optional[Dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM tasks WHERE status='pending' ORDER BY priority DESC, created_at ASC LIMIT 1"
            ).fetchone()
            if row:
                row = dict(row)
                conn.execute(
                    "UPDATE tasks SET status='running', started_at=? WHERE id=?",
                    (datetime.now().isoformat(), row['id'])
                )
                return row
        return None
    
    def _complete_task(self, task_id: str, result: Any, error: str = None):
        now = datetime.now().isoformat()
        status = 'completed' if not error else 'failed'
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE tasks SET status=?, result=?, completed_at=?, error=? WHERE id=?",
                (status, json.dumps(result), now, error, task_id)
            )
    
    def _retry_task(self, task_id: str, error: str):
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT retry_count, max_retries FROM tasks WHERE id=?", (task_id,)).fetchone()
            if row and row[0] < row[1]:
                conn.execute(
                    "UPDATE tasks SET status='pending', retry_count=retry_count+1, error=?, started_at=NULL WHERE id=?",
                    (error, task_id)
                )
                logger.info(f"Retrying task {task_id[:8]}... (attempt {row[0]+1}/{row[1]})")
            else:
                conn.execute("UPDATE tasks SET status='failed', error=? WHERE id=?", (error, task_id))
    
    def worker_loop(self, poll_interval: float = 1.0):
        logger.info("Worker started")
        while self._running:
            task = self._dequeue()
            if not task:
                time.sleep(poll_interval)
                continue
            
            handler = self._handlers.get(task['name'])
            if not handler:
                self._complete_task(task['id'], None, error=f"No handler for {task['name']}")
                continue
            
            try:
                payload = json.loads(task['payload']) if task['payload'] else None
                result = handler(payload) if payload else handler()
                self._complete_task(task['id'], result)
                logger.info(f"Task {task['name']} ({task['id'][:8]}...) completed")
            except Exception as e:
                logger.error(f"Task {task['id'][:8]}... failed: {e}")
                self._retry_task(task['id'], str(e))
    
    def start_workers(self, num_workers: int = 2, poll_interval: float = 1.0):
        self._running = True
        self._pool = ThreadPoolExecutor(max_workers=num_workers)
        for _ in range(num_workers):
            self._pool.submit(self.worker_loop, poll_interval)
        logger.info(f"Started {num_workers} workers")
    
    def stop(self):
        self._running = False
    
    def get_stats(self) -> Dict:
        with sqlite3.connect(self.db_path) as conn:
            counts = {}
            for status in ('pending', 'running', 'completed', 'failed'):
                row = conn.execute("SELECT COUNT(*) FROM tasks WHERE status=?", (status,)).fetchone()
                counts[status] = row[0]
            return counts

if __name__ == '__main__':
    q = TaskQueue()
    
    q.register_handler("echo", lambda p: f"Echo: {p}")
    q.register_handler("compute", lambda p: sum(range(p.get('n', 100))))
    q.register_handler("fail_test", lambda p: 1/0)
    
    q.enqueue("echo", {"message": "Hello"}, priority=1)
    q.enqueue("compute", {"n": 10000}, priority=5)
    q.enqueue("fail_test", priority=0)
    
    print("=== Stats ===")
    print(json.dumps(q.get_stats(), indent=2))
    
    print("\n=== Processing (3s) ===")
    q.start_workers(num_workers=2)
    time.sleep(3)
    q.stop()
    print("Final stats:", q.get_stats())
