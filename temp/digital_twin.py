#!/usr/bin/env python3
"""
Digital Twin Simulator for GenericAgent
数字孪生模拟器: 物理系统建模、实时同步、预测仿真、状态对比
支持: 实体建模、传感器数据流、偏差检测、what-if模拟
"""

import os
import json
import time
import math
import logging
from datetime import datetime
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field, asdict

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class TwinProperty:
    name: str
    value: float
    min_val: float = 0.0
    max_val: float = 100.0
    unit: str = ""
    drift_rate: float = 0.0

@dataclass
class TwinState:
    timestamp: str
    properties: Dict[str, float]
    health_score: float = 1.0

@dataclass
class SimulationResult:
    scenario: str
    predicted_state: Dict[str, float]
    deviation_from_current: Dict[str, float]
    timestamp: str


class DigitalTwin:
    def __init__(self, twin_id: str, model_type: str = "generic"):
        self.twin_id = twin_id
        self.model_type = model_type
        self.properties: Dict[str, TwinProperty] = {}
        self.state_history: List[TwinState] = []
        self.real_time_sync: bool = False
        self.deviation_threshold = 0.1
        self.callbacks: List[Callable] = []
    
    def add_property(self, name: str, value: float, min_val: float = 0, 
                     max_val: float = 100, unit: str = "", drift_rate: float = 0):
        self.properties[name] = TwinProperty(name, value, min_val, max_val, unit, drift_rate)
    
    def update_from_sensor(self, sensor_data: Dict[str, float]) -> Dict[str, float]:
        """Update twin state from real sensor data"""
        deviations = {}
        for name, new_val in sensor_data.items():
            if name in self.properties:
                old_val = self.properties[name].value
                self.properties[name].value = new_val
                deviations[name] = abs(new_val - old_val)
        
        state = TwinState(
            timestamp=datetime.now().isoformat(),
            properties={k: v.value for k, v in self.properties.items()}
        )
        self.state_history.append(state)
        
        # Check health
        max_dev = max(deviations.values()) if deviations else 0
        state.health_score = max(0.0, 1.0 - (max_dev / self.deviation_threshold))
        
        for cb in self.callbacks:
            cb(state)
        
        return deviations
    
    def simulate_drift(self, duration_sec: float, step: float = 1.0) -> List[TwinState]:
        """Simulate natural drift over time"""
        states = []
        steps = int(duration_sec / step)
        for i in range(steps):
            t = datetime.now().isoformat()
            props = {}
            for name, prop in self.properties.items():
                prop.value += prop.drift_rate * step
                prop.value = max(prop.min_val, min(prop.max_val, prop.value))
                props[name] = prop.value
            states.append(TwinState(timestamp=t, properties=props))
        self.state_history.extend(states)
        return states
    
    def what_if(self, scenario: Dict[str, float]) -> SimulationResult:
        """What-if simulation"""
        predicted = {}
        deviations = {}
        for name, change in scenario.items():
            if name in self.properties:
                predicted[name] = self.properties[name].value + change
                deviations[name] = change
        
        return SimulationResult(
            scenario=json.dumps(scenario),
            predicted_state=predicted,
            deviation_from_current=deviations,
            timestamp=datetime.now().isoformat()
        )
    
    def get_current_state(self) -> TwinState:
        if self.state_history:
            return self.state_history[-1]
        return TwinState(
            timestamp=datetime.now().isoformat(),
            properties={k: v.value for k, v in self.properties.items()}
        )
    
    def get_health_report(self) -> Dict:
        state = self.get_current_state()
        return {
            'twin_id': self.twin_id,
            'health_score': state.health_score,
            'n_properties': len(self.properties),
            'history_length': len(self.state_history)
        }


class TwinManager:
    def __init__(self, storage_dir: str = ".twins"):
        self.twins: Dict[str, DigitalTwin] = {}
        self.storage_dir = storage_dir
        os.makedirs(storage_dir, exist_ok=True)
    
    def create_twin(self, twin_id: str, model_type: str = "generic") -> DigitalTwin:
        twin = DigitalTwin(twin_id, model_type)
        self.twins[twin_id] = twin
        return twin
    
    def sync_all(self, sensor_data: Dict[str, Dict[str, float]]) -> Dict:
        results = {}
        for twin_id, data in sensor_data.items():
            if twin_id in self.twins:
                results[twin_id] = self.twins[twin_id].update_from_sensor(data)
        return results
    
    def export_twin(self, twin_id: str) -> str:
        if twin_id not in self.twins:
            return ""
        twin = self.twins[twin_id]
        data = {
            'twin_id': twin.twin_id,
            'model_type': twin.model_type,
            'properties': {k: asdict(v) for k, v in twin.properties.items()},
            'state_history': [asdict(s) for s in twin.state_history[-100:]]
        }
        fpath = os.path.join(self.storage_dir, f"{twin_id}.json")
        with open(fpath, 'w') as f:
            json.dump(data, f, indent=2)
        return fpath


if __name__ == '__main__':
    manager = TwinManager()
    
    # Create a temperature sensor twin
    temp_twin = manager.create_twin("temp_sensor_01", "thermal")
    temp_twin.add_property("temperature", 22.5, min_val=-10, max_val=50, unit="°C", drift_rate=0.01)
    temp_twin.add_property("humidity", 45.0, min_val=0, max_val=100, unit="%", drift_rate=-0.005)
    
    print("=== Digital Twin Simulation ===")
    states = temp_twin.simulate_drift(10, step=2)
    print(f"Simulated {len(states)} states")
    print(f"Final state: {json.dumps(states[-1].properties, indent=2)}")
    
    # Sensor sync
    deviations = temp_twin.update_from_sensor({"temperature": 24.0, "humidity": 43.0})
    print(f"Deviations: {deviations}")
    
    # What-if
    result = temp_twin.what_if({"temperature": 5.0, "humidity": -10.0})
    print(f"\nWhat-if predicted: {json.dumps(result.predicted_state, indent=2)}")
    
    # Health
    print(f"\nHealth: {json.dumps(temp_twin.get_health_report(), indent=2)}")
    
    # Export
    fpath = manager.export_twin("temp_sensor_01")
    print(f"Exported to: {fpath}")
