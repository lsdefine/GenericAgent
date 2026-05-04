#!/usr/bin/env python3
"""Heterogeneous GNN: 异构图神经网络"""
import math, random, logging
logging.basicConfig(level=logging.INFO)

class HetGNN:
    def __init__(self, node_types, edge_types):
        self.node_types = node_types
        self.edge_types = edge_types
        self.transforms = {}
        for et in edge_types:
            dim_in = node_types.get(et.split('-')[0], 4)
            dim_out = node_types.get(et.split('-')[1], 4)
            self.transforms[et] = [[random.gauss(0,0.3) for _ in range(dim_in)] for _ in range(dim_out)]

    def aggregate(self, node, neighbors, adj_type):
        """异构邻居聚合"""
        if adj_type not in self.transforms:
            return node
        W = self.transforms[adj_type]
        new_node = [0.0]*len(W)
        for nb in neighbors:
            for i in range(len(W)):
                for j in range(len(nb)):
                    new_node[i] += W[i][j] * nb[j]
        return [x/max(len(neighbors),1) for x in new_node]

if __name__ == "__main__":
    print("=== Heterogeneous GNN Demo ===")
    nt = {'user': 3, 'item': 2, 'tag': 2}
    et = ['user-item', 'item-tag']
    hg = HetGNN(nt, et)
    nb = [[1,0],[0,1]]
    agg = hg.aggregate([0.5,0.3], nb, 'user-item')
    print(f"HetGNN agg: {len(agg)} dims")
