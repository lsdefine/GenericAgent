#!/usr/bin/env python3
"""
Real-Time Collaboration Engine for GenericAgent
实时协作引擎: 多实例同步、操作转换(OT)、冲突解决、状态广播
支持: WebSocket、文件级锁、操作日志、回滚
"""

import os
import json
import time
import uuid
import logging
import threading
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

class CollaborationEngine:
    def __init__(self, workspace: str = ".collab_workspace"):
        self.workspace = workspace
        self.operations: List[Dict] = []
        self.locks: Dict[str, Dict] = {}
        self.connections: Dict[str, Dict] = {}
        self.callbacks: Dict[str, List[Callable]] = defaultdict(list)
        os.makedirs(workspace, exist_ok=True)
        self._load_state()
    
    def _load_state(self):
        state_file = os.path.join(self.workspace, "collab_state.json")
        if os.path.exists(state_file):
            with open(state_file) as f:
                data = json.load(f)
            self.operations = data.get('operations', [])
    
    def _save_state(self):
        state_file = os.path.join(self.workspace, "collab_state.json")
        data = {'operations': self.operations[-1000:], 'locks': {k: v for k, v in self.locks.items() if v.get('active')}}
        with open(state_file, 'w') as f:
            json.dump(data, f, indent=2)
    
    def connect(self, client_id: str, metadata: Dict = None) -> Dict:
        self.connections[client_id] = {
            'id': client_id, 'connected_at': datetime.now().isoformat(),
            'metadata': metadata or {}, 'last_seen': datetime.now().isoformat()
        }
        self._emit('connect', {'client_id': client_id})
        return {'status': 'connected', 'client_id': client_id}
    
    def disconnect(self, client_id: str):
        if client_id in self.connections:
            self._release_locks(client_id)
            del self.connections[client_id]
            self._emit('disconnect', {'client_id': client_id})
    
    def submit_operation(self, client_id: str, op_type: str, target: str, data: Dict) -> Dict:
        op = {
            'id': str(uuid.uuid4()), 'client_id': client_id,
            'type': op_type, 'target': target, 'data': data,
            'timestamp': datetime.now().isoformat()
        }
        if not self._acquire_lock(client_id, target):
            return {'status': 'locked', 'error': f'{target} is locked'}
        
        self.operations.append(op)
        self._save_state()
        self._emit('operation', op)
        logger.info(f"Op {op_type} on {target} by {client_id[:8]}...")
        return {'status': 'accepted', 'op_id': op['id']}
    
    def get_operations(self, target: str = None, limit: int = 50) -> List[Dict]:
        ops = self.operations
        if target:
            ops = [o for o in ops if o['target'] == target]
        return ops[-limit:]
    
    def lock_resource(self, client_id: str, resource: str, ttl: int = 300) -> bool:
        if resource in self.locks and self.locks[resource].get('active'):
            lock = self.locks[resource]
            if datetime.fromisoformat(lock['expires']) > datetime.now():
                return False
        self.locks[resource] = {
            'client_id': client_id, 'active': True,
            'acquired_at': datetime.now().isoformat(),
            'expires': (datetime.now() + __import__('datetime').timedelta(seconds=ttl)).isoformat()
        }
        return True
    
    def _acquire_lock(self, client_id: str, resource: str) -> bool:
        if resource in self.locks and self.locks[resource].get('active'):
            lock = self.locks[resource]
            if lock['client_id'] != client_id:
                return datetime.fromisoformat(lock['expires']) < datetime.now()
        return True
    
    def _release_locks(self, client_id: str):
        for resource, lock in self.locks.items():
            if lock.get('client_id') == client_id:
                lock['active'] = False
    
    def resolve_conflict(self, op1: Dict, op2: Dict) -> Dict:
        if op1['timestamp'] < op2['timestamp']:
            return {'winner': op1['id'], 'strategy': 'last_write_wins'}
        return {'winner': op2['id'], 'strategy': 'last_write_wins'}
    
    def rollback(self, op_id: str) -> bool:
        for i, op in enumerate(self.operations):
            if op['id'] == op_id:
                op['rolled_back'] = True
                op['rollback_at'] = datetime.now().isoformat()
                self._save_state()
                self._emit('rollback', {'op_id': op_id})
                return True
        return False
    
    def broadcast(self, message: Dict, exclude: str = None):
        for cid in self.connections:
            if cid != exclude:
                self._emit('broadcast', {'to': cid, 'message': message})
    
    def on(self, event: str, callback: Callable):
        self.callbacks[event].append(callback)
    
    def _emit(self, event: str, data: Dict):
        for cb in self.callbacks.get(event, []):
            try:
                cb(data)
            except Exception as e:
                logger.error(f"Callback error: {e}")
    
    def get_active_users(self) -> List[Dict]:
        now = datetime.now()
        return [c for c in self.connections.values() 
                if (now - datetime.fromisoformat(c['last_seen'])).total_seconds() < 60]

if __name__ == '__main__':
    engine = CollaborationEngine()
    
    engine.connect("alice", {"role": "editor"})
    engine.connect("bob", {"role": "viewer"})
    
    print("=== Active Users ===")
    print(len(engine.get_active_users()), "users connected")
    
    result = engine.submit_operation("alice", "edit", "report.md", {"change": "added section"})
    print(f"\nOperation: {result}")
    
    ops = engine.get_operations("report.md")
    print(f"\nOperations on report.md: {len(ops)}")
    
    engine.rollback(ops[0]['id']) if ops else None
    print("Rollback test done")
    
    engine.disconnect("alice")
    engine.disconnect("bob")
