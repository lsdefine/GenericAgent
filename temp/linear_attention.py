#!/usr/bin/env python3
"""Linear Attention: 线性注意力机制"""
import math, random, logging
logging.basicConfig(level=logging.INFO)

class LinearAttention:
    def __init__(self, dim=4):
        self.dim = dim

    def elu_feature_map(self, x):
        return [max(0, xi) + 1 for xi in x]

    def forward(self, queries, keys, values):
        n = len(queries)
        Q = [self.elu_feature_map(q) for q in queries]
        K = [self.elu_feature_map(k) for k in keys]
        d = len(Q[0])
        KV = [sum(K[j][a]*values[j][b] for j in range(n)) for a in range(d) for b in range(len(values[0]))]
        out = []
        for i in range(n):
            row = [sum(Q[i][a]*KV[a*len(values[0])+b] for a in range(d)) for b in range(len(values[0]))]
            norm = sum(Q[i][a]*sum(K[j][a] for j in range(n)) for a in range(d))
            out.append([x/max(norm,1e-8) for x in row])
        return out

if __name__ == "__main__":
    print("=== Linear Attention Demo ===")
    la = LinearAttention(dim=2)
    Q = [[1,2],[0,1]]
    K = [[2,1],[1,0]]
    V = [[1],[0]]
    out = la.forward(Q, K, V)
    print(f"Output: {out}")
