#!/usr/bin/env python3
"""Causal Reinforcement Learning: 因果强化学习"""
import math, random, logging
from typing import Dict, List
logging.basicConfig(level=logging.INFO)

class CausalAgent:
    def __init__(self, state_dim, action_dim, seed=42):
        random.seed(seed)
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.causal_model = {}
        self.q_table = {}
        self.transition_buffer = []

    def learn_causal_model(self, transitions):
        for s, a, s_next, r in transitions:
            key = (s, a)
            if key not in self.causal_model:
                self.causal_model[key] = {"count": 0, "avg_reward": 0.0}
            m = self.causal_model[key]
            m["count"] += 1
            m["avg_reward"] += (r - m["avg_reward"]) / m["count"]

    def select_action(self, state, epsilon=0.1):
        if random.random() < epsilon:
            return random.randint(0, self.action_dim - 1)
        best_a, best_v = 0, float("-inf")
        for a in range(self.action_dim):
            v = self.causal_model.get((state, a), {}).get("avg_reward", 0)
            if v > best_v:
                best_v, best_a = v, a
        return best_a

    def intervene(self, state, action):
        return self.causal_model.get((state, action), {}).get("avg_reward", 0)

if __name__ == "__main__":
    print("=== Causal RL Demo ===")
    agent = CausalAgent(state_dim=3, action_dim=2)
    transitions = []
    for _ in range(100):
        s, a = random.randint(0, 2), random.randint(0, 1)
        r = 1.0 if a == 0 else -0.5 + random.gauss(0, 0.2)
        transitions.append((s, a, s, r))
    agent.learn_causal_model(transitions)
    print(f"Action 0 value: {agent.intervene(0, 0):.3f}")
    print(f"Best action for state 0: {agent.select_action(0)}")
