#!/usr/bin/env python3
"""Secure Aggregation for Federated Learning"""
import math, random, logging
logging.basicConfig(level=logging.INFO)

class SecureAggregator:
    def __init__(self, n_clients=5, dim=4, noise_scale=0.1):
        self.n = n_clients
        self.dim = dim
        self.noise_scale = noise_scale

    def mask(self, values):
        noise = [random.gauss(0, self.noise_scale) for _ in values]
        return [v + n for v, n in zip(values, noise)]

    def unmask(self, masked_values, scale=None):
        if scale is None:
            scale = 1.0/self.n
        return [sum(m)/self.n for m in zip(*masked_values)]

    def aggregate_secure(self, client_updates):
        masked = [self.mask(u) for u in client_updates]
        return self.unmask(masked)

if __name__ == "__main__":
    sa = SecureAggregator()
    updates = [[random.gauss(0.5, 0.2) for _ in range(4)] for _ in range(sa.n)]
    result = sa.aggregate_secure(updates)
    logging.info(f"Secure agg: {[round(x,3) for x in result]}")
