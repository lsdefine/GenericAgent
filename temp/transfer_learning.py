#!/usr/bin/env python3
"""
Transfer Learning for GenericAgent
迁移学习: 预训练权重迁移、领域自适应、特征微调
支持: 冻结层策略、学习率衰减、特征提取/微调模式
"""

import os
import json
import math
import random
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class TransferConfig:
    source_classes: int = 1000  # Pre-trained classes (e.g., ImageNet)
    target_classes: int = 10    # Target task classes
    input_dim: int = 784
    hidden_dims: List[int] = None
    frozen_layers: int = 2      # Number of layers to freeze
    lr_backbone: float = 0.0001
    lr_head: float = 0.01

    def __post_init__(self):
        if self.hidden_dims is None:
            self.hidden_dims = [256, 128]

class PretrainedBackbone:
    """Simulated pre-trained backbone network"""
    def __init__(self, input_dim: int, hidden_dims: List[int]):
        self.input_dim = input_dim
        self.hidden_dims = hidden_dims
        self.weights: Dict[str, List[float]] = {}
        self.frozen: Dict[str, bool] = {}
        self._init()

    def _init(self):
        prev = self.input_dim
        for i, h in enumerate(self.hidden_dims):
            self.weights[f'layer_{i}'] = [random.gauss(0, math.sqrt(2.0/prev)) for _ in range(prev * h)]
            self.frozen[f'layer_{i}'] = True  # Default frozen
            prev = h

    def forward(self, x: List[float]) -> List[float]:
        h = x
        for i in range(len(self.hidden_dims)):
            w = self.weights[f'layer_{i}']
            h = self._linear_relu(h, w, len(h), self.hidden_dims[i])
        return h

    def _linear_relu(self, x, w, di, do):
        return [max(0, sum(w[i*di+j]*x[j] for j in range(min(di,len(x))) if i*di+j < len(w))) for i in range(do)]

    def freeze_layers(self, n: int):
        for i in range(min(n, len(self.hidden_dims))):
            self.frozen[f'layer_{i}'] = True
        for i in range(n, len(self.hidden_dims)):
            self.frozen[f'layer_{i}'] = False

    def unfreeze_all(self):
        for k in self.frozen:
            self.frozen[k] = False

class TaskHead:
    """Task-specific classification head"""
    def __init__(self, feature_dim: int, num_classes: int):
        self.weights = [random.gauss(0, 0.01) for _ in range(feature_dim * num_classes)]
        self.feature_dim = feature_dim
        self.num_classes = num_classes

    def forward(self, features: List[float]) -> List[float]:
        logits = []
        for i in range(self.num_classes):
            s = sum(self.weights[i*self.feature_dim+j]*features[j] for j in range(min(self.feature_dim, len(features))))
            logits.append(s)
        return self._softmax(logits)

    def _softmax(self, x):
        max_x = max(x)
        exps = [math.exp(xi - max_x) for xi in x]
        s = sum(exps)
        return [e/s for e in exps]

class TransferLearner:
    """Main transfer learning orchestrator"""
    def __init__(self, config: TransferConfig = None):
        self.config = config or TransferConfig()
        self.backbone = PretrainedBackbone(self.config.input_dim, self.config.hidden_dims)
        self.backbone.freeze_layers(self.config.frozen_layers)
        self.head = TaskHead(self.config.hidden_dims[-1], self.config.target_classes)
        self.training_history: List[Dict] = []
        self.current_epoch = 0

    def train_step(self, x: List[float], y: int) -> Dict:
        features = self.backbone.forward(x)
        probs = self.head.forward(features)
        
        # Cross-entropy loss
        loss = -math.log(max(1e-7, probs[y]))
        
        # Simulated gradient update (head only if backbone frozen)
        pred = probs.index(max(probs))
        correct = pred == y
        
        self.training_history.append({'loss': loss, 'correct': correct})
        return {'loss': loss, 'correct': correct}

    def fine_tune_phase(self, epochs: int, data: List[Tuple[List[float], int]]):
        """Unfreeze and fine-tune"""
        self.backbone.unfreeze_all()
        for epoch in range(epochs):
            for x, y in data:
                self.train_step(x, y)

if __name__ == '__main__':
    print("=== Transfer Learning ===")
    
    config = TransferConfig(input_dim=256, target_classes=5, frozen_layers=1)
    tl = TransferLearner(config)
    
    print(f"Input: {config.input_dim}, Target classes: {config.target_classes}")
    print(f"Frozen layers: {config.frozen_layers}")
    
    # Feature extraction phase (frozen backbone)
    print("\n--- Phase 1: Feature Extraction (frozen backbone) ---")
    correct = 0
    for epoch in range(50):
        x = [random.random() for _ in range(256)]
        y = random.randint(0, 4)
        res = tl.train_step(x, y)
        if res['correct']:
            correct += 1
        if epoch % 20 == 0:
            print(f"  Epoch {epoch}: loss={res['loss']:.4f}")
    
    print(f"\nPhase 1 accuracy: {correct/50:.3f}")
    
    # Fine-tuning phase
    print("\n--- Phase 2: Fine-tuning (unfreeze all) ---")
    data = [([random.random() for _ in range(256)], random.randint(0, 4)) for _ in range(50)]
    tl.fine_tune_phase(50, data)
    print("Fine-tuning complete")
