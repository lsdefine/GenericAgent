#!/usr/bin/env python3
"""Graph Transformer for GenericAgent"""
import math, random, logging
logging.basicConfig(level=logging.INFO)

class GraphAttention:
    def __init__(self, dim, n_heads=2):
        self.dim = dim
        self.n_heads = n_heads
        self.qkv_w = [[random.gauss(0, 0.3) for _ in range(dim)] for _ in range(dim*3)]

    def forward(self, H, adj):
        n = len(H)
        # Simple attention with adjacency mask
        attn = [[0.0]*n for _ in range(n)]
        for i in range(n):
            for j in range(n):
                if adj[i][j] > 0:
                    dot = sum(H[i][d]*H[j][d] for d in range(self.dim))
                    attn[i][j] = max(0, dot / math.sqrt(self.dim))
            # Softmax row
            max_a = max(attn[i])
            exps = [math.exp(a - max_a) for a in attn[i]]
            s = sum(exps)
            attn[i] = [e/s for e in exps]
        # Aggregate
        new_H = [[0.0]*self.dim for _ in range(n)]
        for i in range(n):
            for j in range(n):
                if attn[i][j] > 0:
                    for d in range(self.dim):
                        new_H[i][d] += attn[i][j] * H[j][d]
        return new_H

class GraphTransformer:
    def __init__(self, dim, n_heads=2, n_layers=2):
        self.layers = [GraphAttention(dim, n_heads) for _ in range(n_layers)]

    def forward(self, adj, H):
        for layer in self.layers:
            H = layer.forward(H, adj)
        return H

if __name__ == "__main__":
    print("=== Graph Transformer Demo ===")
    adj = [[0,1,1],[1,0,1],[1,1,0]]
    H = [[1,0,1],[0,1,0],[1,1,1]]
    gt = GraphTransformer(dim=3, n_heads=2, n_layers=2)
    out = gt.forward(adj, H)
    print(f"Graph Transformer output: {len(out)} nodes")
