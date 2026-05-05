#!/usr/bin/env python3
"""Rehearsal-Based Continual Learning"""
import math, random, logging
logging.basicConfig(level=logging.INFO)

class RehearsalCL:
    def __init__(self, dim=4, buffer_size=20):
        self.dim = dim
        self.buffer = []
        self.model = [0.0]*dim

    def add_to_buffer(self, sample):
        if len(self.buffer) < self.buffer_size:
            self.buffer.append(sample)
        else:
            idx = random.randint(0, len(self.buffer)-1)
            self.buffer[idx] = sample

    def train(self, new_data, lr=0.01):
        for d in new_data:
            for i in range(self.dim):
                self.model[i] += lr * d[i]
        for r in random.sample(self.buffer, min(5, len(self.buffer))):
            for i in range(self.dim):
                self.model[i] -= lr * r[i] * 0.5

if __name__ == "__main__":
    rcl = RehearsalCL()
    for _ in range(10):
        rcl.add_to_buffer([random.gauss(0.5,0.2) for _ in range(4)])
    new = [[random.gauss(0,0.1) for _ in range(4)] for _ in range(3)]
    rcl.train(new)
    logging.info(f"Rehearsal CL: {[round(x,3) for x in rcl.model]}")
