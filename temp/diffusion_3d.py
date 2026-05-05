#!/usr/bin/env python3
"""3D Diffusion Generation"""
import math, random, logging
logging.basicConfig(level=logging.INFO)

class Diffusion3D:
    def __init__(self, res=32):
        self.res = res
        self.volume = [0.0] * (res**3)

    def initialize_noise(self):
        self.volume = [random.gauss(0,1) for _ in range(self.res**3)]

    def denoise_step(self):
        for i in range(len(self.volume)):
            self.volume[i] *= 0.95

if __name__ == "__main__":
    d3 = Diffusion3D(res=8)
    d3.initialize_noise()
    for _ in range(20):
        d3.denoise_step()
    logging.info(f"3D Diffusion: {d3.res}^3 volume, mean={sum(d3.volume)/len(d3.volume):.3f}")
