#!/usr/bin/env python3
"""Logical Neural Network: 将逻辑运算嵌入神经网络"""
import math, random, logging
logging.basicConfig(level=logging.INFO)

class LogicalNeuron:
    def __init__(self, op="AND", n_inputs=2):
        self.op = op
        self.n_inputs = n_inputs
        self.weights = [1.0/n_inputs]*n_inputs
        self.threshold = 0.5 if op == "AND" else 0.5/n_inputs if op == "OR" else 0.5

    def forward(self, inputs):
        val = sum(w*x for w,x in zip(self.weights, inputs))
        if self.op == "AND":
            return max(0, min(1, val * self.n_inputs))
        elif self.op == "OR":
            return max(0, min(1, 1 - math.prod(1-x for x in inputs)))
        elif self.op == "NOT":
            return 1 - inputs[0]
        return val

class LogicalNeuralNetwork:
    def __init__(self):
        self.layers = []

    def add_layer(self, neurons):
        self.layers.append(neurons)

    def forward(self, inputs):
        x = inputs
        for layer in self.layers:
            x = [n.forward(x) for n in layer]
        return x

if __name__ == "__main__":
    print("=== Logical Neural Network Demo ===")
    lnn = LogicalNeuralNetwork()
    lnn.add_layer([LogicalNeuron("AND", 2), LogicalNeuron("OR", 2)])
    out = lnn.forward([0.8, 0.3])
    print(f"Output: {out}")
