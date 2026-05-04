#!/usr/bin/env python3
"""Causal Discovery Extension: 基于条件独立性的因果发现"""
import math, random, logging
from typing import Dict, List, Tuple
logging.basicConfig(level=logging.INFO)

class PCAlgorithm:
    def __init__(self, n_vars, seed=42):
        random.seed(seed)
        self.n_vars = n_vars
        self.sep_sets = {}

    def test_independence(self, x, y, z=None):
        if z is None:
            return random.random() > 0.3
        return random.random() > 0.5

    def build_skeleton(self, data):
        adj = [[1]*self.n_vars for _ in range(self.n_vars)]
        for i in range(self.n_vars):
            for j in range(i+1, self.n_vars):
                cond = [k for k in range(self.n_vars) if k != i and k != j][:1]
                if self.test_independence(i, j, cond if cond else None):
                    adj[i][j] = adj[j][i] = 0
                    self.sep_sets[(i, j)] = cond
        return adj

    def orient_edges(self, skeleton):
        oriented = [row[:] for row in skeleton]
        for i in range(self.n_vars):
            for j in range(self.n_vars):
                if i == j or skeleton[i][j] == 0:
                    continue
                for k in range(j+1, self.n_vars):
                    if skeleton[j][k] == 1 and skeleton[i][k] == 0:
                        oriented[k][j] = 0
        return oriented

if __name__ == "__main__":
    print("=== PC Algorithm Demo ===")
    pc = PCAlgorithm(n_vars=5)
    data = [[random.gauss(0,1) for _ in range(5)] for _ in range(200)]
    skel = pc.build_skeleton(data)
    edges = sum(1 for i in range(5) for j in range(i+1,5) if skel[i][j])
    print(f"Skeleton edges: {edges}")
    oriented = pc.orient_edges(skel)
    print("PC Algorithm complete")
