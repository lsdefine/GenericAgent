#!/usr/bin/env python3
"""
Auto-Healing & Self-Recovery System for GenericAgent
自愈系统: 进程监控、异常恢复、资源回收、状态回滚
支持: 心跳检测、优雅重启、故障转移、自动清理
"""

import os
import sys
import time
import signal
import json
import logging
import subprocess
import psutil
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

class HealthCheck:
    def __init__(self, name: str, check_fn: Callable, interval: int = 30, max_failures: int = 3):
        self.name = name
        self.check_fn = check_fn
        self.interval = interval
        self.max_failures = max_failures
        self.consecutive_failures = 0
        self.last_check = 0
        self.last_status = 'unknown'

class AutoHealer:
    def __init__(self, config_file: str = "healing_config.json"):
        self.checks: Dict[str, HealthCheck] = {}
        self.actions: Dict[str, Callable] = {}
        self.is_running = False
        self._thread = None
        self.event_log: List[Dict] = []
        self.config_file = config_file
        self._load_config()
    
    def _load_config(self):
        if os.path.exists(self.config_file):
            with open(self.config_file) as f:
                config = json.load(f)
            for check_name, check_cfg in config.get('checks', {}).items():
                self._register_from_config(check_name, check_cfg)
    
    def _register_from_config(self, name: str, cfg: Dict):
        check_type = cfg.get('type', 'process')
        if check_type == 'process':
            def check_proc():
                return self._check_process(cfg.get('name', ''), cfg.get('pattern', ''))
            self.register_check(name, check_proc, cfg.get('interval', 30), cfg.get('max_failures', 3))
            if cfg.get('action') == 'restart':
                self.register_action(name, lambda: self._restart_process(cfg.get('command', '')))
    
    def _check_process(self, name: str, pattern: str) -> bool:
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                cmdline = ' '.join(proc.info.get('cmdline', []) or [])
                if pattern and pattern.lower() in cmdline.lower():
                    return True
                if name and proc.info.get('name', '') == name:
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return False
    
    def _restart_process(self, command: str) -> bool:
        try:
            subprocess.Popen(command, shell=True, start_new_session=True)
            logger.info(f"Restarted: {command}")
            return True
        except Exception as e:
            logger.error(f"Restart failed: {e}")
            return False
    
    def register_check(self, name: str, check_fn: Callable, interval: int = 30, max_failures: int = 3):
        self.checks[name] = HealthCheck(name, check_fn, interval, max_failures)
    
    def register_action(self, name: str, action_fn: Callable):
        self.actions[name] = action_fn
    
    def cleanup_resources(self, max_memory_mb: int = 1024, max_open_files: int = 500):
        current = psutil.Process(os.getpid())
        mem_mb = current.memory_info().rss / 1024 / 1024
        open_files = len(current.open_files())
        
        if mem_mb > max_memory_mb:
            self._log_event("memory_cleanup", f"Memory {mem_mb:.0f}MB > {max_memory_mb}MB, triggering GC")
            import gc
            gc.collect()
        
        if open_files > max_open_files:
            self._log_event("fd_cleanup", f"Open files {open_files} > {max_open_files}")
        
        return {'memory_mb': round(mem_mb, 1), 'open_files': open_files}
    
    def _log_event(self, event_type: str, message: str):
        event = {
            'type': event_type,
            'message': message,
            'timestamp': datetime.now().isoformat()
        }
        self.event_log.append(event)
        logger.info(f"[Healing] {event_type}: {message}")
    
    def _run_checks(self):
        while self.is_running:
            for name, check in self.checks.items():
                now = time.time()
                if now - check.last_check < check.interval:
                    continue
                
                check.last_check = now
                try:
                    healthy = check.check_fn()
                    check.last_status = 'healthy' if healthy else 'unhealthy'
                    if healthy:
                        check.consecutive_failures = 0
                    else:
                        check.consecutive_failures += 1
                        self._log_event("health_check_failed", f"{name} failed ({check.consecutive_failures}/{check.max_failures})")
                        
                        if check.consecutive_failures >= check.max_failures:
                            if name in self.actions:
                                self._log_event("auto_healing", f"Triggering healing action for {name}")
                                try:
                                    self.actions[name]()
                                    check.consecutive_failures = 0
                                except Exception as e:
                                    self._log_event("healing_failed", f"Action for {name} failed: {e}")
                            else:
                                self._log_event("no_action", f"No healing action registered for {name}")
                except Exception as e:
                    self._log_event("check_error", f"Check {name} error: {e}")
            
            time.sleep(5)
    
    def start(self, daemon: bool = True):
        self.is_running = True
        self._thread = threading.Thread(target=self._run_checks, daemon=daemon)
        self._thread.start()
        logger.info("AutoHealer started")
    
    def stop(self):
        self.is_running = False
        if self._thread:
            self._thread.join(timeout=10)
        logger.info("AutoHealer stopped")
    
    def get_status(self) -> Dict:
        return {
            'running': self.is_running,
            'checks': {n: {'status': c.last_status, 'failures': c.consecutive_failures} for n, c in self.checks.items()},
            'event_count': len(self.event_log),
            'recent_events': self.event_log[-10:]
        }
    
    def export_log(self, path: str = "healing_log.json"):
        with open(path, 'w') as f:
            json.dump(self.event_log, f, indent=2)

if __name__ == '__main__':
    healer = AutoHealer()
    
    # Example: monitor a python process
    healer.register_check("python_main", lambda: healer._check_process('', 'python'), interval=10, max_failures=2)
    
    print("=== AutoHealer Status ===")
    status = healer.get_status()
    print(json.dumps(status, indent=2, ensure_ascii=False))
    
    print("\n=== Resource Check ===")
    resources = healer.cleanup_resources()
    print(json.dumps(resources, indent=2))
    
    print("\nStarting healer daemon (5s demo)...")
    healer.start()
    time.sleep(5)
    healer.stop()
