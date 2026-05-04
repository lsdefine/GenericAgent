#!/usr/bin/env python3
"""Dynamic Graph Learning for GenericAgent"""
import math, random, logging
logging.basicConfig(level=logging.INFO)

class TemporalGraph:
    def __init__(self, n_nodes):
        self.n_nodes = n_nodes
        self.snapshots = []

    def add_snapshot(self, adj, t):
        self.snapshots.append({"adj": adj, "t": t})

    def evolve(self):
        """Simple Markov evolution"""
        if not self.snapshots:
            return
        last = self.snapshots[-1]["adj"]
        new_adj = [[0]*self.n_nodes for _ in range(self.n_nodes)]
        for i in range(self.n_nodes):
            for j in range(self.n_nodes):
                p_keep = last[i][j] * 0.8
                p_new = 0.1 if last[i][j] == 0 else 0.2
                new_adj[i][j] = 1 if random.random() < p_keep or (last[i][j]==0 and random.random()<p_new) else 0
        self.add_snapshot(new_adj, self.snapshots[-1]["t"] + 1)
        return new_adj

class DynamicGraphLearner:
    def __init__(self, n_nodes):
        self.tg = TemporalGraph(n_nodes)

    def train(self, n_steps):
        init = [[1 if i!=j and random.random()<0.3 else 0 for j in range(self.tg.n_nodes)] for i in range(self.tg.n_nodes)]
        self.tg.add_snapshot(init, 0)
        for _ in range(n_steps):
            self.tg.evolve()

    def get_edge_prob(self, i, j):
        count = sum(1 for s in self.tg.snapshots if s["adj"][i][j] > 0)
        return count / max(len(self.tg.snapshots), 1)

if __name__ == "__main__":
    print("=== Dynamic Graph Learning Demo ===")
    learner = DynamicGraphLearner(n_nodes=5)
    learner.train(n_steps=10)
    for i in range(5):
        for j in range(i+1, 5):
            print(f"P({i},{j}): {learner.get_edge_prob(i, j):.2f}")
