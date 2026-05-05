#!/usr/bin/env python3
"""Masked Autoencoder (MAE) for SSL"""
import math, random, logging
logging.basicConfig(level=logging.INFO)

class MaskedAutoencoder:
    def __init__(self, patch_size=16, mask_ratio=0.75):
        self.patch_size = patch_size
        self.mask_ratio = mask_ratio

    def generate_mask(self, seq_len):
        n_mask = int(seq_len * self.mask_ratio)
        indices = random.sample(range(seq_len), n_mask)
        mask = [0]*seq_len
        for i in indices:
            mask[i] = 1
        return mask

    def reconstruct(self, input_seq, mask):
        output = list(input_seq)
        for i, m in enumerate(mask):
            if m:
                output[i] = random.gauss(0, 0.5)
        return output

if __name__ == "__main__":
    mae = MaskedAutoencoder()
    seq = [random.gauss(0,1) for _ in range(16)]
    mask = mae.generate_mask(16)
    recon = mae.reconstruct(seq, mask)
    mse = sum((s-r)**2 for s,r in zip(seq, recon))/16
    logging.info(f"MAE: mask={sum(mask)}/16, mse={mse:.3f}")
