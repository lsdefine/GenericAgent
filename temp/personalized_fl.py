#!/usr/bin/env python3
"""Personalized Federated Learning"""
import math, random, logging
logging.basicConfig(level=logging.INFO)

class PersonalizedFL:
    def __init__(self, n_clients=5, dim=4, alpha=0.5):
        self.alpha = alpha
        self.global_model = [0.0]*dim
        self.personal_models = [[random.gauss(0,0.3) for _ in range(dim)] for _ in range(n_clients)]

    def personal_step(self, client_id, lr=0.01):
        for i in range(len(self.personal_models[client_id])):
            grad = random.gauss(0, 0.1)
            self.personal_models[client_id][i] -= lr * grad
            self.personal_models[client_id][i] = (
                (1-self.alpha)*self.personal_models[client_id][i] +
                self.alpha*self.global_model[i]
            )

    def update_global(self):
        for i in range(len(self.global_model)):
            self.global_model[i] = sum(p[i] for p in self.personal_models)/len(self.personal_models)

if __name__ == "__main__":
    pfl = PersonalizedFL()
    for _ in range(5):
        for c in range(pfl.n_clients):
            pfl.personal_step(c)
        pfl.update_global()
    logging.info(f"Personalized FL done, global={[round(x,3) for x in pfl.global_model]}")
