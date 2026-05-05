#!/usr/bin/env python3
"""Multimodal Fusion Architecture"""
import math, random, logging
logging.basicConfig(level=logging.INFO)

class MultimodalFusion:
    def __init__(self, dims):
        self.dims = dims

    def early_fusion(self, inputs):
        return sum(inputs, [])

    def late_fusion(self, outputs, weights=None):
        if not weights:
            weights = [1.0/len(outputs)] * len(outputs)
        n = len(outputs[0])
        return [sum(o[i]*w for o,w in zip(outputs, weights)) for i in range(n)]

    def cross_attention(self, q, k, v, dim=64):
        score = sum(a*b for a,b in zip(q, k)) / dim
        return [x * score for x in v]

if __name__ == "__main__":
    mf = MultimodalFusion([64, 64])
    early = mf.early_fusion([[1]*32, [0]*32])
    late = mf.late_fusion([[0.5]*32, [0.6]*32])
    logging.info(f"Fusion: early={len(early)}, late={len(late)}")
