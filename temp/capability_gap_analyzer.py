#!/usr/bin/env python3
"""Capability Gap Analyzer"""
import json, logging
logging.basicConfig(level=logging.INFO)

class GapAnalyzer:
    def __init__(self, scanned_caps):
        self.scanned = scanned_caps
        self.gaps = []
        self.required = {
            "hardware": ["memory_gb", "cpu_count"],
            "automation": ["applescript", "shortcuts"],
            "security": ["keychain_available"]
        }

    def analyze(self):
        for category, fields in self.required.items():
            if category not in self.scanned:
                self.gaps.append(f"Missing category: {category}")
                continue
            for field in fields:
                if field not in self.scanned.get(category, {}):
                    self.gaps.append(f"Missing field: {category}.{field}")
        return self.gaps

if __name__ == "__main__":
    caps = {"hardware": {"memory_gb": 16.0}, "automation": {"applescript": True}}
    ga = GapAnalyzer(caps)
    gaps = ga.analyze()
    logging.info(f"Gaps found: {gaps}")
