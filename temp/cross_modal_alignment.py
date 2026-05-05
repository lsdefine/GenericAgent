#!/usr/bin/env python3
"""Cross-Modal Alignment"""
import math, random, logging
logging.basicConfig(level=logging.INFO)

class CrossModalAlignment:
    def __init__(self, embed_dim=256):
        self.embed_dim = embed_dim

    def project(self, x, modality="text"):
        scale = 1.0 if modality == "text" else 0.9
        return [v * scale + random.gauss(0, 0.05) for v in x]

    def align_loss(self, t_emb, v_emb):
        sim = sum(a*b for a,b in zip(t_emb, v_emb)) / self.embed_dim
        return max(0, 1.0 - sim)

if __name__ == "__main__":
    cma = CrossModalAlignment()
    t = [random.gauss(0,1) for _ in range(256)]
    v = [random.gauss(0,1) for _ in range(256)]
    loss = cma.align_loss(t, v)
    logging.info(f"Cross-Modal Alignment loss: {loss:.4f}")
