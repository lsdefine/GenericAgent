#!/usr/bin/env python3
"""Contrastive Multimodal Learning"""
import math, random, logging
logging.basicConfig(level=logging.INFO)

class ContrastiveMultimodal:
    def __init__(self, temperature=0.07):
        self.temperature = temperature

    def compute_logits(self, x1, x2, x2_neg):
        pos = sum(a*b for a,b in zip(x1, x2)) / self.temperature
        negs = [sum(a*b for a,b in zip(x1, xn)) / self.temperature for xn in x2_neg]
        max_neg = max(negs)
        log_sum_exp = max_neg + math.log(sum(math.exp(n - max_neg) for n in negs))
        return pos - log_sum_exp

if __name__ == "__main__":
    cm = ContrastiveMultimodal()
    x1 = [random.gauss(0,1) for _ in range(128)]
    x2 = [v + random.gauss(0,0.1) for v in x1]
    negs = [[random.gauss(0,1) for _ in range(128)] for _ in range(3)]
    loss = -cm.compute_logits(x1, x2, negs)
    logging.info(f"Contrastive Multimodal loss: {loss:.4f}")
