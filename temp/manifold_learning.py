#!/usr/bin/env python3
"""Manifold Learning: 流形学习"""
import math, random, logging
logging.basicConfig(level=logging.INFO)

class ManifoldLearner:
    def __init__(self, dim=2):
        self.dim = dim

    def local_linear_embedding(self, points, k=3):
        n = len(points)
        d = len(points[0])
        embedded = []
        for i in range(n):
            dists = [(sum((points[i][j]-points[m][j])**2 for j in range(d)), m) for m in range(n) if m!=i]
            dists.sort()
            neighbors = [m for _, m in dists[:k]]
            emb = [0.0]*self.dim
            for nb in neighbors:
                for j in range(self.dim):
                    emb[j] += points[nb][j % d]
            emb = [x/max(k,1) for x in emb]
            embedded.append(emb)
        return embedded

if __name__ == "__main__":
    print("=== Manifold Learning Demo ===")
    pts = [[math.sin(t), math.cos(t), t*0.1] for t in range(10)]
    ml = ManifoldLearner(dim=2)
    emb = ml.local_linear_embedding(pts, k=3)
    print(f"Embedded: {len(emb)}x{len(emb[0])}")
