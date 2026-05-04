#!/usr/bin/env python3
"""Meta-Causal Discovery: 跨任务学习因果结构先验"""
import os, math, random, logging
from typing import Dict, List, Tuple
from dataclasses import dataclass

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class MetaCausalLearner:
    def __init__(self, n_vars=5, seed=42):
        self.n_vars = n_vars
        random.seed(seed)
        self.prior_probs = [[0.5]*n_vars for _ in range(n_vars)]
        self.task_history = []

    def discover_causal(self, data: List[List[float]], threshold=0.3):
        adj = [[0]*self.n_vars for _ in range(self.n_vars)]
        for i in range(self.n_vars):
            for j in range(self.n_vars):
                if i == j: continue
                corr = self._compute_corr([d[i] for d in data], [d[j] for d in data])
                adj[i][j] = 1 if abs(corr) > threshold else 0
        self.task_history.append(adj)
        self._update_prior()
        return adj

    def predict_causal_prior(self):
        return [row[:] for row in self.prior_probs]

    def _update_prior(self):
        if not self.task_history: return
        n = len(self.task_history)
        for i in range(self.n_vars):
            for j in range(self.n_vars):
                self.prior_probs[i][j] = sum(t[i][j] for t in self.task_history) / n

    def _compute_corr(self, x, y):
        n = len(x)
        if n == 0: return 0
        mx = sum(x)/n
        my = sum(y)/n
        num = sum((x[i]-mx)*(y[i]-my) for i in range(n))
        dx = math.sqrt(sum((xi-mx)**2 for xi in x)+1e-8)
        dy = math.sqrt(sum((yi-my)**2 for yi in y)+1e-8)
        return num/(dx*dy)

if __name__ == "__main__":
    print("=== Meta-Causal Discovery Demo ===")
    learner = MetaCausalLearner(n_vars=4)
    for t in range(3):
        data = [[random.gauss(0,1) for _ in range(4)] for _ in range(100)]
        for d in data: d[1] = 0.5*d[0] + random.gauss(0,0.2)
        adj = learner.discover_causal(data)
        print(f"Task {t}: edges found = {sum(sum(r) for r in adj)}")
    print(f"Causal prior: {learner.predict_causal_prior()[0][1]:.3f}")
