#!/usr/bin/env python3
"""Causal Embedding Model: 因果嵌入表示"""
import math, random, logging
logging.basicConfig(level=logging.INFO)

class CausalEmbedder:
    def __init__(self, n_concepts, dim=8, seed=42):
        random.seed(seed)
        self.n_concepts = n_concepts
        self.dim = dim
        self.embeddings = {i: [random.gauss(0, 1) for _ in range(dim)] for i in range(n_concepts)}

    def cosine_sim(self, i, j):
        a, b = self.embeddings[i], self.embeddings[j]
        dot = sum(x*y for x,y in zip(a,b))
        na = math.sqrt(sum(x*x for x in a))
        nb = math.sqrt(sum(x*x for x in b))
        return dot / max(na*nb, 1e-8)

    def train(self, pairs, lr=0.01):
        """Pull similar, push dissimilar"""
        for i, j, similar in pairs:
            sim = self.cosine_sim(i, j)
            target = 1.0 if similar else 0.0
            grad = sim - target
            for d in range(self.dim):
                self.embeddings[i][d] -= lr * grad * self.embeddings[j][d]
                self.embeddings[j][d] -= lr * grad * self.embeddings[i][d]

if __name__ == "__main__":
    print("=== Causal Embedding Model Demo ===")
    ce = CausalEmbedder(n_concepts=5, dim=4)
    ce.train([(0,1,True), (0,2,False), (1,2,False)], lr=0.05)
    print(f"Sim(0,1): {ce.cosine_sim(0,1):.3f}")
