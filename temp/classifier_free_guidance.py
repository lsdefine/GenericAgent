#!/usr/bin/env python3
"""Classifier-Free Guidance for Diffusion"""
import math, random, logging
logging.basicConfig(level=logging.INFO)

class ClassifierFreeGuidance:
    def __init__(self, guidance_scale=7.5):
        self.guidance_scale = guidance_scale

    def predict_noise(self, xt, t, cond=True):
        scale = 1.0 if cond else 0.8
        return [v * scale + random.gauss(0, 0.1) for v in xt]

    def guidance_step(self, xt, t):
        noise_cond = self.predict_noise(xt, t, cond=True)
        noise_uncond = self.predict_noise(xt, t, cond=False)
        guided = [u + self.guidance_scale * (c - u)
                  for c, u in zip(noise_cond, noise_uncond)]
        return guided

if __name__ == "__main__":
    cfg = ClassifierFreeGuidance()
    xt = [random.gauss(0,1) for _ in range(8)]
    guided = cfg.guidance_step(xt, 10)
    logging.info(f"CFG: guided={[round(v,2) for v in guided]}")
