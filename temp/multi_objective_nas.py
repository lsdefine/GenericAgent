#!/usr/bin/env python3
"""Multi-Objective NAS"""
import math, random, logging
logging.basicConfig(level=logging.INFO)

class MultiObjectiveNAS:
    def __init__(self, n_obj=3):
        self.n_obj = n_obj
        self.pareto_front = []

    def dominates(self, a, b):
        return all(a[i] >= b[i] for i in range(self.n_obj)) and any(a[i] > b[i] for i in range(self.n_obj))

    def add_solution(self, obj_values, config):
        self.pareto_front = [x for x in self.pareto_front
                             if not self.dominates(obj_values, x[0])]
        if not any(self.dominates(x[0], obj_values) for x in self.pareto_front):
            self.pareto_front.append((obj_values, config))

    def get_pareto_front(self):
        return self.pareto_front

if __name__ == "__main__":
    nas = MultiObjectiveNAS()
    for _ in range(10):
        acc = random.uniform(0.7, 0.95)
        lat = random.uniform(5, 20)
        sz = random.uniform(1, 10)
        nas.add_solution([acc, -lat, -sz], {"acc": acc, "lat": lat, "size": sz})
    logging.info(f"Pareto front size: {len(nas.get_pareto_front())}")
    for v, c in nas.get_pareto_front():
        logging.info(f"  acc={v[0]:.3f} lat={-v[1]:.1f} size={-v[2]:.1f} config={c}")
