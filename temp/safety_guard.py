#!/usr/bin/env python3
"""AI Safety Guardrails"""
import random, logging
logging.basicConfig(level=logging.INFO)

class SafetyGuardrail:
    def __init__(self):
        self.denylist = {"harmful", "illegal", "dangerous"}

    def check_input(self, text):
        words = set(text.lower().split())
        violations = words & self.denylist
        return list(violations)

    def check_output(self, output, threshold=0.8):
        risk = sum(random.random() for _ in output) / len(output) if output else 0
        return {"safe": risk < threshold, "risk_score": round(risk, 3)}

if __name__ == "__main__":
    sg = SafetyGuardrail()
    violations = sg.check_input("This is a test input")
    safety = sg.check_output([0.1, 0.2, 0.3])
    logging.info(f"Safety: violations={violations}, {safety}")
