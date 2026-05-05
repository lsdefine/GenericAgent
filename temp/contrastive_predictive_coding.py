#!/usr/bin/env python3
"""Contrastive Predictive Coding"""
import math, random, logging
logging.basicConfig(level=logging.INFO)

class ContrastivePredictiveCoding:
    def __init__(self, hidden_dim=8):
        self.hidden_dim = hidden_dim
        self.context = [0.0]*hidden_dim

    def encode_step(self, x):
        self.context = [self.context[i]*0.9 + x[i%len(x)]*0.1 for i in range(self.hidden_dim)]
        return self.context

    def predict_next(self):
        return [c*1.1 for c in self.context]

    def contrastive_loss(self, true_next, predicted, n_negatives=4):
        pos_sim = sum(t*p for t,p in zip(true_next, predicted))
        neg_sims = [sum(random.gauss(0,1) for _ in range(self.hidden_dim)) for _ in range(n_negatives)]
        denom = math.exp(pos_sim) + sum(math.exp(n) for n in neg_sims)
        return -math.log(max(math.exp(pos_sim)/denom, 1e-8))

if __name__ == "__main__":
    cpc = ContrastivePredictiveCoding()
    for _ in range(10):
        x = [random.gauss(0,1) for _ in range(8)]
        cpc.encode_step(x)
    pred = cpc.predict_next()
    true = [random.gauss(0,1) for _ in range(8)]
    loss = cpc.contrastive_loss(true, pred)
    logging.info(f"CPC: loss={loss:.3f}")
