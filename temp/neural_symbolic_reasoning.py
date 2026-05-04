#!/usr/bin/env python3
"""Neural Symbolic Reasoning: 结合神经网络与符号推理"""
import math, random, logging
logging.basicConfig(level=logging.INFO)

class NeuralSymbolicEngine:
    def __init__(self, n_symbols=10, seed=42):
        random.seed(seed)
        self.n_symbols = n_symbols
        self.fact_embeddings = {i: [random.gauss(0,1) for _ in range(4)] for i in range(n_symbols)}
        self.rules = []

    def add_rule(self, premise, conclusion, weight=1.0):
        self.rules.append({"premise": premise, "conclusion": conclusion, "weight": weight})

    def neural_match(self, a, b):
        sim = sum(x*y for x,y in zip(a,b)) / (max(math.sqrt(sum(x*x for x in a)+1e-8)*math.sqrt(sum(y*y for y in b)+1e-8), 1e-8))
        return max(0, min(1, (sim+1)/2))

    def reason(self, query_symbol):
        results = []
        for rule in self.rules:
            premise_sim = self.neural_match(self.fact_embeddings.get(rule["premise"], [0]*4),
                                            self.fact_embeddings.get(query_symbol, [0]*4))
            if premise_sim > 0.5:
                results.append({"conclusion": rule["conclusion"], "confidence": premise_sim * rule["weight"]})
        return sorted(results, key=lambda x: -x["confidence"])

if __name__ == "__main__":
    print("=== Neural Symbolic Reasoning Demo ===")
    engine = NeuralSymbolicEngine(n_symbols=5)
    engine.add_rule(0, 1, 0.9)
    engine.add_rule(1, 2, 0.7)
    results = engine.reason(0)
    print(f"Reasoning results: {results}")
