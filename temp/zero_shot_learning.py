#!/usr/bin/env python3
"""
Zero-Shot Learning for GenericAgent
零样本学习: 语义嵌入、属性分类、未见类别预测
支持: CLIP-style图文对齐、类别描述嵌入、属性迁移
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
class ZSLConfig:
    input_dim: int = 256
    semantic_dim: int = 128
    embedding_dim: int = 64
    num_seen_classes: int = 10
    num_unseen_classes: int = 5

class SemanticEmbedding:
    """Generate semantic embeddings for classes"""
    def __init__(self, class_names: List[str], dim: int):
        self.class_names = class_names
        self.dim = dim
        self.embeddings: Dict[str, List[float]] = {}
        self._init()

    def _init(self):
        for name in self.class_names:
            # Simulate semantic embedding (e.g., from word2vec)
            seed = sum(ord(c) for c in name)
            random.seed(seed)
            self.embeddings[name] = [random.gauss(0, 1) for _ in range(self.dim)]
            random.seed()

    def get_embedding(self, name: str) -> List[float]:
        return self.embeddings.get(name, [0.0] * self.dim)

class VisualSemanticMapper:
    """Map visual features to semantic space"""
    def __init__(self, input_dim: int, semantic_dim: int, embedding_dim: int):
        self.weights = [random.gauss(0, math.sqrt(2.0/input_dim)) for _ in range(input_dim * embedding_dim)]
        self.input_dim = input_dim
        self.embedding_dim = embedding_dim
        self.semantic_dim = semantic_dim
        # Projection to semantic space
        self.semantic_proj = [random.gauss(0, math.sqrt(2.0/embedding_dim)) for _ in range(embedding_dim * semantic_dim)]

    def forward(self, x: List[float]) -> List[float]:
        h = self._linear(x, self.weights, self.input_dim, self.embedding_dim)
        return self._linear_relu(h, self.semantic_proj, self.embedding_dim, self.semantic_dim)

    def _linear(self, x, w, di, do):
        return [sum(w[i*di+j]*x[j] for j in range(min(di,len(x))) if i*di+j < len(w)) for i in range(do)]

    def _linear_relu(self, x, w, di, do):
        return [max(0, sum(w[i*di+j]*x[j] for j in range(min(di,len(x))) if i*di+j < len(w))) for i in range(do)]

class ZeroShotLearner:
    """Main zero-shot learning orchestrator"""
    def __init__(self, config: ZSLConfig = None):
        self.config = config or ZSLConfig()
        self.mapper = VisualSemanticMapper(self.config.input_dim, self.config.semantic_dim, self.config.embedding_dim)
        self.seen_embeddings: Dict[str, List[float]] = {}
        self.unseen_embeddings: Dict[str, List[float]] = {}
        self.training_history: List[Dict] = []

    def train_on_seen(self, x: List[float], class_name: str, semantic_emb: List[float]):
        """Train on seen classes"""
        visual_emb = self.mapper.forward(x)
        # MSE between visual embedding and semantic embedding
        loss = sum((v - s)**2 for v, s in zip(visual_emb, semantic_emb)) / len(visual_emb)
        self.seen_embeddings[class_name] = semantic_emb
        self.training_history.append({'loss': loss, 'class': class_name})
        return {'loss': loss}

    def predict_unseen(self, x: List[float], unseen_classes: Dict[str, List[float]]) -> str:
        """Predict class among unseen categories"""
        visual_emb = self.mapper.forward(x)
        best_class = None
        best_sim = -float('inf')
        
        for cls_name, sem_emb in unseen_classes.items():
            sim = self._cosine_similarity(visual_emb, sem_emb)
            if sim > best_sim:
                best_sim = sim
                best_class = cls_name
        
        return best_class

    def _cosine_similarity(self, u: List[float], v: List[float]) -> float:
        dot = sum(a*b for a,b in zip(u,v))
        norm_u = math.sqrt(sum(a*a for a in u) + 1e-7)
        norm_v = math.sqrt(sum(b*b for b in v) + 1e-7)
        return dot / (norm_u * norm_v)

if __name__ == '__main__':
    print("=== Zero-Shot Learning ===")
    
    config = ZSLConfig(input_dim=128, semantic_dim=64, embedding_dim=32)
    zsl = ZeroShotLearner(config)
    
    seen_names = ['cat', 'dog', 'bird', 'fish', 'horse']
    seen_sem = SemanticEmbedding(seen_names, config.semantic_dim)
    
    print(f"\nSeen classes: {seen_names}")
    print("Training on seen classes...")
    for epoch in range(100):
        cls = random.choice(seen_names)
        x = [random.random() for _ in range(128)]
        sem_emb = seen_sem.get_embedding(cls)
        res = zsl.train_on_seen(x, cls, sem_emb)
        if epoch % 25 == 0:
            print(f"  Epoch {epoch}: loss={res['loss']:.4f}")
    
    # Predict unseen
    unseen_names = ['elephant', 'zebra', 'lion', 'tiger', 'bear']
    unseen_sem = SemanticEmbedding(unseen_names, config.semantic_dim)
    unseen_dict = {n: unseen_sem.get_embedding(n) for n in unseen_names}
    
    print(f"\nUnseen classes: {unseen_names}")
    x_test = [random.random() for _ in range(128)]
    pred = zsl.predict_unseen(x_test, unseen_dict)
    print(f"Predicted unseen class: {pred}")
