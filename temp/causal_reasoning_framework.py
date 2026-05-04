#!/usr/bin/env python3
"""Causal Reasoning Framework: 因果推理框架"""
import math, random, logging
logging.basicConfig(level=logging.INFO)

class CausalReasoner:
    def __init__(self, seed=42):
        random.seed(seed)
        self.knowledge_base = {}

    def add_fact(self, name, prob=1.0):
        self.knowledge_base[name] = prob

    def deductive_inference(self, premises, conclusion):
        conf = 1.0
        for p in premises:
            conf *= self.knowledge_base.get(p, 0.0)
        self.knowledge_base[conclusion] = conf
        return conf

    def abductive_inference(self, observation, hypotheses):
        """Best explanation"""
        best = None
        best_score = -1
        for hyp, prob in hypotheses:
            if self.knowledge_base.get(hyp, 0) > best_score:
                best_score = self.knowledge_base[hyp]
                best = hyp
        return best, best_score

if __name__ == "__main__":
    print("=== Causal Reasoning Framework Demo ===")
    cr = CausalReasoner()
    cr.add_fact("Rain", 0.8)
    cr.add_fact("Cloudy", 0.6)
    conf = cr.deductive_inference(["Rain"], "WetGround")
    print(f"Confidence in WetGround: {conf:.3f}")
