#!/usr/bin/env python3
"""Meta-Graph Learning: 元图学习/跨图迁移"""
import math, random, logging
logging.basicConfig(level=logging.INFO)

class MetaGraphLearner:
    def __init__(self, dim=4, seed=42):
        random.seed(seed)
        self.dim = dim
        self.meta_params = [[random.gauss(0,0.3) for _ in range(dim)] for _ in range(dim)]

    def adapt(self, graph_data, lr=0.05):
        """适应新图结构"""
        adapted = [[p for p in row] for row in self.meta_params]
        if len(graph_data) < 2: return adapted
        for i in range(min(len(graph_data), self.dim)):
            for j in range(self.dim):
                delta = random.gauss(0, lr * 0.5)
                adapted[i][j] += delta
        return adapted

    def get_embedding(self, node_id, params):
        return params[node_id % len(params)] if params else [0]*self.dim

if __name__ == "__main__":
    print("=== Meta-Graph Learning Demo ===")
    mgl = MetaGraphLearner(dim=4)
    new_params = mgl.adapt([[1,0],[0,1],[1,1]])
    print(f"Meta params shape: {len(new_params)}x{len(new_params[0])}")
