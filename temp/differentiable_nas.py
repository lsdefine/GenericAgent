#!/usr/bin/env python3
"""Differentiable Neural Architecture Search"""
import math, random, logging
logging.basicConfig(level=logging.INFO)

class DifferentiableNAS:
    def __init__(self, n_ops=4, dim=8):
        self.n_ops = n_ops
        self.dim = dim
        self.alpha = [[random.gauss(0,0.1) for _ in range(n_ops)] for _ in range(dim)]

    def softmax(self, logits):
        m = max(logits)
        e = [math.exp(x-m) for x in logits]
        s = sum(e)
        return [x/s for x in e]

    def sample_arch(self):
        arch = []
        for row in self.alpha:
            probs = self.softmax(row)
            r = random.random()
            cum = 0
            for i, p in enumerate(probs):
                cum += p
                if r <= cum:
                    arch.append(i)
                    break
            else:
                arch.append(len(probs)-1)
        return arch

    def update(self, val_loss, lr=0.01):
        for row in self.alpha:
            for j in range(len(row)):
                row[j] -= lr * (random.gauss(0,0.1) + val_loss * 0.1)
        return sum(sum(r) for r in self.alpha)

if __name__ == "__main__":
    nas = DifferentiableNAS()
    arch = nas.sample_arch()
    v = nas.update(0.5)
    logging.info(f"DNAS: arch={arch}, val={v:.4f}")
