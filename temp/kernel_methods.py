#!/usr/bin/env python3
"""Kernel Methods: 核方法"""
import math, random, logging
logging.basicConfig(level=logging.INFO)

class KernelMachine:
    def __init__(self, kernel_type='rbf', gamma=1.0):
        self.kernel_type = kernel_type
        self.gamma = gamma
        self.X_train = []
        self.alpha = []

    def kernel(self, x1, x2):
        if self.kernel_type == 'rbf':
            sq = sum((a-b)**2 for a,b in zip(x1, x2))
            return math.exp(-self.gamma * sq)
        elif self.kernel_type == 'poly':
            return (sum(a*b for a,b in zip(x1, x2)) + 1) ** 2
        return sum(a*b for a,b in zip(x1, x2))

    def fit(self, X, y):
        self.X_train = X
        n = len(X)
        K = [[self.kernel(X[i], X[j]) for j in range(n)] for i in range(n)]
        # Ridge regression solution
        lam = 0.1
        diag = [K[i][i] + lam for i in range(n)]
        self.alpha = [y[i]/diag[i] for i in range(n)]

    def predict(self, X):
        return [sum(self.alpha[i]*self.kernel(x, self.X_train[i]) for i in range(len(self.X_train))) for x in X]

if __name__ == "__main__":
    print("=== Kernel Methods Demo ===")
    km = KernelMachine('rbf', gamma=0.5)
    X = [[0],[1],[2]]
    y = [0, 1, 4]
    km.fit(X, y)
    pred = km.predict([[0.5],[1.5]])
    print(f"Predictions: {pred}")
