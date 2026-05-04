#!/usr/bin/env python3
"""Attention Extension: 注意力机制扩展"""
import math, random, logging
logging.basicConfig(level=logging.INFO)

class MultiQueryAttention:
    def __init__(self, d_model=8, n_heads=2):
        self.d = d_model
        self.h = n_heads
        self.dk = d_model // n_heads
        self.Wq = [[random.gauss(0,0.2) for _ in range(d_model)] for _ in range(d_model)]
        self.Wv = [random.gauss(0,0.2) for _ in range(d_model)]

    def forward(self, x):
        n = len(x)
        # Project Q, K, V
        Q = [[sum(x[i][k]*self.Wq[k][j] for k in range(self.d)) for j in range(self.dk*self.h)] for i in range(n)]
        V = [sum(x[i][k]*self.Wv[k] for k in range(self.d)) for i in range(n)]
        # Scaled dot-product
        attn = [[0]*n for _ in range(n)]
        for i in range(n):
            for j in range(n):
                s = sum(Q[i][k]*Q[j][k] for k in range(self.dk*self.h))
                attn[i][j] = s / math.sqrt(self.dk*self.h)
        return {"attn_weights": attn, "values": V}

if __name__ == "__main__":
    print("=== Attention Extension Demo ===")
    mqa = MultiQueryAttention(d_model=4, n_heads=2)
    x = [[1,0,1,0],[0,1,0,1],[1,1,0,0]]
    out = mqa.forward(x)
    print(f"Attn shape: {len(out['attn_weights'])}x{len(out['attn_weights'][0])}")
