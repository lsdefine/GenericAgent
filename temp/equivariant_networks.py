#!/usr/bin/env python3
"""Equivariant Networks: 等变网络"""
import math, random, logging
logging.basicConfig(level=logging.INFO)

class EquivariantLayer:
    def __init__(self, dim, groups=None):
        self.dim = dim
        self.groups = groups or [(0,1),(1,2)]

    def equivariant_forward(self, x, transform):
        out = [0.0]*self.dim
        for g in self.groups:
            i, j = g
            out[i] += transform.get('swap', False) and x[j] or x[i]
            out[j] += transform.get('swap', False) and x[i] or x[j]
        return [x/len(self.groups) for x in out]

class EquivariantNet:
    def __init__(self, dim=3):
        self.layers = [EquivariantLayer(dim) for _ in range(2)]

    def forward(self, x, transforms):
        h = x
        for i, layer in enumerate(self.layers):
            t = transforms[i] if i < len(transforms) else {}
            h = layer.equivariant_forward(h, t)
        return h

if __name__ == "__main__":
    print("=== Equivariant Net Demo ===")
    en = EquivariantNet(dim=3)
    out = en.forward([1,2,3], [{'swap': True}, {}])
    print(f"Output: {out}")
