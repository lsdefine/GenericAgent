#!/usr/bin/env python3
"""Geometric Deep Learning: 几何深度学习"""
import math, random, logging
logging.basicConfig(level=logging.INFO)

class GeometricNet:
    def __init__(self, dim=3, hidden=8):
        self.dim = dim
        self.W = [[random.gauss(0,0.3) for _ in range(dim)] for _ in range(hidden)]

    def forward(self, coords):
        n = len(coords)
        out = []
        for i in range(n):
            feat = []
            for h in range(self.hidden):
                v = sum(self.W[h][d]*coords[i][d] for d in range(self.dim))
                feat.append(max(0, v))
            out.append(feat)
        return out

if __name__ == "__main__":
    print("=== Geometric DL Demo ===")
    gn = GeometricNet(dim=3, hidden=4)
    out = gn.forward([[1,0,0],[0,1,0],[0,0,1]])
    print(f"Output shape: {len(out)}x{len(out[0])}")
