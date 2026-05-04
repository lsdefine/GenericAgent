#!/usr/bin/env python3
"""
Meta-Learning Framework for GenericAgent
元学习框架: MAML(模型无关元学习)、原型网络、支持集/查询集
支持: 快速适应、少样本学习、元训练循环、任务采样
"""

import os
import json
import math
import copy
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Callable
from dataclasses import dataclass, field
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class Task:
    task_id: str
    support_x: List[List[float]] = field(default_factory=list)
    support_y: List[int] = field(default_factory=list)
    query_x: List[List[float]] = field(default_factory=list)
    query_y: List[int] = field(default_factory=list)

@dataclass
class SimpleModel:
    weights: List[float] = field(default_factory=list)
    bias: float = 0.0
    lr: float = 0.01
    
    def predict(self, x: List[float]) -> float:
        return sum(w * xi for w, xi in zip(self.weights, x)) + self.bias
    
    def gradient_step(self, x: List[float], target: float):
        pred = self.predict(x)
        error = pred - target
        for i in range(len(self.weights)):
            self.weights[i] -= self.lr * error * x[i]
        self.bias -= self.lr * error

@dataclass
class MAMLConfig:
    inner_lr: float = 0.01
    outer_lr: float = 0.001
    n_inner_steps: int = 5
    n_tasks_per_batch: int = 4
    n_meta_epochs: int = 10


class MAML:
    """Model-Agnostic Meta-Learning"""
    def __init__(self, config: MAMLConfig = None):
        self.config = config or MAMLConfig()
        self.meta_model = SimpleModel(weights=[0.5]*3, lr=self.config.inner_lr)
        self.loss_history: List[float] = []
    
    def inner_adapt(self, task: Task, init_model: SimpleModel) -> SimpleModel:
        adapted = copy.deepcopy(init_model)
        for _ in range(self.config.n_inner_steps):
            for x, y in zip(task.support_x, task.support_y):
                adapted.gradient_step(x, float(y))
        return adapted
    
    def outer_update(self, tasks: List[Task]):
        meta_grad_w = [0.0] * len(self.meta_model.weights)
        meta_grad_b = 0.0
        
        for task in tasks:
            adapted = self.inner_adapt(task, self.meta_model)
            loss = 0.0
            for x, y in zip(task.query_x, task.query_y):
                pred = adapted.predict(x)
                loss += (pred - float(y)) ** 2
            loss /= max(len(task.query_x), 1)
            
            # Approximate meta-gradient
            for i in range(len(meta_grad_w)):
                meta_grad_w[i] += (adapted.weights[i] - self.meta_model.weights[i])
            meta_grad_b += (adapted.bias - self.meta_model.bias)
        
        n = len(tasks)
        for i in range(len(self.meta_model.weights)):
            self.meta_model.weights[i] -= self.config.outer_lr * meta_grad_w[i] / n
        self.meta_model.bias -= self.config.outer_lr * meta_grad_b / n


class ProtoNet:
    """Prototypical Networks for Few-Shot Classification"""
    def __init__(self, embedding_dim: int = 5):
        self.embedding_dim = embedding_dim
        self.prototypes: Dict[int, List[float]] = {}
    
    @staticmethod
    def euclidean_dist(a: List[float], b: List[float]) -> float:
        return math.sqrt(sum((x - y)**2 for x, y in zip(a, b)))
    
    def compute_prototypes(self, support_x: List[List[float]], support_y: List[int]):
        class_vectors = defaultdict(list)
        for x, y in zip(support_x, support_y):
            class_vectors[y].append(x)
        
        self.prototypes = {}
        for cls, vectors in class_vectors.items():
            dim = len(vectors[0])
            proto = [sum(v[i] for v in vectors) / len(vectors) for i in range(dim)]
            self.prototypes[cls] = proto
    
    def classify(self, query_x: List[float]) -> Tuple[int, Dict[int, float]]:
        scores = {}
        for cls, proto in self.prototypes.items():
            dist = self.euclidean_dist(query_x, proto)
            scores[cls] = 1.0 / (1.0 + dist)
        
        best_cls = max(scores, key=scores.get) if scores else -1
        return best_cls, scores


class TaskSampler:
    def __init__(self, n_classes: int = 5, n_samples_per_class: int = 10):
        self.n_classes = n_classes
        self.data = {}
        for c in range(n_classes):
            self.data[c] = [[math.sin(i + c*0.5), math.cos(i + c*0.3), (i+c)%5] 
                          for i in range(n_samples_per_class)]
    
    def sample_task(self, n_way: int = 3, k_shot: int = 2, n_query: int = 3) -> Task:
        import random
        classes = random.sample(list(self.data.keys()), min(n_way, len(self.data)))
        task = Task(task_id=f"task_{n_way}way_{k_shot}shot")
        
        for cls in classes:
            samples = random.sample(self.data[cls], min(k_shot + n_query, len(self.data[cls])))
            task.support_x.extend(samples[:k_shot])
            task.support_y.extend([cls] * k_shot)
            task.query_x.extend(samples[k_shot:k_shot+n_query])
            task.query_y.extend([cls] * n_query)
        
        return task


if __name__ == '__main__':
    print("=== MAML Meta-Training ===")
    config = MAMLConfig(inner_lr=0.05, outer_lr=0.01, n_inner_steps=3)
    maml = MAML(config)
    sampler = TaskSampler(n_classes=5)
    
    for epoch in range(5):
        tasks = [sampler.sample_task(n_way=3, k_shot=2, n_query=3) for _ in range(4)]
        maml.outer_update(tasks)
        print(f"Epoch {epoch}: meta_weights = {[f'{w:.3f}' for w in maml.meta_model.weights]}")
    
    print("\n=== ProtoNet Few-Shot ===")
    proto = ProtoNet()
    support_x = [[1.0, 2.0], [1.1, 1.9], [5.0, 5.0], [5.1, 4.9]]
    support_y = [0, 0, 1, 1]
    proto.compute_prototypes(support_x, support_y)
    
    query = [1.05, 2.05]
    pred, scores = proto.classify(query)
    print(f"Query {query} -> Class {pred}, scores: {scores}")
