#!/usr/bin/env python3
"""Federated Learning Extension"""
import math, random, logging
logging.basicConfig(level=logging.INFO)

class FederatedAveraging:
    def __init__(self, n_clients=5, dim=4):
        self.n = n_clients
        self.dim = dim
        self.global_model = [0.0]*dim

    def local_train(self, client_id):
        return [random.gauss(0, 0.5) + self.global_model[i] for i in range(self.dim)]

    def aggregate(self, local_models, weights=None):
        if weights is None:
            weights = [1.0/self.n]*self.n
        for i in range(self.dim):
            self.global_model[i] = sum(w*m[i] for w, m in zip(weights, local_models))
        return self.global_model

if __name__ == "__main__":
    fl = FederatedAveraging()
    models = [fl.local_train(i) for i in range(fl.n)]
    g = fl.aggregate(models)
    logging.info(f"FL avg: {[round(x,3) for x in g]}")
