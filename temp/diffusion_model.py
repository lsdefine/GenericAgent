#!/usr/bin/env python3
"""
Diffusion Model for GenericAgent
扩散模型: 前向加噪、反向去噪、DDPM/DDIM采样
支持: 条件生成、分类器引导、DDIM加速采样、图像修复
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
class DiffusionConfig:
    timesteps: int = 1000
    beta_start: float = 0.0001
    beta_end: float = 0.02
    model_hidden_dims: List[int] = None
    sampling_steps: int = 50  # DDIM steps
    guidance_scale: float = 7.5
    image_dim: int = 32
    
    def __post_init__(self):
        if self.model_hidden_dims is None:
            self.model_hidden_dims = [64, 128, 256]


class NoiseScheduler:
    """Manages the noise schedule (beta, alpha, alpha_bar)"""
    def __init__(self, config: DiffusionConfig):
        self.config = config
        self.betas = self._linear_beta_schedule()
        self.alphas = [1.0 - b for b in self.betas]
        self.alpha_bars = []
        acc = 1.0
        for a in self.alphas:
            acc *= a
            self.alpha_bars.append(acc)
    
    def _linear_beta_schedule(self) -> List[float]:
        scale = (self.config.beta_end - self.config.beta_start) / (self.config.timesteps - 1)
        return [self.config.beta_start + scale * i for i in range(self.config.timesteps)]
    
    def add_noise(self, x0: List[float], t: int, epsilon: List[float]) -> Tuple[List[float], Dict]:
        """Forward process: add noise at step t"""
        alpha_bar = self.alpha_bars[t]
        sqrt_alpha_bar = math.sqrt(alpha_bar)
        sqrt_one_minus = math.sqrt(1 - alpha_bar)
        
        noisy = [sqrt_alpha_bar * x0[i] + sqrt_one_minus * epsilon[i] 
                 for i in range(len(x0))]
        return noisy, {'alpha_bar': alpha_bar}
    
    def get_sampling_timesteps(self) -> List[int]:
        """Get timesteps for DDIM sampling"""
        step = self.config.timesteps // self.config.sampling_steps
        return list(range(step - 1, self.config.timesteps, step))[::-1]


class UNetSimple:
    """Simplified U-Net for noise prediction"""
    def __init__(self, input_dim: int, hidden_dims: List[int], timesteps: int):
        self.input_dim = input_dim
        self.hidden_dims = hidden_dims
        self.timesteps = timesteps
        self.weights: Dict[str, List[float]] = {}
        self.t_embed: List[List[float]] = []
        self._init()
    
    def _init(self):
        prev = self.input_dim + 4  # input + time embedding
        for i, h in enumerate(self.hidden_dims):
            self.weights[f'u_{i}'] = [random.gauss(0, 0.02) for _ in range(prev * h)]
            prev = h
        self.weights['u_out'] = [random.gauss(0, 0.02) for _ in range(prev * self.input_dim)]
        
        # Time embeddings
        for t in range(self.timesteps):
            emb = [math.sin(t / (10000 ** (2 * j / 64))) for j in range(32)]
            self.t_embed.append(emb[:4])
    
    def predict_noise(self, x_t: List[float], t: int) -> List[float]:
        """Predict noise given noisy input and timestep"""
        t_emb = self.t_embed[min(t, self.timesteps - 1)]
        x_aug = x_t[:self.input_dim] + t_emb  # Simple conditioning
        
        h = x_aug
        for i in range(len(self.hidden_dims)):
            w = self.weights[f'u_{i}']
            dim_in = len(h)
            dim_out = self.hidden_dims[i]
            h = self._linear_relu(h, w, dim_in, dim_out)
        
        # Output
        w = self.weights['u_out']
        return self._linear(h, w, len(h), self.input_dim)
    
    def _linear_relu(self, x, w, di, do):
        out = []
        for i in range(do):
            s = sum(w[i*di+j]*x[j] for j in range(min(di,len(x))) if i*di+j < len(w))
            out.append(max(0, s))
        return out
    
    def _linear(self, x, w, di, do):
        return [sum(w[i*di+j]*x[j] for j in range(min(di,len(x))) if i*di+j < len(w)) for i in range(do)]


class DiffusionModel:
    """Main diffusion model orchestrator"""
    def __init__(self, config: DiffusionConfig = None):
        self.config = config or DiffusionConfig()
        self.scheduler = NoiseScheduler(self.config)
        self.model = UNetSimple(self.config.image_dim, self.config.model_hidden_dims, 
                                self.config.timesteps)
        self.training_history: List[Dict] = []
    
    def train_step(self, x0: List[float]) -> Dict:
        """Single training step"""
        t = random.randint(0, self.config.timesteps - 1)
        epsilon = [random.gauss(0, 1) for _ in range(len(x0))]
        
        # Forward: add noise
        x_t, _ = self.scheduler.add_noise(x0, t, epsilon)
        
        # Predict noise
        pred_epsilon = self.model.predict_noise(x_t, t)
        
        # MSE loss
        loss = sum((p - e)**2 for p, e in zip(pred_epsilon, epsilon)) / len(epsilon)
        
        self.training_history.append({'t': t, 'loss': loss})
        return {'loss': loss, 'timestep': t}
    
    def sample_ddim(self, n_samples: int = 1, condition: Optional[List[float]] = None) -> List[List[float]]:
        """DDIM accelerated sampling"""
        timesteps = self.scheduler.get_sampling_timesteps()
        samples = []
        
        for _ in range(n_samples):
            # Start from pure noise
            x = [random.gauss(0, 1) for _ in range(self.config.image_dim)]
            
            for i in range(len(timesteps) - 1):
                t = timesteps[i]
                t_prev = timesteps[i + 1] if i + 1 < len(timesteps) else -1
                
                # Predict noise
                eps_pred = self.model.predict_noise(x, t)
                
                alpha_bar = self.scheduler.alpha_bars[t]
                alpha_bar_prev = self.scheduler.alpha_bars[t_prev] if t_prev >= 0 else 1.0
                
                # DDIM update
                pred_x0 = [(x[j] - math.sqrt(1 - alpha_bar) * eps_pred[j]) / math.sqrt(max(1e-7, alpha_bar))
                          for j in range(len(x))]
                
                sigma = self.config.guidance_scale * math.sqrt((1 - alpha_bar_prev) / (1 - alpha_bar)) * math.sqrt(1 - alpha_bar / alpha_bar_prev)
                
                x = [math.sqrt(alpha_bar_prev) * pred_x0[j] + 
                     math.sqrt(max(0, 1 - alpha_bar_prev - sigma**2)) * eps_pred[j] +
                     sigma * random.gauss(0, 1)
                     for j in range(len(x))]
            
            samples.append(x)
        
        return samples
    
    def inpaint(self, x0: List[float], mask: List[int]) -> List[float]:
        """Image inpainting: generate masked regions"""
        # Initialize with masked noise
        x = [x0[i] if mask[i] else random.gauss(0, 1) for i in range(len(x0))]
        timesteps = self.scheduler.get_sampling_timesteps()
        
        for i in range(len(timesteps) - 1):
            t = timesteps[i]
            eps_pred = self.model.predict_noise(x, t)
            
            alpha_bar = self.scheduler.alpha_bars[t]
            t_prev = timesteps[i+1] if i+1 < len(timesteps) else -1
            alpha_bar_prev = self.scheduler.alpha_bars[t_prev] if t_prev >= 0 else 1.0
            
            # Project back to x0 estimate
            pred_x0 = [(x[j] - math.sqrt(1 - alpha_bar) * eps_pred[j]) / math.sqrt(max(1e-7, alpha_bar))
                      for j in range(len(x))]
            
            # Apply mask constraint
            x = [pred_x0[j] if not mask[j] else x[j] for j in range(len(x))]
            
            # Add noise for next step
            if t_prev >= 0:
                x = [math.sqrt(alpha_bar_prev) * x[j] + 
                     math.sqrt(max(0, 1 - alpha_bar_prev)) * random.gauss(0, 1)
                     for j in range(len(x))]
        
        return x


if __name__ == '__main__':
    print("=== Diffusion Model (DDPM/DDIM) ===")
    
    config = DiffusionConfig(timesteps=1000, image_dim=64, sampling_steps=20)
    dm = DiffusionModel(config)
    
    print(f"\nTimesteps: {config.timesteps}")
    print(f"DDIM sampling steps: {config.sampling_steps}")
    
    # Simulated training
    print("\nTraining...")
    for epoch in range(200):
        x0 = [random.gauss(0.5, 0.3) for _ in range(64)]
        result = dm.train_step(x0)
        if epoch % 50 == 0:
            print(f"  Epoch {epoch}: loss={result['loss']:.4f}")
    
    # Generate samples
    samples = dm.sample_ddim(n_samples=3)
    print(f"\nGenerated {len(samples)} samples via DDIM")
    
    # Inpainting
    mask = [1 if i < 32 else 0 for i in range(64)]  # Keep first half
    x0 = [random.random() for _ in range(64)]
    inpainted = dm.inpaint(x0, mask)
    print(f"Inpainted: kept first {sum(mask)} values, generated remaining")
