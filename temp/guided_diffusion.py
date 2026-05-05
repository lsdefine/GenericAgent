#!/usr/bin/env python3
"""Guided Diffusion Model"""
import math, random, logging
logging.basicConfig(level=logging.INFO)

class GuidedDiffusion:
    def __init__(self, steps=50):
        self.steps = steps

    def add_noise(self, x0, t):
        alpha = t / self.steps
        return [v * (1-alpha) + random.gauss(0, alpha) for v in x0]

    def sample_step(self, xt, t, gradient=None):
        noise_scale = math.sqrt(t / self.steps)
        denoised = [v * 0.9 for v in xt]
        if gradient:
            denoised = [d + 0.1*g for d, g in zip(denoised, gradient)]
        return [d + random.gauss(0, noise_scale*0.1) for d in denoised]

if __name__ == "__main__":
    gd = GuidedDiffusion()
    x0 = [random.gauss(0,1) for _ in range(8)]
    xt = gd.add_noise(x0, 25)
    for t in range(25, 0, -1):
        xt = gd.sample_step(xt, t)
    logging.info(f"Guided diffusion: sample done, final={[round(v,2) for v in xt]}")
