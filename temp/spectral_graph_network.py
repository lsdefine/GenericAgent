#!/usr/bin/env python3
"""Spectral Graph Network: 谱图网络/图拉普拉斯"""
import math, random, logging
logging.basicConfig(level=logging.INFO)

class SpectralGraphNet:
    def __init__(self, n_nodes, k=3):
        self.n = n_nodes
        self.k = k

    def laplacian(self, adj):
        D = [sum(row) for row in adj]
        L = [[0]*self.n for _ in range(self.n)]
        for i in range(self.n):
            for j in range(self.n):
                L[i][j] = -adj[i][j]
            L[i][i] += D[i]
        return L

    def spectral_embedding(self, adj):
        L = self.laplacian(adj)
        # Power iteration for k smallest eigenvectors
        n = self.n
        V = [[random.gauss(0,1) for _ in range(self.k)] for _ in range(n)]
        for _ in range(10):
            for i in range(n):
                for p in range(self.k):
                    v_new = sum(L[i][j]*V[j][p] for j in range(n))
                    V[i][p] = v_new
            # Normalize
            for p in range(self.k):
                norm = math.sqrt(sum(V[i][p]**2 for i in range(n)) + 1e-8)
                for i in range(n): V[i][p] /= norm
        return V

if __name__ == "__main__":
    print("=== Spectral Graph Demo ===")
    adj = [[0,1,1],[1,0,1],[1,1,0]]
    sgn = SpectralGraphNet(3, k=2)
    emb = sgn.spectral_embedding(adj)
    print(f"Spectral embedding: {len(emb)}x{len(emb[0])}")
