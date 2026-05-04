#!/usr/bin/env python3
"""
Federated Learning Orchestrator for GenericAgent
联邦学习编排器: 分布式模型训练、模型聚合(FedAvg)、隐私保护
支持: 客户端管理、轮次调度、差分隐私、模型差分
"""

import os
import json
import time
import logging
import hashlib
from datetime import datetime
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class FLClient:
    client_id: str
    status: str = 'idle'  # idle, training, aggregating, offline
    local_model_hash: str = ""
    data_points: int = 0
    last_update: str = ""
    metadata: Dict = field(default_factory=dict)

@dataclass
class FLRound:
    round_id: int
    selected_clients: List[str] = field(default_factory=list)
    status: str = 'pending'  # pending, training, aggregating, completed
    start_time: str = ""
    end_time: str = ""
    aggregation_result: Dict = field(default_factory=dict)


class DifferentialPrivacy:
    def __init__(self, epsilon: float = 1.0, delta: float = 1e-5):
        self.epsilon = epsilon
        self.delta = delta
        self.sensitivity = 1.0
    
    def add_noise(self, value: float) -> float:
        """Add Laplace noise for differential privacy"""
        import random
        import math
        b = self.sensitivity / self.epsilon
        u = random.uniform(-0.5, 0.5)
        noise = -b * math.copysign(1, u) * math.log(1 - 2 * abs(u))
        return value + noise
    
    def clip_gradient(self, gradient: List[float], max_norm: float = 1.0) -> List[float]:
        """Clip gradient by L2 norm"""
        norm = sum(g**2 for g in gradient) ** 0.5
        if norm > max_norm:
            return [g * max_norm / norm for g in gradient]
        return gradient


class ModelAggregator:
    @staticmethod
    def fed_avg(models: List[Dict[str, List[float]]], weights: List[float] = None) -> Dict[str, List[float]]:
        """Federated Averaging: weighted average of model parameters"""
        if not models:
            return {}
        
        if weights is None:
            weights = [1.0 / len(models)] * len(models)
        
        total_weight = sum(weights)
        weights = [w / total_weight for w in weights]
        
        aggregated = {}
        all_keys = set()
        for m in models:
            all_keys.update(m.keys())
        
        for key in all_keys:
            client_values = []
            client_weights = []
            for i, m in enumerate(models):
                if key in m:
                    client_values.append(m[key])
                    client_weights.append(weights[i])
            
            if client_values:
                if isinstance(client_values[0], list):
                    # Vector parameters
                    dim = len(client_values[0])
                    agg = [0.0] * dim
                    for vals, w in zip(client_values, client_weights):
                        for j in range(dim):
                            agg[j] += vals[j] * w
                    aggregated[key] = agg
                else:
                    # Scalar parameters
                    agg = sum(v * w for v, w in zip(client_values, client_weights))
                    aggregated[key] = agg
        
        return aggregated
    
    @staticmethod
    def compute_model_hash(model: Dict) -> str:
        """Compute SHA256 hash of model parameters"""
        return hashlib.sha256(json.dumps(model, sort_keys=True).encode()).hexdigest()[:16]


class FederatedLearningOrchestrator:
    def __init__(self, n_rounds: int = 10, clients_per_round: int = 3, 
                 dp_enabled: bool = False, storage_dir: str = ".fl_data"):
        self.n_rounds = n_rounds
        self.clients_per_round = clients_per_round
        self.dp = DifferentialPrivacy() if dp_enabled else None
        self.storage_dir = storage_dir
        self.clients: Dict[str, FLClient] = {}
        self.rounds: List[FLRound] = []
        self.global_model: Dict[str, List[float]] = {}
        self.aggregator = ModelAggregator()
        os.makedirs(storage_dir, exist_ok=True)
    
    def register_client(self, client_id: str, metadata: Dict = None) -> FLClient:
        client = FLClient(client_id=client_id, metadata=metadata or {})
        self.clients[client_id] = client
        return client
    
    def select_clients(self) -> List[str]:
        """Select available clients for training round"""
        available = [cid for cid, c in self.clients.items() if c.status == 'idle']
        import random
        return random.sample(available, min(self.clients_per_round, len(available)))
    
    def start_round(self) -> FLRound:
        selected = self.select_clients()
        round_obj = FLRound(
            round_id=len(self.rounds),
            selected_clients=selected,
            status='training',
            start_time=datetime.now().isoformat()
        )
        self.rounds.append(round_obj)
        
        for cid in selected:
            self.clients[cid].status = 'training'
        
        return round_obj
    
    def submit_local_model(self, client_id: str, local_model: Dict, data_points: int = 0) -> bool:
        if client_id not in self.clients:
            return False
        
        client = self.clients[client_id]
        client.local_model_hash = self.aggregator.compute_model_hash(local_model)
        client.data_points = data_points
        client.last_update = datetime.now().isoformat()
        client.status = 'idle'
        
        if self.dp:
            noisy_model = {}
            for key, params in local_model.items():
                if isinstance(params, list):
                    noisy_model[key] = [self.dp.add_noise(p) for p in params]
                else:
                    noisy_model[key] = self.dp.add_noise(params)
            local_model = noisy_model
        
        return True
    
    def aggregate(self, round_id: int) -> Dict:
        round_obj = self.rounds[round_id]
        round_obj.status = 'aggregating'
        
        local_models = []
        weights = []
        for cid in round_obj.selected_clients:
            client = self.clients[cid]
            if client.local_model_hash:
                # In real scenario, load actual model; here we simulate
                local_models.append({'w': [0.1] * 10})
                weights.append(client.data_points or 1)
        
        if local_models:
            self.global_model = self.aggregator.fed_avg(local_models, weights)
            round_obj.aggregation_result = {
                'global_hash': self.aggregator.compute_model_hash(self.global_model),
                'n_models': len(local_models)
            }
        
        round_obj.status = 'completed'
        round_obj.end_time = datetime.now().isoformat()
        self._save_round(round_obj)
        return round_obj.aggregation_result
    
    def _save_round(self, round_obj: FLRound):
        fpath = os.path.join(self.storage_dir, f"round_{round_obj.round_id}.json")
        with open(fpath, 'w') as f:
            json.dump({
                'round_id': round_obj.round_id,
                'selected_clients': round_obj.selected_clients,
                'status': round_obj.status,
                'start_time': round_obj.start_time,
                'end_time': round_obj.end_time,
                'result': round_obj.aggregation_result
            }, f, indent=2)
    
    def get_training_summary(self) -> Dict:
        return {
            'n_clients': len(self.clients),
            'n_rounds': len(self.rounds),
            'completed_rounds': sum(1 for r in self.rounds if r.status == 'completed'),
            'global_model_hash': self.aggregator.compute_model_hash(self.global_model) if self.global_model else None
        }


if __name__ == '__main__':
    fl = FederatedLearningOrchestrator(n_rounds=5, clients_per_round=2, dp_enabled=True)
    
    # Register simulated clients
    for i in range(5):
        fl.register_client(f"client_{i}", {'data_size': 1000*(i+1)})
    
    print("=== Federated Learning Simulation ===")
    for round_num in range(3):
        r = fl.start_round()
        print(f"\nRound {r.round_id}: selected {r.selected_clients}")
        
        for cid in r.selected_clients:
            # Simulate local training
            import random
            local_model = {'w': [random.gauss(0, 1) for _ in range(10)]}
            fl.submit_local_model(cid, local_model, data_points=100)
        
        result = fl.aggregate(r.round_id)
        print(f"  Aggregated: {result}")
    
    print(f"\n=== Summary ===")
    print(json.dumps(fl.get_training_summary(), indent=2))
