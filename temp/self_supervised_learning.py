#!/usr/bin/env python3
"""
Self-Supervised Learning for GenericAgent
自监督学习: 数据增强、预训练任务、特征学习
支持: 旋转预测、拼图(Jigsaw)、掩码建模、上下文预测
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
class SSLConfig:
    input_dim: int = 784
    feature_dim: int = 128
    hidden_dims: List[int] = None
    learning_rate: float = 0.001
    pretext_task: str = 'rotation'  # rotation, jigsaw, masking
    
    def __post_init__(self):
        if self.hidden_dims is None:
            self.hidden_dims = [256, 128]


class DataAugmentation:
    """Data augmentation for self-supervised learning"""
    @staticmethod
    def rotate(x: List[float], angle: int) -> List[float]:
        """Rotate representation (simulated for 1D)"""
        n = len(x)
        shift = int(n * angle / 360)
        return x[shift:] + x[:shift]
    
    @staticmethod
    def mask_random(x: List[float], mask_ratio: float = 0.15) -> Tuple[List[float], List[int]]:
        """Random masking (like BERT)"""
        masked = x.copy()
        mask_indices = random.sample(range(len(x)), int(len(x) * mask_ratio))
        for i in mask_indices:
            masked[i] = 0.0
        return masked, mask_indices
    
    @staticmethod
    def jigsaw(x: List[float], n_patches: int = 4) -> Tuple[List[List[float]], List[int]]:
        """Split into patches and shuffle"""
        patch_size = len(x) // n_patches
        patches = [x[i*patch_size:(i+1)*patch_size] for i in range(n_patches)]
        perm = list(range(n_patches))
        random.shuffle(perm)
        shuffled = [patches[p] for p in perm]
        return shuffled, perm


class FeatureExtractor:
    """Shared backbone network"""
    def __init__(self, input_dim: int, hidden_dims: List[int], feature_dim: int):
        self.input_dim = input_dim
        self.hidden_dims = hidden_dims
        self.feature_dim = feature_dim
        self.weights: Dict[str, List[float]] = {}
        self._init()
    
    def _init(self):
        prev = self.input_dim
        for i, h in enumerate(self.hidden_dims):
            self.weights[f'fe_{i}'] = [random.gauss(0, math.sqrt(2.0/prev)) for _ in range(prev * h)]
            prev = h
        self.weights['fe_head'] = [random.gauss(0, math.sqrt(2.0/prev)) for _ in range(prev * self.feature_dim)]
    
    def forward(self, x: List[float]) -> List[float]:
        h = x
        for i in range(len(self.hidden_dims)):
            w = self.weights[f'fe_{i}']
            di, do = len(h), self.hidden_dims[i]
            h = self._linear_relu(h, w, di, do)
        w = self.weights['fe_head']
        return self._linear(h, w, len(h), self.feature_dim)
    
    def _linear_relu(self, x, w, di, do):
        return [max(0, sum(w[i*di+j]*x[j] for j in range(min(di,len(x))) if i*di+j < len(w))) for i in range(do)]
    
    def _linear(self, x, w, di, do):
        return [sum(w[i*di+j]*x[j] for j in range(min(di,len(x))) if i*di+j < len(w)) for i in range(do)]


class RotationPredictor:
    """Pretext task: predict rotation angle"""
    def __init__(self, feature_dim: int):
        self.weights = [random.gauss(0, 0.1) for _ in range(feature_dim * 4)]
    
    def forward(self, features: List[float]) -> List[float]:
        logits = []
        for i in range(4):
            s = sum(self.weights[i*len(features)+j]*features[j] for j in range(min(len(features), len(self.weights)//4)))
            logits.append(s)
        return self._softmax(logits)
    
    def _softmax(self, x):
        max_x = max(x)
        exps = [math.exp(xi - max_x) for xi in x]
        s = sum(exps)
        return [e/s for e in exps]


class SelfSupervisedLearner:
    """Main self-supervised learning orchestrator"""
    def __init__(self, config: SSLConfig = None):
        self.config = config or SSLConfig()
        self.feature_extractor = FeatureExtractor(self.config.input_dim, self.config.hidden_dims, self.config.feature_dim)
        self.task_heads: Dict = {}
        self._init_task_heads()
        self.training_history: List[Dict] = []
    
    def _init_task_heads(self):
        if self.config.pretext_task == 'rotation':
            self.task_heads['rotation'] = RotationPredictor(self.config.feature_dim)
    
    def train_step(self, x: List[float]) -> Dict:
        """Single training step"""
        if self.config.pretext_task == 'rotation':
            return self._train_rotation(x)
        elif self.config.pretext_task == 'masking':
            return self._train_masking(x)
        return {}
    
    def _train_rotation(self, x: List[float]) -> Dict:
        angle = random.choice([0, 90, 180, 270])
        x_rot = DataAugmentation.rotate(x, angle)
        features = self.feature_extractor.forward(x_rot)
        logits = self.task_heads['rotation'].forward(features)
        
        label_idx = [0, 90, 180, 270].index(angle)
        loss = -math.log(max(1e-7, logits[label_idx]))
        
        self.training_history.append({'task': 'rotation', 'loss': loss, 'pred': logits.index(max(logits)), 'true': label_idx})
        return {'loss': loss, 'predicted': logits.index(max(logits)), 'true': label_idx}
    
    def _train_masking(self, x: List[float]) -> Dict:
        masked, mask_indices = DataAugmentation.mask_random(x, mask_ratio=0.15)
        features = self.feature_extractor.forward(masked)
        
        # Simulated reconstruction loss
        loss = sum((x[i] - features[i % len(features)])**2 for i in mask_indices) / len(mask_indices)
        self.training_history.append({'task': 'masking', 'loss': loss})
        return {'loss': loss}
    
    def extract_features(self, x: List[float]) -> List[float]:
        """Extract features for downstream tasks"""
        return self.feature_extractor.forward(x)


if __name__ == '__main__':
    print("=== Self-Supervised Learning ===")
    
    # Rotation prediction
    config = SSLConfig(pretext_task='rotation', input_dim=256, feature_dim=64)
    ssl = SelfSupervisedLearner(config)
    
    print(f"\nPretext task: {config.pretext_task}")
    
    correct = 0
    for epoch in range(100):
        x = [random.random() for _ in range(256)]
        result = ssl.train_step(x)
        if result.get('predicted') == result.get('true'):
            correct += 1
        if epoch % 20 == 0:
            print(f"  Epoch {epoch}: loss={result['loss']:.4f}, acc_so_far={correct/(epoch+1):.3f}")
    
    print(f"\nFinal accuracy: {correct/100:.3f}")
    
    # Feature extraction
    features = ssl.extract_features([random.random() for _ in range(256)])
    print(f"Extracted {len(features)}-dim features")
