#!/usr/bin/env python3
"""Topological Data Analysis: 拓扑数据分析"""
import math, random, logging
logging.basicConfig(level=logging.INFO)

class TDA:
    def __init__(self, points):
        self.points = points
        self.n = len(points)

    def pairwise_dist(self, i, j):
        return math.sqrt(sum((self.points[i][d]-self.points[j][d])**2 for d in range(len(self.points[0]))))

    def build_vr_complex(self, eps):
        """Vietoris-Rips复形"""
        edges = []
        for i in range(self.n):
            for j in range(i+1, self.n):
                if self.pairwise_dist(i, j) < eps:
                    edges.append((i, j))
        triangles = []
        for i in range(self.n):
            for j in range(i+1, self.n):
                for k in range(j+1, self.n):
                    if (i,j) in edges or (j,i) in edges:
                        if (i,k) in edges or (k,i) in edges:
                            if (j,k) in edges or (k,j) in edges:
                                triangles.append((i,j,k))
        return {"vertices": self.n, "edges": len(edges), "triangles": len(triangles)}

if __name__ == "__main__":
    print("=== TDA Demo ===")
    pts = [[0,0],[1,0],[0,1],[1,1],[0.5,0.5]]
    tda = TDA(pts)
    for eps in [0.8, 1.2]:
        cx = tda.build_vr_complex(eps)
        print(f"eps={eps}: {cx}")
