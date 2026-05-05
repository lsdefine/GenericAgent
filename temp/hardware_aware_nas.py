#!/usr/bin/env python3
"""Hardware-Aware NAS"""
import math, random, logging
logging.basicConfig(level=logging.INFO)

HARDWARE_PROFILES = {
    "edge": {"latency_budget": 10, "mem_budget": 512, "penalty": 1.5},
    "server": {"latency_budget": 50, "mem_budget": 8192, "penalty": 1.0},
}

class HardwareAwareNAS:
    def __init__(self, profile="edge"):
        self.hw = HARDWARE_PROFILES.get(profile, HARDWARE_PROFILES["edge"])
        self.candidates = []

    def add_candidate(self, name, params_m, latency_ms, accuracy):
        self.candidates.append({"name": name, "params": params_m,
                                "latency": latency_ms, "accuracy": accuracy})

    def score(self, cand):
        lat_pen = min(1.0, cand["latency"] / self.hw["latency_budget"]) * self.hw["penalty"]
        mem_pen = min(1.0, cand["params"] * 10 / self.hw["mem_budget"]) * self.hw["penalty"]
        return cand["accuracy"] - lat_pen * 0.3 - mem_pen * 0.2

    def select(self):
        if not self.candidates:
            return None
        return max(self.candidates, key=self.score)

if __name__ == "__main__":
    nas = HardwareAwareNAS("edge")
    nas.add_candidate("mobilenet", 3.5, 8.2, 0.82)
    nas.add_candidate("efficientnet", 5.0, 12.0, 0.85)
    best = nas.select()
    logging.info(f"Best: {best["name"]} score={nas.score(best):.3f}")
