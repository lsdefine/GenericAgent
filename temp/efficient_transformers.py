#!/usr/bin/env python3
"""Efficient Transformers: 高效Transformer"""
import math, random, logging
logging.basicConfig(level=logging.INFO)

class PerformerAttention:
    def __init__(self, dim=4, m=2):
        self.dim = dim
        self.m = m

    def feature_map(self, x):
        return [math.exp(-xi**2/2)*math.cos(xi*random.gauss(0,1)) for xi in x]

    def forward(self, seq):
        n = len(seq)
        F = [self.feature_map(s) for s in seq]
        G = [[sum(F[i][a]*F[j][a] for a in range(self.m)) for j in range(n)] for i in range(n)]
        return G

if __name__ == "__main__":
    print("=== Performer Demo ===")
    pa = PerformerAttention(dim=4, m=2)
    seq = [[1,0,0,1],[0,1,1,0]]
    out = pa.forward(seq)
    print(f"Attn matrix: {out}")
