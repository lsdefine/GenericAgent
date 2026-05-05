#!/usr/bin/env python3
"""Task-Free Continual Learning"""
import math, random, logging
logging.basicConfig(level=logging.INFO)

class TaskFreeCL:
    def __init__(self, dim=4, memory_size=10):
        self.dim = dim
        self.memory = []
        self.model = [0.0]*dim

    def observe(self, data_point):
        self.memory.append(data_point)
        if len(self.memory) > self.memory_size:
            self.memory.pop(0)

    def replay_train(self, lr=0.01):
        for sample in self.memory:
            for i in range(self.dim):
                self.model[i] += lr * (sample[i] - self.model[i]) * 0.1

    def get_representation(self, x):
        return [sum(x[i]*m[i] for i in range(self.dim))/self.dim for m in [self.model]]

if __name__ == "__main__":
    tfcl = TaskFreeCL()
    for _ in range(20):
        tfcl.observe([random.gauss(0,1) for _ in range(4)])
        tfcl.replay_train()
    logging.info(f"Model: {[round(x,3) for x in tfcl.model]}")
