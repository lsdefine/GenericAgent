#!/usr/bin/env python3
"""
Causal Representation Learning for GenericAgent
因果表征学习: 从数据中发现因果因子, 解耦表示学习
支持: 信息瓶颈、独立成分分析近似、因果因子提取
"""

import os
import math
import random
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class CausalEncoder:
    """因果编码器: 将高维输入映射到因果因子空间"""
    
    def __init__(self, input_dim: int, latent_dim: int,
                 hidden_dim: int = 64, seed: int = 42):
        self.input_dim = input_dim
        self.latent_dim = latent_dim
        random.seed(seed)
        
        # 两层编码器
        self.W1 = [[random.gauss(0, 0.1) for _ in range(hidden_dim)] 
                   for _ in range(input_dim)]
        self.b1 = [0.0] * hidden_dim
        self.W2 = [[random.gauss(0, 0.1) for _ in range(latent_dim)] 
                   for _ in range(hidden_dim)]
        self.b2 = [0.0] * latent_dim
    
    def encode(self, x: List[float]) -> List[float]:
        """前向编码"""
        # Layer 1
        h = []
        for j in range(len(self.b1)):
            val = self.b1[j]
            for i in range(self.input_dim):
                val += x[i] * self.W1[i][j]
            h.append(max(0, val))  # ReLU
        
        # Layer 2 (linear)
        z = []
        for j in range(self.latent_dim):
            val = self.b2[j]
            for i in range(len(h)):
                val += h[i] * self.W2[i][j]
            z.append(val)
        return z


class IndependenceRegularizer:
    """独立性正则化: 促进因果因子解耦"""
    
    @staticmethod
    def correlation_penalty(z_batch: List[List[float]]) -> float:
        """基于相关系数的惩罚项"""
        n = len(z_batch)
        if n < 2:
            return 0.0
        dim = len(z_batch[0])
        penalty = 0.0
        count = 0
        
        for i in range(dim):
            for j in range(i+1, dim):
                # 计算皮尔逊相关系数
                zi = [z[i] for z in z_batch]
                zj = [z[j] for z in z_batch]
                
                mean_i = sum(zi) / n
                mean_j = sum(zj) / n
                
                cov = sum((zi[k] - mean_i) * (zj[k] - mean_j) for k in range(n)) / n
                std_i = math.sqrt(sum((z - mean_i)**2 for z in zi) / n + 1e-8)
                std_j = math.sqrt(sum((z - mean_j)**2 for z in zj) / n + 1e-8)
                
                corr = cov / (std_i * std_j)
                penalty += corr ** 2
                count += 1
        
        return penalty / max(count, 1)
    
    @staticmethod
    def total_correlation(z_batch: List[List[float]]) -> float:
        """总相关性近似 (基于边缘-联合熵差)"""
        n = len(z_batch)
        if n < 2:
            return 0.0
        dim = len(z_batch[0])
        
        # 简化的基于方差比的TC估计
        marginal_var_sum = 0.0
        joint_var = 0.0
        
        for d in range(dim):
            vals = [z[d] for z in z_batch]
            mean = sum(vals) / n
            var = sum((v - mean)**2 for v in vals) / n
            marginal_var_sum += math.log(var + 1e-8)
        
        # 联合方差 (近似)
        all_vals = [v for z in z_batch for v in z]
        grand_mean = sum(all_vals) / (n * dim)
        joint_var = sum((v - grand_mean)**2 for v in all_vals) / (n * dim)
        joint_log = math.log(joint_var + 1e-8)
        
        return abs(marginal_var_sum - dim * joint_log)


class CausalRepresentationLearner:
    """因果表征学习编排器"""
    
    def __init__(self, input_dim: int, latent_dim: int,
                 beta: float = 1.0):  # beta控制解耦强度
        self.encoder = CausalEncoder(input_dim, latent_dim)
        self.beta = beta
        self.regularizer = IndependenceRegularizer()
        self.history = []
    
    def train(self, X: List[List[float]], epochs: int = 50, 
              lr: float = 0.001) -> Dict:
        """训练因果表征"""
        eps = 1e-5
        n = len(X)
        
        for epoch in range(epochs):
            # 编码全部样本
            Z = [self.encoder.encode(x) for x in X]
            
            # 重建损失 (简化: 自编码目标)
            recon_loss = 0.0
            for i, (x, z) in enumerate(zip(X, Z)):
                recon = sum(z[j]**2 for j in range(len(z)))  # 简化重建
                recon_loss += sum((x[k] - recon * 0.1)**2 for k in range(len(x)))
            recon_loss /= n
            
            # 独立性正则
            indep_loss = self.regularizer.correlation_penalty(Z)
            
            # 总损失
            total_loss = recon_loss + self.beta * indep_loss
            
            # 数值梯度更新
            for i in range(len(self.encoder.W1)):
                for j in range(len(self.encoder.W1[i])):
                    self.encoder.W1[i][j] += eps
                    Z_new = [self.encoder.encode(x) for x in X]
                    recon_new = sum(sum((x[k] - sum(z[d]**2 for d in range(len(z))) * 0.1)**2 
                                       for k in range(len(x))) for x, z in zip(X, Z_new)) / n
                    indep_new = self.regularizer.correlation_penalty(Z_new)
                    loss_new = recon_new + self.beta * indep_new
                    self.encoder.W1[i][j] -= 2*eps
                    
                    loss_old = total_loss
                    grad = (loss_new - loss_old) / (2*eps)
                    self.encoder.W1[i][j] -= lr * grad
            
            if epoch % 10 == 0:
                self.history.append({
                    'epoch': epoch,
                    'recon_loss': recon_loss,
                    'indep_loss': indep_loss,
                    'total_loss': total_loss
                })
        
        return {
            'history': self.history,
            'final_loss': total_loss
        }
    
    def extract_factors(self, x: List[float]) -> List[float]:
        """提取因果因子"""
        return self.encoder.encode(x)


if __name__ == '__main__':
    print("=== Causal Representation Learning Demo ===")
    
    # 生成解耦数据: x = [c1 + noise, c2 + noise, c1*c2 + noise]
    random.seed(42)
    n = 100
    X = []
    true_c1 = [random.uniform(-1, 1) for _ in range(n)]
    true_c2 = [random.uniform(-1, 1) for _ in range(n)]
    
    for i in range(n):
        c1, c2 = true_c1[i], true_c2[i]
        x = [c1 + random.gauss(0, 0.1),
             c2 + random.gauss(0, 0.1),
             c1 * c2 + random.gauss(0, 0.1)]
        X.append(x)
    
    learner = CausalRepresentationLearner(input_dim=3, latent_dim=2, beta=0.5)
    print("Training causal representation learner...")
    result = learner.train(X, epochs=30, lr=0.001)
    
    print(f"\nFinal reconstruction loss: {result['history'][-1]['recon_loss']:.4f}")
    print(f"Final independence penalty: {result['history'][-1]['indep_loss']:.4f}")
    print(f"Total loss: {result['history'][-1]['total_loss']:.4f}")
    
    # 测试提取
    test_x = [0.5, -0.3, 0.5*(-0.3)]
    factors = learner.extract_factors(test_x)
    print(f"\nTest input: {test_x}")
    print(f"Extracted causal factors: [{factors[0]:.3f}, {factors[1]:.3f}]")
