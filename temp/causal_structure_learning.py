#!/usr/bin/env python3
"""Causal Structure Learning: 因果结构学习"""
import math, random, logging
logging.basicConfig(level=logging.INFO)

class StructureLearner:
    def __init__(self, n_vars, seed=42):
        random.seed(seed)
        self.n_vars = n_vars
        self.adjacency = [[0]*n_vars for _ in range(n_vars)]
        self.scores = [[0.0]*n_vars for _ in range(n_vars)]

    def score_edge(self, x, y, data):
        """Simple correlation-based score"""
        cov = sum(a*b for a,b in zip(data[x], data[y])) / len(data[x])
        return abs(cov)

    def learn(self, data):
        for i in range(self.n_vars):
            for j in range(self.n_vars):
                if i != j:
                    self.scores[i][j] = self.score_edge(i, j, data)
        # Threshold
        for i in range(self.n_vars):
            for j in range(self.n_vars):
                if self.scores[i][j] > 0.3:
                    self.adjacency[i][j] = 1
        return self.adjacency

if __name__ == "__main__":
    print("=== Causal Structure Learning Demo ===")
    sl = StructureLearner(n_vars=4)
    data = {i: [random.gauss(0,1) for _ in range(50)] for i in range(4)}
    adj = sl.learn(data)
    print(f"Edges found: {sum(sum(row) for row in adj)}")
