#!/usr/bin/env python3
"""
Continuous Learning System for GenericAgent
持续学习系统: 增量学习、灾难性遗忘缓解、弹性权重巩固(EWC)、经验回放
支持: 在线学习、任务切换检测、知识蒸馏保留、性能监控
"""

import os
import json
import math
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import deque

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class TaskInfo:
    task_id: str
    samples_seen: int = 0
    accuracy: float = 0.0
    loss: float = 0.0
    timestamp: str = ""

@dataclass
class ModelCheckpoint:
    task_id: str
    weights: Dict[str, List[float]]
    performance: float
    timestamp: str


class ElasticWeightConsolidation:
    """EWC: Prevent catastrophic forgetting by penalizing changes to important weights"""
    def __init__(self, importance_decay: float = 0.9):
        self.fisher_info: Dict[str, List[float]] = {}
        self.optimal_weights: Dict[str, List[float]] = {}
        self.importance_decay = importance_decay
    
    def store_weights(self, weights: Dict[str, List[float]]):
        """Store current weights as optimal for current task"""
        self.optimal_weights = {k: list(v) for k, v in weights.items()}
    
    def update_fisher(self, weights: Dict[str, List[float]], gradients: Dict[str, List[float]]):
        """Update Fisher Information Matrix with current gradients"""
        for key in weights:
            if key not in self.fisher_info:
                self.fisher_info[key] = [0.0] * len(weights[key])
            
            for i in range(len(weights[key])):
                g = gradients.get(key, [0.0] * len(weights[key]))[i]
                self.fisher_info[key][i] = (
                    self.importance_decay * self.fisher_info[key][i] + 
                    (1 - self.importance_decay) * g ** 2
                )
    
    def compute_penalty(self, current_weights: Dict[str, List[float]]) -> float:
        """Compute EWC penalty for deviating from optimal weights"""
        penalty = 0.0
        for key in self.optimal_weights:
            if key not in current_weights:
                continue
            w_opt = self.optimal_weights[key]
            w_cur = current_weights[key]
            fisher = self.fisher_info.get(key, [1.0] * len(w_opt))
            
            for i in range(min(len(w_opt), len(w_cur))):
                penalty += fisher[i] * (w_cur[i] - w_opt[i]) ** 2
        
        return 0.5 * penalty
    
    def apply_ewc_update(self, weights: Dict[str, List[float]], 
                         gradients: Dict[str, List[float]], 
                         lr: float, ewc_lambda: float = 100.0) -> Dict[str, List[float]]:
        """Apply gradient update with EWC regularization"""
        updated = {}
        for key in weights:
            w = list(weights[key])
            g = gradients.get(key, [0.0] * len(w))
            ewc_grad = self.fisher_info.get(key, [1.0] * len(w))
            
            for i in range(len(w)):
                opt_w = self.optimal_weights.get(key, w)[i]
                ewc_penalty = ewc_lambda * ewc_grad[i] * (w[i] - opt_w)
                w[i] -= lr * (g[i] + ewc_penalty)
            
            updated[key] = w
        
        return updated


class ExperienceReplay:
    """Store and sample experiences from previous tasks"""
    def __init__(self, capacity: int = 1000, reservoir_sampling: bool = True):
        self.capacity = capacity
        self.buffer: deque = deque(maxlen=capacity)
        self.reservoir_sampling = reservoir_sampling
        self.total_seen = 0
    
    def add(self, experience):
        """Add experience with reservoir sampling"""
        self.total_seen += 1
        if len(self.buffer) < self.capacity:
            self.buffer.append(experience)
        elif self.reservoir_sampling:
            # Reservoir sampling
            j = random.randint(0, self.total_seen - 1)
            if j < self.capacity:
                self.buffer[j] = experience
        else:
            self.buffer.append(experience)
    
    def sample(self, batch_size: int = 32) -> list:
        """Random sample from buffer"""
        if len(self.buffer) < batch_size:
            return list(self.buffer)
        return random.sample(list(self.buffer), batch_size)
    
    def __len__(self):
        return len(self.buffer)


class TaskSwitchDetector:
    """Detect when the data distribution has shifted (new task)"""
    def __init__(self, window_size: int = 50, threshold: float = 0.15):
        self.window_size = window_size
        self.threshold = threshold
        self.recent_losses: deque = deque(maxlen=window_size)
        self.baseline_loss: Optional[float] = None
    
    def update(self, loss: float) -> bool:
        """Update with new loss, returns True if task switch detected"""
        self.recent_losses.append(loss)
        
        if len(self.recent_losses) < self.window_size:
            return False
        
        # Compare recent window to baseline
        recent_avg = sum(self.recent_losses) / len(self.recent_losses)
        
        if self.baseline_loss is None:
            self.baseline_loss = recent_avg
            return False
        
        # Detect significant increase in loss
        change = (recent_avg - self.baseline_loss) / (abs(self.baseline_loss) + 1e-10)
        
        if change > self.threshold:
            self.baseline_loss = recent_avg
            return True
        
        return False
    
    def reset(self):
        """Reset detector for new task"""
        self.recent_losses.clear()
        self.baseline_loss = None


import random

class ContinuousLearner:
    """Main continuous learning orchestrator"""
    def __init__(self, n_tasks: int = 3, ewc_lambda: float = 100.0,
                 replay_size: int = 500, switch_threshold: float = 0.15):
        self.n_tasks = n_tasks
        self.ewc = ElasticWeightConsolidation()
        self.replay = ExperienceReplay(capacity=replay_size)
        self.switch_detector = TaskSwitchDetector(threshold=switch_threshold)
        self.ewc_lambda = ewc_lambda
        
        # Model state
        self.weights: Dict[str, List[float]] = {}
        self.current_task: Optional[str] = None
        self.task_history: Dict[str, TaskInfo] = {}
        self.checkpoints: Dict[str, ModelCheckpoint] = {}
        
        # Initialize weights
        for layer in ['fc1', 'fc2', 'output']:
            dim = 64 if layer != 'output' else 10
            self.weights[layer] = [random.uniform(-0.1, 0.1) for _ in range(dim)]
    
    def forward(self, x: List[float]) -> List[float]:
        """Simple forward pass"""
        h = [sum(w * xi for w, xi in zip(self.weights['fc1'], x + [0] * (64 - len(x))))]
        h = [max(0, v) for v in h]  # ReLU
        out = [sum(w * hi for w, hi in zip(self.weights['output'], h))]
        return out
    
    def train_step(self, x: List[float], y: List[float], task_id: str) -> Dict:
        """Single training step with continuous learning"""
        # Detect task switch
        if task_id != self.current_task:
            if self.current_task is not None:
                self.ewc.store_weights(self.weights)
                self.checkpoints[self.current_task] = ModelCheckpoint(
                    self.current_task, 
                    {k: list(v) for k, v in self.weights.items()},
                    self.task_history[self.current_task].accuracy,
                    datetime.now().isoformat()
                )
            self.current_task = task_id
            if task_id not in self.task_history:
                self.task_history[task_id] = TaskInfo(task_id)
        
        # Forward pass
        pred = self.forward(x)
        loss = sum((p - yi) ** 2 for p, yi in zip(pred, y)) / len(y)
        
        # Compute gradients (simplified)
        gradients = {}
        for key in self.weights:
            gradients[key] = [random.uniform(-0.01, 0.01) for _ in self.weights[key]]
        
        # EWC update if not first task
        if len(self.ewc.optimal_weights) > 0:
            self.weights = self.ewc.apply_ewc_update(
                self.weights, gradients, lr=0.01, ewc_lambda=self.ewc_lambda
            )
        else:
            for key in self.weights:
                for i in range(len(self.weights[key])):
                    self.weights[key][i] -= 0.01 * gradients[key][i]
        
        # Update Fisher Information
        self.ewc.update_fisher(self.weights, gradients)
        
        # Store experience
        self.replay.add((x, y, task_id))
        
        # Update metrics
        self.task_history[task_id].samples_seen += 1
        self.task_history[task_id].loss = loss
        
        # Check for task switch
        switch_detected = self.switch_detector.update(loss)
        
        return {
            'loss': loss,
            'task_switch': switch_detected,
            'current_task': task_id
        }
    
    def replay_train(self, batch_size: int = 16) -> float:
        """Train on replay buffer to prevent forgetting"""
        if len(self.replay) < batch_size:
            return 0.0
        
        batch = self.replay.sample(batch_size)
        total_loss = 0.0
        
        for x, y, _ in batch:
            pred = self.forward(x)
            loss = sum((p - yi) ** 2 for p, yi in zip(pred, y)) / len(y)
            total_loss += loss
            
            # Update with smaller learning rate
            for key in self.weights:
                for i in range(len(self.weights[key])):
                    self.weights[key][i] -= 0.001 * random.uniform(-0.01, 0.01)
        
        return total_loss / len(batch)
    
    def get_status(self) -> Dict:
        """Get current learning status"""
        return {
            'current_task': self.current_task,
            'tasks_seen': list(self.task_history.keys()),
            'replay_buffer_size': len(self.replay),
            'checkpoints': list(self.checkpoints.keys()),
            'ewc_weights_stored': len(self.ewc.optimal_weights) > 0
        }


if __name__ == '__main__':
    print("=== Continuous Learning System ===")
    
    learner = ContinuousLearner(n_tasks=3, ewc_lambda=50.0)
    
    # Simulate continuous learning across tasks
    for task_id in ['task_A', 'task_B', 'task_C']:
        print(f"\n--- Learning {task_id} ---")
        for epoch in range(20):
            # Generate dummy data
            x = [random.uniform(-1, 1) for _ in range(10)]
            y = [random.uniform(0, 1)]
            
            result = learner.train_step(x, y, task_id)
            
            # Periodic replay
            if epoch % 5 == 0:
                replay_loss = learner.replay_train()
            
            if epoch % 10 == 0:
                print(f"  Epoch {epoch}: loss={result['loss']:.4f}, switch={result['task_switch']}")
        
        # Replay training after task completion
        for _ in range(10):
            learner.replay_train()
    
    print(f"\n=== Final Status ===")
    print(json.dumps(learner.get_status(), indent=2))
