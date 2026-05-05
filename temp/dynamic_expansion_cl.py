#!/usr/bin/env python3
"""Continuous Learning: 动态扩展网络"""
import math, random, logging
logging.basicConfig(level=logging.INFO)

class DynamicExpansionCL:
    def __init__(self, base_dim=4, threshold=0.7):
        self.base_dim = base_dim
        self.threshold = threshold
        self.weights = [[random.gauss(0,0.3) for _ in range(base_dim)] for _ in range(base_dim)]
        self.capacity_used = 0

    def capacity_check(self, utilization):
        if utilization > self.threshold:
            new_dim = int(self.base_dim * 1.5)
            for _ in range(new_dim - len(self.weights)):
                self.weights.append([random.gauss(0,0.1) for _ in range(new_dim)])
            for w in self.weights:
                while len(w) < new_dim:
                    w.append(random.gauss(0,0.1))
            self.base_dim = new_dim
            self.capacity_used = 0
            logging.info(f"Expanded to dim={new_dim}")
            return True
        self.capacity_used += utilization
        return False

if __name__ == "__main__":
    cl = DynamicExpansionCL()
    for i in range(5):
        cl.capacity_check(0.3)
    logging.info(f"Final dim={cl.base_dim}")
