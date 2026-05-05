#!/usr/bin/env python3
"""Masked Image Modeling"""
import math, random, logging
logging.basicConfig(level=logging.INFO)

class MaskedImageModeling:
    def __init__(self, img_size=224, patch_size=16):
        self.img_size = img_size
        self.patch_size = patch_size
        self.n_patches = (img_size // patch_size) ** 2

    def patchify(self, img):
        return [random.gauss(0.5, 0.2) for _ in range(self.n_patches)]

    def mask_patches(self, patches, ratio=0.75):
        n_mask = int(self.n_patches * ratio)
        masked = list(patches)
        indices = random.sample(range(len(patches)), n_mask)
        for i in indices:
            masked[i] = 0.5
        return masked

if __name__ == "__main__":
    mim = MaskedImageModeling()
    patches = mim.patchify(None)
    masked = mim.mask_patches(patches)
    n_masked = sum(1 for p in masked if p == 0.5)
    logging.info(f"MIM: {n_masked}/{mim.n_patches} masked")
