#!/usr/bin/env python3
"""Interpretability Tools"""
import math, random, logging
logging.basicConfig(level=logging.INFO)

class InterpretabilityTool:
    def __init__(self, n_features=10):
        self.n_features = n_features

    def saliency_map(self, inputs, grads):
        return [abs(x*g) for x,g in zip(inputs, grads)]

    def feature_importance(self, weights):
        total = sum(abs(w) for w in weights)
        if total == 0:
            return [0] * len(weights)
        return [abs(w)/total for w in weights]

    def attention_heatmap(self, attn_matrix):
        n = len(attn_matrix)
        max_val = max(max(row) for row in attn_matrix) if attn_matrix else 1
        return [[v/max_val for v in row] for row in attn_matrix]

if __name__ == "__main__":
    it = InterpretabilityTool()
    inp = [random.random() for _ in range(10)]
    grads = [random.gauss(0,1) for _ in range(10)]
    saliency = it.saliency_map(inp, grads)
    importance = it.feature_importance(grads)
    logging.info(f"Interpretability: saliency_top={max(saliency):.3f}, importance_sum={sum(importance):.3f}")
