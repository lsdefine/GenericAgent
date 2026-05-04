#!/usr/bin/env python3
"""Sparse Attention: 稀疏注意力"""
import math, random, logging
logging.basicConfig(level=logging.INFO)

class SparseAttention:
    def __init__(self, dim=4, window=2):
        self.dim = dim
        self.window = window

    def forward(self, seq):
        n = len(seq)
        attn = [[0]*n for _ in range(n)]
        for i in range(n):
            for j in range(max(0, i-self.window), min(n, i+self.window+1)):
                s = sum(seq[i][k]*seq[j][k] for k in range(self.dim))
                attn[i][j] = s / math.sqrt(self.dim)
        return attn

class SlidingWindowAttn(SparseAttention):
    def __init__(self, dim=4, window=1):
        super().__init__(dim, window)

if __name__ == "__main__":
    print("=== Sparse Attention Demo ===")
    sa = SparseAttention(dim=2, window=1)
    seq = [[1,0],[0,1],[1,1]]
    out = sa.forward(seq)
    print(f"Sparse attn: {out}")
