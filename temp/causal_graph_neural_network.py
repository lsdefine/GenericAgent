#!/usr/bin/env python3
"""Causal GNN: 结合因果结构的图神经网络"""
import os, math, random, logging
from typing import Dict, List, Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class CausalGNNLayer:
    def __init__(self, in_dim, out_dim, alpha=0.5):
        self.in_dim, self.out_dim = in_dim, out_dim
        self.alpha = alpha  # 因果传播权重
        self.W = [[random.gauss(0, 0.1) for _ in range(out_dim)] for _ in range(in_dim)]

    def forward(self, node_features, adj_matrix):
        n = len(node_features)
        output = []
        for i in range(n):
            # 因果聚合: 只聚合因果父节点
            causal_sum = [0.0]*self.out_dim
            for j in range(n):
                if adj_matrix[j][i] > 0:
                    for k in range(self.out_dim):
                        val = sum(node_features[j][d]*self.W[d][k] for d in range(self.in_dim))
                        causal_sum[k] += adj_matrix[j][i]*val
            output.append(causal_sum)
        return output

class CausalGNN:
    def __init__(self, dims, alpha=0.5):
        self.layers = [CausalGNNLayer(dims[i], dims[i+1], alpha) for i in range(len(dims)-1)]

    def forward(self, features, adj):
        x = features
        for layer in self.layers:
            x = layer.forward(x, adj)
        return x

    def intervene(self, features, adj, target_node, value):
        """干预节点: 设置目标节点特征为固定值"""
        intervened = [f[:] for f in features]
        intervened[target_node] = value
        return self.forward(intervened, adj)

if __name__ == "__main__":
    print("=== Causal GNN Demo ===")
    gnn = CausalGNN([4, 8, 2])
    features = [[random.random() for _ in range(4)] for _ in range(5)]
    adj = [[1 if j==i else random.choice([0,1]) for j in range(5)] for i in range(5)]
    out = gnn.forward(features, adj)
    print(f"Output shape: {len(out)}x{len(out[0])}")
