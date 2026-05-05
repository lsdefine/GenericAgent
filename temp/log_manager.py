#!/usr/bin/env python3
"""Log Manager - Structured logging with rotation and analysis"""
import logging
import os
from logging.handlers import RotatingFileHandler
from typing import Dict, List, Optional
from datetime import datetime

class LogManager:
    """Structured log manager with rotation and analysis"""
    
    _instance = None
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, log_file: str = "agent.log", max_bytes: int = 10*1024*1024, backup_count: int = 3):
        if self._initialized:
            return
        self._initialized = True
        self.log_file = log_file
        self.logger = logging.getLogger("GenericAgent")
        self.logger.setLevel(logging.DEBUG)
        
        # Console handler
        console = logging.StreamHandler()
        console.setLevel(logging.INFO)
        console.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        self.logger.addHandler(console)
        
        # File handler with rotation
        file_handler = RotatingFileHandler(log_file, maxBytes=max_bytes, backupCount=backup_count)
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s:%(funcName)s - %(message)s"))
        self.logger.addHandler(file_handler)
    
    def get_logger(self, name: str = "GenericAgent"):
        return self.logger.getChild(name)
    
    def analyze_logs(self, log_file: Optional[str] = None) -> Dict:
        """Analyze log file for patterns"""
        target = log_file or self.log_file
        if not os.path.exists(target):
            return {"error": "Log file not found"}
        
        counts = {"DEBUG": 0, "INFO": 0, "WARNING": 0, "ERROR": 0}
        with open(target, 'r') as f:
            for line in f:
                if "[DEBUG]" in line: counts["DEBUG"] += 1
                elif "[INFO]" in line: counts["INFO"] += 1
                elif "[WARNING]" in line: counts["WARNING"] += 1
                elif "[ERROR]" in line: counts["ERROR"] += 1
        
        total = sum(counts.values())
        return {
            "file": target,
            "total_entries": total,
            "by_level": counts,
            "error_rate": f"{(counts['ERROR']/total*100) if total > 0 else 0:.1f}%"
        }


if __name__ == "__main__":
    # Initialize log manager
    log_mgr = LogManager(log_file="test_agent.log")
    logger = log_mgr.get_logger("TestModule")
    
    # Generate test logs
    logger.debug("Debug: Variable x = 42")
    logger.info("System startup complete")
    logger.info("Processing 100 requests")
    logger.warning("High memory usage detected: 85%")
    logger.error("Connection timeout to database")
    logger.info("Request completed successfully")
    
    # Analyze
    time.sleep(0.1)  # Allow flush
    stats = log_mgr.analyze_logs("test_agent.log")
    print("\n=== Log Analysis ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    
    # Cleanup
    if os.path.exists("test_agent.log"):
        os.remove("test_agent.log")
    print("Log manager ready.")
