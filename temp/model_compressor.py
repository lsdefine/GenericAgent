#!/usr/bin/env python3
"""
Model Compression Toolkit for GenericAgent
模型压缩工具: 剪枝(Pruning)、量化(Quantization)、知识蒸馏、低秩分解
支持: 结构化/非结构化剪枝、INT8/FP16量化、SVD分解、压缩率评估
"""

import os
import json
import math
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class CompressionStats:
    original_size: float  # bytes
    compressed_size: float
    compression_ratio: float
    accuracy_drop: float
    method: str

@dataclass
class LayerWeights:
    name: str
    weights: List[List[float]]
    shape: Tuple[int, int]


class PruningEngine:
    """Model pruning: remove redundant weights"""
    def __init__(self):
        pass
    
    def magnitude_pruning(self, weights: List[List[float]], sparsity: float = 0.5) -> Tuple[List[List[float]], int]:
        """Unstructured pruning based on weight magnitude"""
        # Flatten and find threshold
        flat = []
        for row in weights:
            flat.extend([(abs(w), i, j) for i, row in enumerate(weights) for j, w in enumerate(row)])
        
        flat.sort(key=lambda x: x[0])
        n_prune = int(len(flat) * sparsity)
        threshold = flat[n_prune - 1][0] if n_prune > 0 else 0
        
        pruned = [[0.0 if abs(w) < threshold else w for w in row] for row in weights]
        n_zeros = sum(1 for row in pruned for w in row if w == 0.0)
        
        return pruned, n_zeros
    
    def structured_pruning(self, weights: List[List[float]], row_sparsity: float = 0.3) -> Tuple[List[List[float]], int]:
        """Remove entire rows/columns based on L2 norm"""
        row_norms = [(math.sqrt(sum(w**2 for w in row)), i) for i, row in enumerate(weights)]
        row_norms.sort(key=lambda x: x[0])
        
        n_remove = int(len(row_norms) * row_sparsity)
        remove_indices = set(idx for _, idx in row_norms[:n_remove])
        
        pruned = [row for i, row in enumerate(weights) if i not in remove_indices]
        return pruned, n_remove


class Quantizer:
    """Model quantization: reduce precision"""
    def __init__(self):
        pass
    
    def uniform_quantization(self, weights: List[List[float]], bits: int = 8) -> Tuple[List[List[float]], float, float]:
        """Uniform quantization to specified bit width"""
        flat = [w for row in weights for w in row]
        min_val, max_val = min(flat), max(flat)
        
        scale = (max_val - min_val) / (2**bits - 1)
        zero_point = -min_val / scale
        
        quantized = []
        for row in weights:
            q_row = []
            for w in row:
                q = round(w / scale + zero_point)
                q = max(0, min(2**bits - 1, q))
                q_row.append(q * scale - zero_point * scale)
            quantized.append(q_row)
        
        # Compute error
        mse = sum((a - b)**2 for row_a, row_b in zip(weights, quantized) for a, b in zip(row_a, row_b))
        mse /= len(flat)
        
        return quantized, scale, math.sqrt(mse)
    
    def fp16_quantization(self, weights: List[List[float]]) -> float:
        """Estimate FP16 compression ratio"""
        return 0.5  # 32-bit -> 16-bit


class LowRankDecomposition:
    """SVD-based low-rank approximation"""
    def __init__(self):
        pass
    
    def svd_compress(self, weights: List[List[float]], rank: int = None) -> Tuple[List[List[float]], List[List[float]], int]:
        """Simplified SVD decomposition"""
        rows = len(weights)
        cols = len(weights[0]) if rows > 0 else 0
        
        if rank is None:
            rank = max(1, min(rows, cols) // 2)
        
        rank = min(rank, rows, cols)
        
        # Simplified: split into two low-rank matrices
        # U: rows x rank, V: rank x cols
        U = [[weights[i][j] if j < rank else 0.0 for j in range(rank)] for i in range(rows)]
        V = [[1.0 if i == j else 0.0 for j in range(cols)] for i in range(rank)]
        
        # Compute approximation error
        reconstructed = [[sum(U[i][k] * V[k][j] for k in range(rank)) for j in range(cols)] for i in range(rows)]
        error = sum((weights[i][j] - reconstructed[i][j])**2 for i in range(rows) for j in range(cols))
        
        original_params = rows * cols
        compressed_params = rows * rank + rank * cols
        
        return U, V, compressed_params


class KnowledgeDistillation:
    """Knowledge distillation: train student with teacher guidance"""
    def __init__(self, temperature: float = 2.0, alpha: float = 0.5):
        self.temperature = temperature
        self.alpha = alpha
    
    def softmax(self, logits: List[float], T: float = 1.0) -> List[float]:
        scaled = [l / T for l in logits]
        max_l = max(scaled)
        exp_l = [math.exp(l - max_l) for l in scaled]
        total = sum(exp_l)
        return [e / total for e in exp_l]
    
    def distillation_loss(self, student_logits: List[float], teacher_logits: List[float],
                         true_labels: List[float]) -> float:
        """Combined hard + soft loss"""
        # Soft loss (KL divergence)
        student_soft = self.softmax(student_logits, self.temperature)
        teacher_soft = self.softmax(teacher_logits, self.temperature)
        
        soft_loss = 0.0
        for s, t in zip(student_soft, teacher_soft):
            if t > 0:
                soft_loss += t * math.log(t / (s + 1e-10))
        soft_loss *= self.temperature ** 2
        
        # Hard loss (cross-entropy)
        student_hard = self.softmax(student_logits, 1.0)
        hard_loss = 0.0
        for s, y in zip(student_hard, true_labels):
            if y > 0 and s > 0:
                hard_loss -= y * math.log(s)
        
        return self.alpha * soft_loss + (1 - self.alpha) * hard_loss
    
    def update_student(self, student_weights: List[float], lr: float = 0.01) -> List[float]:
        """Simplified student weight update"""
        return [w - lr * 0.01 for w in student_weights]


class ModelCompressor:
    """Main compression orchestrator"""
    def __init__(self):
        self.pruning = PruningEngine()
        self.quantizer = Quantizer()
        self.decomposition = LowRankDecomposition()
        self.distillation = KnowledgeDistillation()
    
    def compress(self, model_weights: Dict[str, List[List[float]]], 
                 method: str = "pruning", **kwargs) -> Tuple[Dict, CompressionStats]:
        """Apply compression method to model"""
        original_size = sum(len(row) * 4 for layer in model_weights.values() for row in layer)
        compressed = {}
        
        if method == "pruning":
            sparsity = kwargs.get('sparsity', 0.5)
            for name, weights in model_weights.items():
                pruned, _ = self.pruning.magnitude_pruning(weights, sparsity)
                compressed[name] = pruned
        
        elif method == "quantization":
            bits = kwargs.get('bits', 8)
            for name, weights in model_weights.items():
                quantized, _, _ = self.quantizer.uniform_quantization(weights, bits)
                compressed[name] = quantized
        
        elif method == "svd":
            rank = kwargs.get('rank', None)
            for name, weights in model_weights.items():
                U, V, _ = self.decomposition.svd_compress(weights, rank)
                compressed[f"{name}_U"] = U
                compressed[f"{name}_V"] = V
        
        compressed_size = sum(len(row) * 4 for layer in compressed.values() for row in layer)
        ratio = compressed_size / original_size if original_size > 0 else 1.0
        
        stats = CompressionStats(
            original_size=original_size,
            compressed_size=compressed_size,
            compression_ratio=ratio,
            accuracy_drop=0.0,
            method=method
        )
        
        return compressed, stats


if __name__ == '__main__':
    print("=== Model Compression Toolkit ===")
    
    # Create dummy model
    import random
    model = {
        'fc1': [[random.uniform(-1, 1) for _ in range(64)] for _ in range(32)],
        'fc2': [[random.uniform(-1, 1) for _ in range(32)] for _ in range(16)],
        'output': [[random.uniform(-1, 1) for _ in range(10)] for _ in range(16)]
    }
    
    compressor = ModelCompressor()
    
    # Pruning
    print("\n--- Pruning (50% sparsity) ---")
    pruned, stats = compressor.compress(model, method="pruning", sparsity=0.5)
    print(f"Original: {stats.original_size / 1024:.1f}KB, Compressed: {stats.compressed_size / 1024:.1f}KB")
    print(f"Compression ratio: {stats.compression_ratio:.2f}")
    
    # Quantization
    print("\n--- Quantization (INT8) ---")
    quantized, stats = compressor.compress(model, method="quantization", bits=8)
    print(f"Compression ratio: {stats.compression_ratio:.2f}")
    
    # SVD
    print("\n--- SVD Decomposition ---")
    svd, stats = compressor.compress(model, method="svd", rank=8)
    print(f"Compression ratio: {stats.compression_ratio:.2f}")
    
    # Knowledge Distillation
    print("\n--- Knowledge Distillation ---")
    teacher_logits = [2.0, 1.0, 0.1]
    student_logits = [1.5, 1.2, 0.3]
    labels = [1.0, 0.0, 0.0]
    loss = compressor.distillation.distillation_loss(student_logits, teacher_logits, labels)
    print(f"Distillation loss: {loss:.4f}")
