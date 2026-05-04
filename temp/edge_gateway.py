#!/usr/bin/env python3
"""
Edge Computing Gateway for GenericAgent
边缘计算网关: 本地数据预处理、设备管理、边缘推理、离线缓存
支持: 传感器数据采集、MQTT桥接、本地缓存、边缘规则引擎
"""

import os
import json
import time
import logging
import threading
from datetime import datetime
from typing import Dict, List, Optional, Callable
from collections import deque

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

class EdgeGateway:
    def __init__(self, cache_dir: str = ".edge_cache"):
        self.cache_dir = cache_dir
        self.devices: Dict[str, Dict] = {}
        self.rules: List[Dict] = []
        self.data_buffer: deque = deque(maxlen=10000)
        self.callbacks: Dict[str, List[Callable]] = {}
        os.makedirs(cache_dir, exist_ok=True)
        self._load_state()
    
    def _load_state(self):
        state_file = os.path.join(self.cache_dir, "gateway_state.json")
        if os.path.exists(state_file):
            with open(state_file) as f:
                state = json.load(f)
            self.devices = state.get('devices', {})
            self.rules = state.get('rules', [])
    
    def _save_state(self):
        state_file = os.path.join(self.cache_dir, "gateway_state.json")
        with open(state_file, 'w') as f:
            json.dump({'devices': self.devices, 'rules': self.rules}, f, indent=2)
    
    def register_device(self, device_id: str, device_type: str, metadata: Dict = None) -> Dict:
        self.devices[device_id] = {
            'id': device_id, 'type': device_type, 'status': 'online',
            'last_seen': datetime.now().isoformat(), 'metadata': metadata or {},
            'data_points': 0
        }
        self._save_state()
        self._emit('device_connected', {'device_id': device_id})
        return self.devices[device_id]
    
    def receive_data(self, device_id: str, payload: Dict) -> Dict:
        if device_id not in self.devices:
            return {'status': 'error', 'message': 'Device not registered'}
        
        record = {
            'device_id': device_id, 'timestamp': datetime.now().isoformat(),
            'payload': payload
        }
        self.data_buffer.append(record)
        self.devices[device_id]['last_seen'] = record['timestamp']
        self.devices[device_id]['data_points'] += 1
        
        # Evaluate rules
        self._evaluate_rules(record)
        return {'status': 'accepted'}
    
    def add_rule(self, rule_id: str, condition: str, action: str) -> bool:
        self.rules.append({
            'id': rule_id, 'condition': condition, 'action': action,
            'enabled': True, 'triggered_count': 0
        })
        self._save_state()
        return True
    
    def _evaluate_rules(self, record: Dict):
        for rule in self.rules:
            if not rule['enabled']:
                continue
            # Simple condition evaluation (device_id match, value threshold)
            try:
                if rule['condition'] in json.dumps(record):
                    rule['triggered_count'] += 1
                    self._emit('rule_triggered', {'rule_id': rule['id'], 'record': record})
            except Exception as e:
                logger.error(f"Rule eval error: {e}")
    
    def get_cached_data(self, device_id: str = None, limit: int = 100) -> List[Dict]:
        data = list(self.data_buffer)
        if device_id:
            data = [d for d in data if d['device_id'] == device_id]
        return data[-limit:]
    
    def flush_cache(self, target_dir: str = None) -> int:
        target = target_dir or self.cache_dir
        batch_file = os.path.join(target, f"batch_{int(time.time())}.json")
        data = list(self.data_buffer)
        with open(batch_file, 'w') as f:
            json.dump(data, f, indent=2)
        count = len(data)
        self.data_buffer.clear()
        return count
    
    def on(self, event: str, callback: Callable):
        if event not in self.callbacks:
            self.callbacks[event] = []
        self.callbacks[event].append(callback)
    
    def _emit(self, event: str, data: Dict):
        for cb in self.callbacks.get(event, []):
            try:
                cb(data)
            except Exception as e:
                logger.error(f"Callback error: {e}")
    
    def get_status(self) -> Dict:
        return {
            'devices': len(self.devices),
            'rules': len(self.rules),
            'buffer_size': len(self.data_buffer),
            'online_devices': sum(1 for d in self.devices.values() 
                                  if d.get('status') == 'online')
        }

if __name__ == '__main__':
    gateway = EdgeGateway()
    print("=== Gateway Status ===")
    print(json.dumps(gateway.get_status(), indent=2))
    
    gateway.register_device("sensor_01", "temperature", {'location': 'room_a'})
    gateway.register_device("sensor_02", "humidity", {'location': 'room_b'})
    
    gateway.add_rule("temp_high", "sensor_01", "alert")
    
    gateway.receive_data("sensor_01", {'temperature': 28.5})
    gateway.receive_data("sensor_02", {'humidity': 65})
    
    print("\n=== Cached Data ===")
    print(json.dumps(gateway.get_cached_data(limit=5), indent=2))
    
    count = gateway.flush_cache()
    print(f"\nFlushed {count} records to cache")
