#!/usr/bin/env python3
"""Invariant Risk Minimization for GenericAgent"""

import os, math, random, logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class InvariantClassifier:
    """学习跨环境一致的预测器"""
    def __init__(self, input_dim, seed=42):
        self.input_dim = input_dim
        self.weights = [random.gauss(0, 0.1) for _ in range(input_dim)]
        self.bias = 0.0

    def predict(self, x):
        val = self.bias + sum(x[i]*self.weights[i] for i in range(self.input_dim))
        return 1.0/(1.0+math.exp(-max(-20, min(20, val))))

    def compute_grad(self, x, y):
        p = self.predict(x)
        err = p - y
        return [err*x[i] for i in range(self.input_dim)], err


class InvariantRiskMinimization:
    """IRM训练器: 多环境训练+梯度惩罚"""
    def __init__(self, input_dim, penalty_weight=100.0):
        self.classifier = InvariantClassifier(input_dim)
        self.penalty_weight = penalty_weight
        self.history = []

    def train(self, environments, epochs=50, lr=0.01):
        for epoch in range(epochs):
            total_loss = 0.0
            env_grads = []

            for env_X, env_Y in environments:
                env_loss = 0.0
                env_w_grad = [0.0]*len(self.classifier.weights)
                env_b_grad = 0.0

                for x, y in zip(env_X, env_Y):
                    p = self.classifier.predict(x)
                    loss = -(y*math.log(p+1e-8) + (1-y)*math.log(1-p+1e-8))
                    env_loss += loss
                    wg, bg = self.classifier.compute_grad(x, y)
                    for i in range(len(env_w_grad)):
                        env_w_grad[i] += wg[i]
                    env_b_grad += bg

                n = len(env_X)
                env_loss /= n
                total_loss += env_loss
                env_grads.append(([g/n for g in env_w_grad], env_b_grad/n))

            avg_loss = total_loss / max(len(environments), 1)

            # IRM penalty: norm of average gradient across environments
            n_env = len(env_grads)
            avg_w = [sum(g[0][i] for g in env_grads)/n_env for i in range(len(env_grads[0][0]))]
            avg_b = sum(g[1] for g in env_grads)/n_env
            penalty = sum(g**2 for g in avg_w) + avg_b**2

            total = avg_loss + self.penalty_weight * penalty

            # Update from first environment
            if environments:
                X0, Y0 = environments[0]
                for x, y in zip(X0, Y0):
                    wg, bg = self.classifier.compute_grad(x, y)
                    for i in range(len(self.classifier.weights)):
                        self.classifier.weights[i] -= lr*wg[i]
                    self.classifier.bias -= lr*bg

            if epoch % 10 == 0:
                self.history.append({"epoch": epoch, "loss": avg_loss, "penalty": penalty, "total": total})

        return {"history": self.history, "final_loss": total}

    def evaluate_environments(self, environments):
        """评估各环境性能"""
        results = []
        for i, (X, Y) in enumerate(environments):
            correct = sum(1 for x, y in zip(X, Y) if (1 if self.classifier.predict(x)>=0.5 else 0)==y)
            results.append({"env": i, "acc": correct/len(X)})
        return results


if __name__ == "__main__":
    print("=== IRM Demo ===")
    random.seed(42)
    n = 100

    # 环境1: 因果关系强
    X1 = [[random.uniform(-1,1), random.gauss(0,0.5)] for _ in range(n)]
    Y1 = [1 if x[0]>0 else 0 for x in X1]

    # 环境2: 反向相关
    X2 = [[random.uniform(-1,1), random.gauss(0,0.5)] for _ in range(n)]
    Y2 = [1 if x[0]<0 else 0 for x in X2]

    irm = InvariantRiskMinimization(input_dim=2, penalty_weight=10.0)
    result = irm.train([(X1, Y1), (X2, Y2)], epochs=30, lr=0.05)
    print(f"Final loss: {result['history'][-1]['total']:.4f}")

    accs = irm.evaluate_environments([(X1, Y1), (X2, Y2)])
    for r in accs:
        print(f"Env {r['env']} accuracy: {r['acc']:.3f}")
