#!/usr/bin/env python3
"""Counterfactual Data Augmentation: 反事实数据增强"""
import os, math, random, logging
from typing import Dict, List, Tuple

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class CounterfactualAugmentor:
    def __init__(self, causal_graph=None):
        self.causal_graph = causal_graph or {}

    def generate(self, sample: Dict, target_var: str, target_value, n_aug=3):
        augmented = []
        for _ in range(n_aug):
            cf = dict(sample)
            cf[target_var] = target_value
            cf = self._propagate(cf, target_var)
            augmented.append(cf)
        return augmented

    def _propagate(self, sample, changed_var):
        for parent, children in self.causal_graph.items():
            if changed_var in children:
                if parent in sample:
                    sample[parent] = sample[parent] + random.gauss(0, 0.1)
        return sample

    def augment_dataset(self, dataset, target_var, flip_label=True):
        new_data = []
        for s in dataset:
            new_val = 1 - s.get(target_var, 0)
            cfs = self.generate(s, target_var, new_val)
            for cf in cfs:
                if flip_label:
                    cf["label"] = 1 - s.get("label", 0)
                cf["_counterfactual"] = True
                new_data.append(cf)
        return new_data

if __name__ == "__main__":
    print("=== Counterfactual Augmentation Demo ===")
    aug = CounterfactualAugmentor({"education": ["income"], "income": ["health"]})
    sample = {"education": 1, "income": 50000, "health": 7}
    cfs = aug.generate(sample, "education", 2, n_aug=3)
    for i, cf in enumerate(cfs):
        print(f"CF {i}: {cf}")
    data = [{"x": random.random(), "label": random.randint(0,1)} for _ in range(5)]
    aug_data = aug.augment_dataset(data, "x")
    print(f"Augmented {len(data)} -> {len(data)+len(aug_data)} samples")
