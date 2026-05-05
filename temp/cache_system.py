#!/usr/bin/env python3
"""Cache System - Multi-level cache (LRU/memory/disk) with TTL support"""
import os
import time
import json
import hashlib
from typing import Any, Optional, Dict
from collections import OrderedDict
from threading import Lock

class LRUCache:
    """In-memory LRU cache with TTL"""
    
    def __init__(self, maxsize: int = 128):
        self.maxsize = maxsize
        self.store = OrderedDict()
        self.ttl_store = {}
        self.lock = Lock()
    
    def get(self, key: str) -> Optional[Any]:
        with self.lock:
            if key in self.store:
                if key in self.ttl_store and time.time() > self.ttl_store[key]:
                    self.store.pop(key, None)
                    self.ttl_store.pop(key, None)
                    return None
                self.store.move_to_end(key)
                return self.store[key]
            return None
    
    def put(self, key: str, value: Any, ttl: int = 3600):
        with self.lock:
            if key in self.store:
                self.store.move_to_end(key)
            else:
                if len(self.store) >= self.maxsize:
                    old_key = next(iter(self.store))
                    self.store.pop(old_key)
                    self.ttl_store.pop(old_key, None)
            self.store[key] = value
            self.ttl_store[key] = time.time() + ttl
    
    def clear(self):
        with self.lock:
            self.store.clear()
            self.ttl_store.clear()
    
    def size(self):
        return len(self.store)


class DiskCache:
    """Disk-based cache with TTL"""
    
    def __init__(self, cache_dir: str = ".cache"):
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)
        self.lock = Lock()
    
    def _key_path(self, key: str) -> str:
        hashed = hashlib.md5(key.encode()).hexdigest()
        return os.path.join(self.cache_dir, f"{hashed}.json")
    
    def get(self, key: str) -> Optional[Any]:
        with self.lock:
            path = self._key_path(key)
            if not os.path.exists(path):
                return None
            with open(path, "r") as f:
                data = json.load(f)
            if time.time() > data.get("expires", 0):
                os.remove(path)
                return None
            return data["value"]
    
    def put(self, key: str, value: Any, ttl: int = 86400):
        with self.lock:
            path = self._key_path(key)
            data = {"value": value, "expires": time.time() + ttl}
            with open(path, "w") as f:
                json.dump(data, f)
    
    def clear(self):
        with self.lock:
            for fn in os.listdir(self.cache_dir):
                os.remove(os.path.join(self.cache_dir, fn))


class MultiLevelCache:
    """Multi-level cache: L1 (memory) -> L2 (disk)"""
    
    def __init__(self, mem_size: int = 256, cache_dir: str = ".cache"):
        self.l1 = LRUCache(maxsize=mem_size)
        self.l2 = DiskCache(cache_dir=cache_dir)
        self.stats = {"hits": 0, "misses": 0, "l2_hits": 0}
    
    def get(self, key: str, ttl: int = 3600) -> Optional[Any]:
        val = self.l1.get(key)
        if val is not None:
            self.stats["hits"] += 1
            return val
        
        val = self.l2.get(key)
        if val is not None:
            self.l1.put(key, val, ttl)
            self.stats["hits"] += 1
            self.stats["l2_hits"] += 1
            return val
        
        self.stats["misses"] += 1
        return None
    
    def put(self, key: str, value: Any, ttl: int = 3600, disk: bool = True):
        self.l1.put(key, value, ttl)
        if disk:
            self.l2.put(key, value, ttl)
    
    def clear(self):
        self.l1.clear()
        self.l2.clear()
    
    def get_stats(self):
        return {
            **self.stats,
            "l1_size": self.l1.size(),
            "hit_rate": self.stats["hits"] / max(1, self.stats["hits"] + self.stats["misses"])
        }


if __name__ == "__main__":
    cache = MultiLevelCache(mem_size=3)
    
    cache.put("a", 1, ttl=60)
    cache.put("b", 2, ttl=60)
    cache.put("c", 3, ttl=60)
    
    print("Get a:", cache.get("a"))
    print("Get b:", cache.get("b"))
    
    cache.put("d", 4, ttl=60)
    cache.put("e", 5, ttl=60)
    
    print("Get a (evicted?):", cache.get("a"))
    print("Get c:", cache.get("c"))
    print("Get d:", cache.get("d"))
    
    cache.put("heavy", "x" * 1000, ttl=300, disk=True)
    print("Heavy from disk:", cache.get("heavy"))
    
    stats = cache.get_stats()
    print(f"Stats: {stats}")
    
    cache.clear()
    import shutil
    if os.path.exists(".cache"):
        shutil.rmtree(".cache")
    print("Cache system ready.")
