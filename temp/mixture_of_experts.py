#!/usr/bin/env python3
"""Mixture of Experts: 混合专家模型"""
import math, random, logging
logging.basicConfig(level=logging.INFO)

class MoE:
    def __init__(self, n_experts=3, dim=4):
        self.n_experts = n_experts
        self.dim = dim
        self.experts = [[[random.gauss(0,0.3) for _ in range(dim)] for _ in range(dim)] for _ in range(n_experts)]
        self.gate_w = [[random.gauss(0,0.3) for _ in range(dim)] for _ in range(n_experts)]

    def gate(self, x):
        logits = [sum(x[i]*self.gate_w[e][i] for i in range(self.dim)) for e in range(self.n_experts)]
        mx = max(logits)
        exps = [math.exp(l-mx) for l in logits]
        s = sum(exps)
        return [e/s for e in exps]

    def forward(self, x):
        weights = self.gate(x)
        out = [0.0]*self.dim
        for e in range(self.n_experts):
            for i in range(self.dim):
                out[i] += weights[e]*sum(x[j]*self.experts[e][j][i] for j in range(self.dim))
        return out

if __name__ == "__main__":
    print("=== MoE Demo ===")
    moe = MoE(n_experts=3, dim=2)
    out = moe.forward([1, 0.5])
    print(f"Output: {[round(x,3) for x in out]}")
