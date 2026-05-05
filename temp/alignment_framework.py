#!/usr/bin/env python3
"""Alignment Framework: RLHF & Constitution"""
import math, random, logging
logging.basicConfig(level=logging.INFO)

class AlignmentFramework:
    def __init__(self):
        self.principles = ["helpful", "honest", "harmless"]

    def score_response(self, response, principle):
        base = 0.5 + random.gauss(0, 0.1)
        return max(0, min(1, base))

    def reward_model(self, responses, preference):
        scores = []
        for r in responses:
            s = sum(self.score_response(r, p) for p in self.principles) / len(self.principles)
            if r == preference:
                s += 0.3
            scores.append(round(s, 3))
        return scores

    def constitutional_check(self, text):
        checks = {p: random.random() > 0.2 for p in self.principles}
        return checks

if __name__ == "__main__":
    af = AlignmentFramework()
    responses = ["R1", "R2", "R3"]
    rewards = af.reward_model(responses, "R2")
    checks = af.constitutional_check("Hello world")
    logging.info(f"Alignment: rewards={rewards}, checks={checks}")
