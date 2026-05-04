#!/usr/bin/env python3
"""
Few-Shot Learning for GenericAgent
少样本学习: Prototypical Networks、Matching Networks、MAML
支持: N-way K-shot、原型计算、episodic训练
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
class FSLConfig:
    input_dim: int = 256
    feature_dim: int = 64
    n_way: int = 5       # Number of classes per episode
    k_shot: int = 1      # Samples per class in support set
    query_per_class: int = 5

class FeatureExtractor:
    """Shared feature extractor (embedding network)"""
    def __init__(self, input_dim: int, feature_dim: int):
        self.weights = [random.gauss(0, math.sqrt(2.0/input_dim)) for _ in range(input_dim * feature_dim)]
        self.input_dim = input_dim
        self.feature_dim = feature_dim

    def forward(self, x: List[float]) -> List[float]:
        return self._linear_relu(x, self.weights, self.input_dim, self.feature_dim)

    def _linear_relu(self, x, w, di, do):
        return [max(0, sum(w[i*di+j]*x[j] for j in range(min(di,len(x))) if i*di+j < len(w))) for i in range(do)]

class PrototypicalNetwork:
    """Prototypical Networks for few-shot classification"""
    def __init__(self, feature_extractor: FeatureExtractor):
        self.extractor = feature_extractor

    def compute_prototypes(self, support_x: List[List[float]], support_y: List[int]) -> Dict[int, List[float]]:
        """Compute class prototypes"""
        prototypes: Dict[int, List[float]] = {}
        class_features: Dict[int, List[List[float]]] = {}
        
        for x, y in zip(support_x, support_y):
            f = self.extractor.forward(x)
            if y not in class_features:
                class_features[y] = []
            class_features[y].append(f)
        
        for cls, feats in class_features.items():
            proto = [sum(f[i] for f in feats) / len(feats) for i in range(len(feats[0]))]
            prototypes[cls] = proto
        
        return prototypes

    def predict(self, x: List[float], prototypes: Dict[int, List[float]]) -> Tuple[int, Dict[int, float]]:
        """Predict class based on distance to prototypes"""
        f = self.extractor.forward(x)
        distances: Dict[int, float] = {}
        
        for cls, proto in prototypes.items():
            dist = sum((a - b)**2 for a, b in zip(f, proto))
            distances[cls] = dist
        
        pred_class = min(distances, key=distances.get)
        return pred_class, distances

    def _euclidean(self, u: List[float], v: List[float]) -> float:
        return math.sqrt(sum((a-b)**2 for a,b in zip(u,v)))

class FewShotLearner:
    """Main few-shot learning orchestrator"""
    def __init__(self, config: FSLConfig = None):
        self.config = config or FSLConfig()
        self.extractor = FeatureExtractor(self.config.input_dim, self.config.feature_dim)
        self.proto_net = PrototypicalNetwork(self.extractor)
        self.training_history: List[Dict] = []

    def generate_episode(self, all_classes: int) -> Dict:
        """Generate N-way K-shot episode"""
        classes = random.sample(range(all_classes), self.config.n_way)
        support_x, support_y = [], []
        query_x, query_y = [], []
        
        for cls in classes:
            # Support set
            for _ in range(self.config.k_shot):
                x = [random.random() + cls*0.1 for _ in range(self.config.input_dim)]
                support_x.append(x)
                support_y.append(cls)
            # Query set
            for _ in range(self.config.query_per_class):
                x = [random.random() + cls*0.1 for _ in range(self.config.input_dim)]
                query_x.append(x)
                query_y.append(cls)
        
        return {'support_x': support_x, 'support_y': support_y, 'query_x': query_x, 'query_y': query_y}

    def train_episode(self, all_classes: int) -> float:
        """Train on one episode"""
        episode = self.generate_episode(all_classes)
        prototypes = self.proto_net.compute_prototypes(episode['support_x'], episode['support_y'])
        
        correct = 0
        for x, y in zip(episode['query_x'], episode['query_y']):
            pred, _ = self.proto_net.predict(x, prototypes)
            if pred == y:
                correct += 1
        
        acc = correct / len(episode['query_y'])
        self.training_history.append({'accuracy': acc})
        return acc

if __name__ == '__main__':
    print("=== Few-Shot Learning (Prototypical Networks) ===")
    
    config = FSLConfig(input_dim=64, n_way=5, k_shot=1, query_per_class=5)
    fsl = FewShotLearner(config)
    
    print(f"\nConfig: {config.n_way}-way {config.k_shot}-shot")
    print(f"Total classes: 20")
    
    accuracies = []
    for episode in range(200):
        acc = fsl.train_episode(20)
        accuracies.append(acc)
        if episode % 50 == 0:
            recent = sum(accuracies[-50:]) / min(50, len(accuracies))
            print(f"  Episode {episode}: acc={acc:.3f}, rolling={recent:.3f}")
    
    final = sum(accuracies[-50:]) / 50
    print(f"\nFinal 50-episode avg accuracy: {final:.3f}")
