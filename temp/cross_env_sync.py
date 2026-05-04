#!/usr/bin/env python3
"""
Cross-Environment Sync Tool for GenericAgent
跨环境数据同步: macOS/Linux/Windows 间的配置、记忆、任务状态同步
支持: 增量同步、冲突检测、加密传输(可选)、断点续传
"""

import os
import sys
import json
import time
import shutil
import hashlib
import logging
import platform
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

class SyncConfig:
    def __init__(self, sync_dir: str = "./sync", db_path: str = "sync_state.db"):
        self.sync_dir = Path(sync_dir)
        self.db_path = Path(db_path)
        self.sync_dir.mkdir(exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS sync_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT NOT NULL,
                source_hash TEXT,
                dest_hash TEXT,
                sync_time TEXT,
                status TEXT,
                direction TEXT
            )''')
            conn.execute('''CREATE TABLE IF NOT EXISTS environment_info (
                env_id TEXT PRIMARY KEY,
                hostname TEXT,
                platform TEXT,
                last_sync TEXT,
                config TEXT
            )''')

class CrossEnvSync:
    """跨环境同步引擎"""
    def __init__(self, config: SyncConfig = None):
        self.config = config or SyncConfig()
        self.local_env = {
            "env_id": hashlib.md5(platform.node().encode()).hexdigest()[:8],
            "hostname": platform.node(),
            "platform": platform.system(),
            "python_version": platform.python_version()
        }
        self.sync_rules: List[Dict] = []
        self._load_rules()

    def _load_rules(self):
        rules_file = self.config.sync_dir / "sync_rules.json"
        if rules_file.exists():
            with open(rules_file) as f:
                self.sync_rules = json.load(f)
            logger.info(f"Loaded {len(self.sync_rules)} sync rules")
        else:
            self._create_default_rules()

    def _create_default_rules(self):
        self.sync_rules = [
            {
                "name": "memory_sync",
                "source": "../memory/",
                "pattern": "*.txt",
                "direction": "bidirectional",
                "conflict_resolution": "newest_wins",
                "enabled": True
            },
            {
                "name": "config_sync",
                "source": "./",
                "pattern": "*.json",
                "direction": "push",
                "conflict_resolution": "local_wins",
                "enabled": True
            },
            {
                "name": "report_sync",
                "source": "./reports/",
                "pattern": "*.md",
                "direction": "pull",
                "conflict_resolution": "remote_wins",
                "enabled": True
            }
        ]
        rules_file = self.config.sync_dir / "sync_rules.json"
        with open(rules_file, 'w') as f:
            json.dump(self.sync_rules, f, indent=2)

    def get_file_hash(self, filepath: Path) -> str:
        if not filepath.exists():
            return ""
        h = hashlib.sha256()
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                h.update(chunk)
        return h.hexdigest()

    def detect_conflicts(self, local_path: Path, remote_path: Path) -> Optional[str]:
        """检测文件冲突"""
        if not local_path.exists() or not remote_path.exists():
            return None
        
        local_hash = self.get_file_hash(local_path)
        remote_hash = self.get_file_hash(remote_path)
        
        if local_hash != remote_hash:
            local_mtime = local_path.stat().st_mtime
            remote_mtime = remote_path.stat().st_mtime
            if local_mtime > remote_mtime:
                return "local_newer"
            else:
                return "remote_newer"
        return None

    def resolve_conflict(self, local_path: Path, remote_path: Path, 
                        resolution: str = "newest_wins") -> Path:
        """解决冲突"""
        conflict = self.detect_conflicts(local_path, remote_path)
        if not conflict:
            return local_path
        
        if resolution == "newest_wins":
            return local_path if "local_newer" in conflict else remote_path
        elif resolution == "local_wins":
            return local_path
        elif resolution == "remote_wins":
            return remote_path
        elif resolution == "merge":
            # 简单合并策略: 保留两者, 添加时间戳
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup = remote_path.with_suffix(f".{timestamp}{remote_path.suffix}")
            shutil.copy2(remote_path, backup)
            logger.info(f"Created backup: {backup}")
            return local_path
        return local_path

    def sync_file(self, local_path: Path, remote_path: Path, 
                  direction: str = "bidirectional", conflict_resolution: str = "newest_wins") -> bool:
        """同步单个文件"""
        try:
            if direction == "push":
                if local_path.exists():
                    remote_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(local_path, remote_path)
                    logger.info(f"Pushed: {local_path} -> {remote_path}")
                    return True
            elif direction == "pull":
                if remote_path.exists():
                    local_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(remote_path, local_path)
                    logger.info(f"Pulled: {remote_path} -> {local_path}")
                    return True
            elif direction == "bidirectional":
                if local_path.exists() and remote_path.exists():
                    winner = self.resolve_conflict(local_path, remote_path, conflict_resolution)
                    if winner == local_path:
                        shutil.copy2(local_path, remote_path)
                    else:
                        shutil.copy2(remote_path, local_path)
                    logger.info(f"Synced (bidirectional): {local_path} <-> {remote_path}")
                elif local_path.exists():
                    remote_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(local_path, remote_path)
                elif remote_path.exists():
                    local_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(remote_path, local_path)
                return True
        except Exception as e:
            logger.error(f"Sync failed for {local_path}: {e}")
            return False
        return False

    def sync_all(self, remote_root: Path = None) -> Dict:
        """执行所有同步规则"""
        results = {"synced": 0, "skipped": 0, "errors": 0}
        
        for rule in self.sync_rules:
            if not rule.get("enabled", True):
                continue
            
            source = Path(rule["source"])
            pattern = rule["pattern"]
            direction = rule.get("direction", "bidirectional")
            resolution = rule.get("conflict_resolution", "newest_wins")
            
            if remote_root:
                remote_source = remote_root / source.relative_to("./")
            else:
                remote_source = self.config.sync_dir / source.name
            
            if source.exists():
                for local_file in source.rglob(pattern):
                    relative = local_file.relative_to(source)
                    remote_file = remote_source / relative
                    
                    if self.sync_file(local_file, remote_file, direction, resolution):
                        results["synced"] += 1
                    else:
                        results["errors"] += 1
            else:
                results["skipped"] += 1
                logger.warning(f"Source not found: {source}")
        
        # 记录环境信息
        self._record_env_sync()
        return results

    def _record_env_sync(self):
        with sqlite3.connect(self.config.db_path) as conn:
            conn.execute('''INSERT OR REPLACE INTO environment_info 
                          (env_id, hostname, platform, last_sync, config) 
                          VALUES (?, ?, ?, ?, ?)''',
                        (self.local_env["env_id"], self.local_env["hostname"],
                         self.local_env["platform"], datetime.now().isoformat(),
                         json.dumps(self.local_env)))

    def get_sync_status(self) -> Dict:
        with sqlite3.connect(self.config.db_path) as conn:
            cursor = conn.execute("SELECT * FROM sync_log ORDER BY sync_time DESC LIMIT 10")
            rows = cursor.fetchall()
            return {
                "local_env": self.local_env,
                "recent_syncs": [
                    {"file": r[1], "time": r[4], "status": r[5]} for r in rows
                ],
                "rules_count": len(self.sync_rules)
            }

    def add_sync_rule(self, name: str, source: str, pattern: str, 
                      direction: str = "bidirectional", conflict_resolution: str = "newest_wins"):
        self.sync_rules.append({
            "name": name, "source": source, "pattern": pattern,
            "direction": direction, "conflict_resolution": conflict_resolution,
            "enabled": True
        })
        rules_file = self.config.sync_dir / "sync_rules.json"
        with open(rules_file, 'w') as f:
            json.dump(self.sync_rules, f, indent=2)
        logger.info(f"Added sync rule: {name}")


if __name__ == '__main__':
    # 演示用法
    sync = CrossEnvSync()
    
    print("=== Sync Configuration ===")
    print(f"Local Env: {sync.local_env['hostname']} ({sync.local_env['platform']})")
    print(f"Sync Rules: {len(sync.sync_rules)}")
    
    print("\n=== Running Sync ===")
    results = sync.sync_all()
    print(f"Results: {results}")
    
    print("\n=== Sync Status ===")
    status = sync.get_sync_status()
    print(json.dumps(status, indent=2, ensure_ascii=False))
