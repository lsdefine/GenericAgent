#!/usr/bin/env python3
"""Persistent Homology: 持续同调计算"""
import math, random, logging
logging.basicConfig(level=logging.INFO)

class PersistentHomology:
    def __init__(self, distances):
        self.distances = distances
        self.n = len(distances)

    def compute_barcodes_0d(self):
        """0维持续同调(连通分量)"""
        parent = list(range(self.n))
        def find(x):
            while parent[x] != x: x = parent[x]
            return x
        def union(a, b):
            pa, pb = find(a), find(b)
            if pa != pb: parent[pa] = pb

        edges = []
        for i in range(self.n):
            for j in range(i+1, self.n):
                edges.append((self.distances[i][j], i, j))
        edges.sort()

        barcodes = []
        born = [0]*self.n
        active = self.n
        for d, i, j in edges:
            pi, pj = find(i), find(j)
            if pi != pj:
                barcodes.append({"birth": born[pi], "death": d})
                union(pi, pj)
                active -= 1
        return barcodes

if __name__ == "__main__":
    print("=== Persistent Homology Demo ===")
    dists = [[0,1,2,3],[1,0,1.5,2.5],[2,1.5,0,1],[3,2.5,1,0]]
    ph = PersistentHomology(dists)
    bcs = ph.compute_barcodes_0d()
    print(f"Barcodes: {bcs}")
