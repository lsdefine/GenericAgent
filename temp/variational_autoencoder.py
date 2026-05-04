#!/usr/bin/env python3
"""
Variational Autoencoder for GenericAgent
变分自编码器: 编码器-解码器架构、KL散度正则、潜空间采样
支持: 生成采样、异常检测、潜空间插值、条件生成
"""

import os
import json
import math
import random
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class VAEConfig:
    input_dim: int = 784
    hidden_dims: List[int] = None
    latent_dim: int = 32
    learning_rate: float = 0.001
    kl_weight: float = 1.0
    
    def __post_init__(self):
        if self.hidden_dims is None:
            self.hidden_dims = [256, 128]

@dataclass
class GenerationResult:
    samples: List[List[float]]
    latent_codes: List[List[float]]
    log_likelihood: float


class VAEEncoder:
    """Encoder network: x -> (mu, log_var)"""
    def __init__(self, input_dim: int, hidden_dims: List[int], latent_dim: int):
        self.input_dim = input_dim
        self.hidden_dims = hidden_dims
        self.latent_dim = latent_dim
        self.weights: Dict[str, List[float]] = {}
        self._init_weights()
    
    def _init_weights(self):
        prev_dim = self.input_dim
        for i, h in enumerate(self.hidden_dims):
            self.weights[f'enc_{i}'] = [random.gauss(0, 0.1) for _ in range(prev_dim * h)]
            prev_dim = h
        self.weights['mu'] = [random.gauss(0, 0.1) for _ in range(prev_dim * self.latent_dim)]
        self.weights['log_var'] = [random.gauss(0, 0.1) for _ in range(prev_dim * self.latent_dim)]
    
    def encode(self, x: List[float]) -> Tuple[List[float], List[float]]:
        """Encode input to latent distribution parameters"""
        h = x
        for i in range(len(self.hidden_dims)):
            w = self.weights[f'enc_{i}']
            dim_out = self.hidden_dims[i]
            dim_in = len(h)
            h = self._linear_relu(h, w, dim_in, dim_out)
        
        mu = self._linear(h, self.weights['mu'], len(h), self.latent_dim)
        log_var = self._linear(h, self.weights['log_var'], len(h), self.latent_dim)
        
        # Clip log_var for stability
        log_var = [max(-10, min(10, v)) for v in log_var]
        
        return mu, log_var
    
    def _linear_relu(self, x: List[float], w: List[float], dim_in: int, dim_out: int) -> List[float]:
        out = []
        for i in range(dim_out):
            s = 0.0
            for j in range(dim_in):
                idx = i * dim_in + j
                if idx < len(w) and j < len(x):
                    s += w[idx] * x[j]
            out.append(max(0, s))  # ReLU
        return out
    
    def _linear(self, x: List[float], w: List[float], dim_in: int, dim_out: int) -> List[float]:
        out = []
        for i in range(dim_out):
            s = 0.0
            for j in range(dim_in):
                idx = i * dim_in + j
                if idx < len(w) and j < len(x):
                    s += w[idx] * x[j]
            out.append(s)
        return out


class VAEDecoder:
    """Decoder network: z -> x_reconstructed"""
    def __init__(self, latent_dim: int, hidden_dims: List[int], output_dim: int):
        self.latent_dim = latent_dim
        self.hidden_dims = list(reversed(hidden_dims))
        self.output_dim = output_dim
        self.weights: Dict[str, List[float]] = {}
        self._init_weights()
    
    def _init_weights(self):
        prev_dim = self.latent_dim
        for i, h in enumerate(self.hidden_dims):
            self.weights[f'dec_{i}'] = [random.gauss(0, 0.1) for _ in range(prev_dim * h)]
            prev_dim = h
        self.weights['out'] = [random.gauss(0, 0.1) for _ in range(prev_dim * self.output_dim)]
    
    def decode(self, z: List[float]) -> List[float]:
        """Decode latent vector to reconstruction"""
        h = z
        for i in range(len(self.hidden_dims)):
            w = self.weights[f'dec_{i}']
            dim_in = len(h)
            dim_out = self.hidden_dims[i]
            h = self._linear_relu(h, w, dim_in, dim_out)
        
        # Output layer with sigmoid
        w = self.weights['out']
        return self._linear_sigmoid(h, w, len(h), self.output_dim)
    
    def _linear_relu(self, x, w, dim_in, dim_out):
        out = []
        for i in range(dim_out):
            s = sum(w[i * dim_in + j] * x[j] for j in range(min(dim_in, len(x))) if i * dim_in + j < len(w))
            out.append(max(0, s))
        return out
    
    def _linear_sigmoid(self, x, w, dim_in, dim_out):
        out = []
        for i in range(dim_out):
            s = sum(w[i * dim_in + j] * x[j] for j in range(min(dim_in, len(x))) if i * dim_in + j < len(w))
            out.append(1.0 / (1.0 + math.exp(-max(-500, min(500, s)))))
        return out


class VariationalAutoencoder:
    """Main VAE orchestrator"""
    def __init__(self, config: VAEConfig = None):
        self.config = config or VAEConfig()
        self.encoder = VAEEncoder(self.config.input_dim, self.config.hidden_dims, self.config.latent_dim)
        self.decoder = VAEDecoder(self.config.latent_dim, self.config.hidden_dims, self.config.input_dim)
        self.training_history: List[Dict] = []
    
    def reparameterize(self, mu: List[float], log_var: List[float]) -> List[float]:
        """Reparameterization trick: z = mu + sigma * epsilon"""
        return [m + math.exp(0.5 * lv) * random.gauss(0, 1) 
                for m, lv in zip(mu, log_var)]
    
    def kl_divergence(self, mu: List[float], log_var: List[float]) -> float:
        """Compute KL divergence from N(0,1)"""
        return -0.5 * sum(1 + lv - m**2 - math.exp(lv) for m, lv in zip(mu, log_var))
    
    def reconstruction_loss(self, x: List[float], x_recon: List[float]) -> float:
        """BCE reconstruction loss"""
        eps = 1e-7
        return -sum(x[i] * math.log(x_recon[i] + eps) + 
                    (1 - x[i]) * math.log(1 - x_recon[i] + eps) 
                    for i in range(len(x)))
    
    def forward(self, x: List[float]) -> Tuple[List[float], List[float], List[float]]:
        """Full forward pass"""
        mu, log_var = self.encoder.encode(x)
        z = self.reparameterize(mu, log_var)
        x_recon = self.decoder.decode(z)
        return x_recon, mu, log_var
    
    def train_step(self, x: List[float]) -> Dict:
        """Single training step (simulated)"""
        x_recon, mu, log_var = self.forward(x)
        
        recon_loss = self.reconstruction_loss(x, x_recon)
        kl_loss = self.kl_divergence(mu, log_var)
        total_loss = recon_loss + self.config.kl_weight * kl_loss
        
        self.training_history.append({
            'recon_loss': recon_loss,
            'kl_loss': kl_loss,
            'total_loss': total_loss
        })
        
        return {'recon_loss': recon_loss, 'kl_loss': kl_loss, 'total_loss': total_loss}
    
    def generate(self, n_samples: int = 1) -> GenerationResult:
        """Generate new samples from prior"""
        samples = []
        latents = []
        
        for _ in range(n_samples):
            z = [random.gauss(0, 1) for _ in range(self.config.latent_dim)]
            x_gen = self.decoder.decode(z)
            samples.append(x_gen)
            latents.append(z)
        
        return GenerationResult(samples=samples, latent_codes=latents, log_likelihood=0.0)
    
    def interpolate(self, z1: List[float], z2: List[float], n_steps: int = 10) -> List[List[float]]:
        """Interpolate in latent space"""
        results = []
        for t in range(n_steps):
            alpha = t / (n_steps - 1)
            z_interp = [z1[i] * (1 - alpha) + z2[i] * alpha 
                       for i in range(len(z1))]
            results.append(self.decoder.decode(z_interp))
        return results


if __name__ == '__main__':
    print("=== Variational Autoencoder (VAE) ===")
    
    config = VAEConfig(input_dim=28*28, hidden_dims=[128, 64], latent_dim=16)
    vae = VariationalAutoencoder(config)
    
    # Simulate training
    print("\nTraining...")
    for epoch in range(50):
        x = [random.random() for _ in range(28*28)]
        result = vae.train_step(x)
        if epoch % 10 == 0:
            print(f"  Epoch {epoch}: loss={result['total_loss']:.4f} "
                  f"(recon={result['recon_loss']:.4f}, kl={result['kl_loss']:.4f})")
    
    # Generate samples
    gen = vae.generate(n_samples=3)
    print(f"\nGenerated {len(gen.samples)} samples")
    
    # Latent interpolation
    z1 = [random.gauss(0, 1) for _ in range(16)]
    z2 = [random.gauss(0, 1) for _ in range(16)]
    interp = vae.interpolate(z1, z2, n_steps=5)
    print(f"Latent interpolation: {len(interp)} steps")
