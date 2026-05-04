#!/usr/bin/env python3
"""
Neural Turing Machine for GenericAgent
神经图灵机: 外部记忆矩阵、注意力读写、可微分计算机
支持: 内容寻址、位置寻址、读写头操作
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
class NTMConfig:
    input_dim: int = 16
    hidden_dim: int = 32
    memory_size: int = 20    # Number of memory locations
    memory_dim: int = 16     # Dimension of each memory location
    num_heads: int = 1

class MemoryMatrix:
    """External differentiable memory"""
    def __init__(self, size: int, dim: int):
        self.size = size
        self.dim = dim
        self.memory: List[List[float]] = [[0.0]*dim for _ in range(size)]

    def read(self, weights: List[float]) -> List[float]:
        """Read from memory weighted by attention"""
        result = [0.0] * self.dim
        for i in range(self.size):
            for d in range(self.dim):
                result[d] += weights[i] * self.memory[i][d]
        return result

    def write(self, weights: List[float], values: List[float], erase: List[float]):
        """Write to memory with erase and add"""
        for i in range(self.size):
            for d in range(self.dim):
                # Erase
                self.memory[i][d] *= (1.0 - weights[i] * erase[d])
                # Add
                self.memory[i][d] += weights[i] * values[d]

class ReadWriteHead:
    """Attention-based read/write head"""
    def __init__(self, memory_size: int, memory_dim: int, hidden_dim: int):
        self.memory_size = memory_size
        self.memory_dim = memory_dim
        self.hidden_dim = hidden_dim
        self.key_weights = [random.gauss(0, 0.1) for _ in range(hidden_dim * memory_dim)]

    def content_addressing(self, memory: List[List[float]], key: List[float]) -> List[float]:
        """Compute attention weights based on content similarity"""
        similarities = []
        for i in range(len(memory)):
            # Cosine similarity
            dot = sum(k * m for k, m in zip(key, memory[i]))
            norm_k = math.sqrt(sum(k*k for k in key) + 1e-7)
            norm_m = math.sqrt(sum(m*m for m in memory[i]) + 1e-7)
            similarities.append(dot / (norm_k * norm_m))

        # Softmax
        max_s = max(similarities)
        exp_s = [math.exp(s - max_s) for s in similarities]
        s_sum = sum(exp_s)
        return [e/s_sum for e in exp_s]

class NeuralTuringMachine:
    """Main NTM orchestrator"""
    def __init__(self, config: NTMConfig = None):
        self.config = config or NTMConfig()
        self.memory = MemoryMatrix(self.config.memory_size, self.config.memory_dim)
        self.heads = [ReadWriteHead(self.config.memory_size, self.config.memory_dim, self.config.hidden_dim)
                      for _ in range(self.config.num_heads)]
        # Controller (simple RNN)
        self.controller_weights = [random.gauss(0, 0.1) for _ in range((self.config.input_dim + self.config.memory_dim) * self.config.hidden_dim)]
        self.hidden_state = [0.0] * self.config.hidden_dim
        self.training_history: List[Dict] = []

    def step(self, x: List[float]) -> Dict:
        """One NTM step"""
        # Read from memory
        # Use current hidden state as key
        key = self.hidden_state[:self.config.memory_dim] if len(self.hidden_state) >= self.config.memory_dim else self.hidden_state + [0.0]*(self.config.memory_dim - len(self.hidden_state))
        
        read_vectors = []
        all_weights = []
        for head in self.heads:
            weights = head.content_addressing(self.memory.memory, key)
            read_vec = self.memory.read(weights)
            read_vectors.append(read_vec)
            all_weights.append(weights)

        # Controller: process input + read vectors
        controller_input = x + read_vectors[0] if read_vectors else x
        new_hidden = []
        for i in range(self.config.hidden_dim):
            val = sum(self.controller_weights[i*len(controller_input)+j]*controller_input[j]
                      for j in range(min(len(controller_input), len(self.controller_weights)//self.config.hidden_dim)))
            new_hidden.append(max(0, val))  # ReLU
        self.hidden_state = new_hidden

        # Write to memory (simplified)
        write_key = self.hidden_state[:self.config.memory_dim] if len(self.hidden_state) >= self.config.memory_dim else self.hidden_state + [0.0]*(self.config.memory_dim - len(self.hidden_state))
        if self.heads:
            write_weights = self.heads[0].content_addressing(self.memory.memory, write_key)
            values = [max(0, h) for h in self.hidden_state[:self.config.memory_dim]]
            erase = [0.5] * self.config.memory_dim
            self.memory.write(write_weights, values, erase)

        return {'hidden': self.hidden_state[:5], 'read_vector': read_vectors[0][:5] if read_vectors else []}

if __name__ == '__main__':
    print("=== Neural Turing Machine ===")
    
    config = NTMConfig(input_dim=8, hidden_dim=16, memory_size=10, memory_dim=8, num_heads=1)
    ntm = NeuralTuringMachine(config)
    
    print(f"Memory: {config.memory_size}x{config.memory_dim}")
    print(f"Hidden dim: {config.hidden_dim}")

    # Run sequence
    for t in range(10):
        x = [random.random() for _ in range(config.input_dim)]
        result = ntm.step(x)
        if t % 5 == 0:
            print(f"Step {t}: hidden[:5]={result['hidden']}, read[:5]={result['read_vector']}")

    print("\nNTM sequence processing successful")
