#!/usr/bin/env python3
"""Graph Convolutional Network for GenericAgent"""
import math, random, logging
logging.basicConfig(level=logging.INFO)

class GCNLayer:
    def __init__(self, in_dim, out_dim):
        self.in_dim = in_dim
        self.out_dim = out_dim
        self.W = [[random.gauss(0, 0.5) for _ in range(in_dim)] for _ in range(out_dim)]

    def forward(self, adj, H):
        """H: nodes x in_dim, adj: nodes x nodes"""
        n = len(H)
        # Normalize adj
        D = [sum(row) for row in adj]
        D_inv = [1/max(d, 1) for d in D]
        new_H = []
        for i in range(n):
            h_new = [0.0]*self.out_dim
            for j in range(n):
                if adj[j][i] > 0:
                    norm = D_inv[j]
                    for k in range(self.out_dim):
                        for d in range(self.in_dim):
                            h_new[k] += norm * H[j][d] * self.W[k][d]
            new_H.append([max(0, x) for x in h_new])
        return new_H

class GraphConvNet:
    def __init__(self, n_features, n_layers=2, hidden=8):
        self.layers = []
        dims = [n_features] + [hidden]*(n_layers-1) + [n_features]
        for i in range(len(dims)-1):
            self.layers.append(GCNLayer(dims[i], dims[i+1]))

    def forward(self, adj, features):
        h = features
        for layer in self.layers:
            h = layer.forward(adj, h)
        return h

if __name__ == "__main__":
    print("=== GCN Demo ===")
    adj = [[0,1,1,0],[1,0,1,1],[1,1,0,0],[0,1,0,0]]
    feats = [[1,0,1],[0,1,0],[1,1,0],[0,0,1]]
    gcn = GraphConvNet(n_features=3, n_layers=2, hidden=4)
    out = gcn.forward(adj, feats)
    print(f"Output shape: {len(out)}x{len(out[0])}")
