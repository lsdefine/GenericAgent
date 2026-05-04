#!/usr/bin/env python3
"""
Graph Attention Network (GAT) for GenericAgent
图注意力网络: 注意力机制图卷积、多头注意力、节点分类
支持: 邻接矩阵处理、注意力系数计算、多头聚合
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
class GATConfig:
    num_nodes: int = 100
    feature_dim: int = 16
    hidden_dim: int = 8
    num_classes: int = 7
    num_heads: int = 2
    dropout: float = 0.6
    alpha: float = 0.2  # LeakyReLU alpha

class AttentionHead:
    """Single attention head"""
    def __init__(self, feature_dim: int, hidden_dim: int, alpha: float = 0.2):
        self.feature_dim = feature_dim
        self.hidden_dim = hidden_dim
        self.alpha = alpha
        # Attention weights
        self.a = [random.gauss(0, 0.1) for _ in range(hidden_dim * 2)]

    def forward(self, h: List[List[float]], adj: List[List[int]]) -> List[List[float]]:
        """Compute attention-weighted node features"""
        n = len(h)
        # Project h to hidden dim (simplified linear)
        h_proj = []
        for node_h in h:
            proj = [sum(node_h[j] * math.sqrt(1.0/self.feature_dim) for j in range(min(self.feature_dim, len(node_h))))
                    for _ in range(self.hidden_dim)]
            h_proj.append(proj)

        # Compute attention coefficients
        attention = [[0.0]*n for _ in range(n)]
        for i in range(n):
            for j in adj[i]:
                if j < n:
                    # Concat h_i and h_j
                    concat = h_proj[i] + h_proj[j]
                    e = self._leaky_relu(sum(self.a[k]*concat[k] for k in range(min(len(concat), len(self.a)))))
                    attention[i][j] = e

        # Softmax
        new_h = []
        for i in range(n):
            neighbors = [j for j in adj[i] if j < n]
            if not neighbors:
                new_h.append(h_proj[i])
                continue
            exp_e = [math.exp(attention[i][j]) for j in neighbors]
            s = sum(exp_e)
            if s == 0:
                s = 1
            alpha = [e/s for e in exp_e]
            # Aggregate
            aggregated = [0.0] * self.hidden_dim
            for idx, j in enumerate(neighbors):
                for d in range(self.hidden_dim):
                    aggregated[d] += alpha[idx] * h_proj[j][d]
            new_h.append(aggregated)

        return new_h

    def _leaky_relu(self, x: float) -> float:
        return x if x > 0 else self.alpha * x

class GraphAttentionNetwork:
    """Multi-head GAT"""
    def __init__(self, config: GATConfig = None):
        self.config = config or GATConfig()
        self.heads = [AttentionHead(self.config.feature_dim, self.config.hidden_dim, self.config.alpha)
                      for _ in range(self.config.num_heads)]
        self.output_weights = [random.gauss(0, 0.1) for _ in range(self.config.hidden_dim * self.config.num_heads * self.config.num_classes)]
        self.training_history: List[Dict] = []

    def forward(self, h: List[List[float]], adj: List[List[int]]) -> List[List[float]]:
        """Forward pass with multi-head attention"""
        head_outputs = []
        for head in self.heads:
            head_out = head.forward(h, adj)
            head_outputs.append(head_out)

        # Concatenate heads
        n = len(h)
        concat_h = []
        for i in range(n):
            combined = []
            for ho in head_outputs:
                if i < len(ho):
                    combined.extend(ho[i])
            concat_h.append(combined)

        # Output layer (classification)
        logits = []
        for node_h in concat_h:
            node_logits = []
            for c in range(self.config.num_classes):
                score = sum(self.output_weights[c*len(node_h)+j]*node_h[j] for j in range(min(len(node_h), len(self.output_weights)//self.config.num_classes)))
                node_logits.append(score)
            logits.append(node_logits)

        return logits

    def predict(self, logits: List[List[float]]) -> List[int]:
        return [max(range(len(l)), key=lambda i: l[i]) for l in logits]

if __name__ == '__main__':
    print("=== Graph Attention Network ===")
    
    config = GATConfig(num_nodes=20, feature_dim=8, num_classes=3, num_heads=2)
    gat = GraphAttentionNetwork(config)
    
    # Create synthetic graph
    h = [[random.random() for _ in range(config.feature_dim)] for _ in range(config.num_nodes)]
    adj = [[] for _ in range(config.num_nodes)]
    for i in range(config.num_nodes):
        neighbors = random.sample(range(config.num_nodes), min(3, config.num_nodes-1))
        adj[i] = neighbors

    print(f"Nodes: {config.num_nodes}, Edges: {sum(len(a) for a in adj)//2}")
    print(f"Heads: {config.num_heads}, Classes: {config.num_classes}")

    logits = gat.forward(h, adj)
    preds = gat.predict(logits)
    print(f"\nPredicted classes for first 5 nodes: {preds[:5]}")
    print(f"GAT forward pass successful")
