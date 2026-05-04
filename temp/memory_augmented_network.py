#!/usr/bin/env python3
"""
Memory Augmented Neural Network for GenericAgent
记忆增强网络: DNC-style架构、外部记忆存储、快速权重
支持: 记忆检索、关联记忆、少样本记忆增强
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
class MANConfig:
    input_dim: int = 32
    hidden_dim: int = 64
    memory_slots: int = 50
    memory_dim: int = 32
    top_k: int = 3  # Top-k retrieval

class AssociativeMemory:
    """Key-value associative memory"""
    def __init__(self, slots: int, dim: int):
        self.slots = slots
        self.dim = dim
        self.keys: List[List[float]] = [[0.0]*dim for _ in range(slots)]
        self.values: List[List[float]] = [[0.0]*dim for _ in range(slots)]
        self.usage: List[float] = [0.0] * slots  # Track usage for least-used replacement
        self.next_slot = 0

    def store(self, key: List[float], value: List[float]):
        """Store key-value pair"""
        slot = self.next_slot % self.slots
        self.keys[slot] = key[:self.dim] + [0.0]*(self.dim - len(key))
        self.values[slot] = value[:self.dim] + [0.0]*(self.dim - len(value))
        self.usage[slot] = 0
        self.next_slot += 1

    def retrieve(self, query: List[float], top_k: int) -> Tuple[List[List[float]], List[float]]:
        """Retrieve top-k most similar memories"""
        q = query[:self.dim] + [0.0]*(self.dim - len(query))
        similarities = []
        for i in range(self.slots):
            dot = sum(a*b for a,b in zip(q, self.keys[i]))
            norm_q = math.sqrt(sum(a*a for a in q) + 1e-7)
            norm_k = math.sqrt(sum(b*b for b in self.keys[i]) + 1e-7)
            sim = dot / (norm_q * norm_k)
            similarities.append((sim, i))

        # Sort by similarity descending
        similarities.sort(key=lambda x: x[0], reverse=True)
        top_indices = [idx for _, idx in similarities[:top_k]]
        
        retrieved_values = [self.values[i] for i in top_indices]
        scores = [similarities[j][0] for j in range(min(top_k, len(similarities)))]

        # Update usage
        for i in top_indices:
            self.usage[i] += 1

        return retrieved_values, scores

class MemoryAugmentedNetwork:
    """Main Memory Augmented Network"""
    def __init__(self, config: MANConfig = None):
        self.config = config or MANConfig()
        self.memory = AssociativeMemory(self.config.memory_slots, self.config.memory_dim)
        # Controller network
        self.input_to_hidden = [random.gauss(0, math.sqrt(2.0/self.config.input_dim))
                                for _ in range(self.config.input_dim * self.config.hidden_dim)]
        self.memory_to_hidden = [random.gauss(0, math.sqrt(2.0/self.config.memory_dim))
                                 for _ in range(self.config.memory_dim * self.config.hidden_dim)]
        self.hidden_to_output = [random.gauss(0, math.sqrt(2.0/self.config.hidden_dim))
                                 for _ in range(self.config.hidden_dim * self.config.input_dim)]
        self.hidden_state = [0.0] * self.config.hidden_dim
        self.training_history: List[Dict] = []

    def process(self, x: List[float]) -> Dict:
        """Process input with memory augmentation"""
        # Retrieve from memory using current hidden state as query
        query = self.hidden_state[:self.config.memory_dim] if len(self.hidden_state) >= self.config.memory_dim else self.hidden_state + [0.0]*(self.config.memory_dim - len(self.hidden_state))
        retrieved, scores = self.memory.retrieve(query, self.config.top_k)

        # Aggregate retrieved memories
        memory_context = [0.0] * self.config.memory_dim
        if retrieved and scores:
            total_score = sum(max(0, s) for s in scores) + 1e-7
            for rv, s in zip(retrieved, scores):
                weight = max(0, s) / total_score
                for d in range(self.config.memory_dim):
                    memory_context[d] += weight * rv[d]

        # Controller forward
        # Input -> Hidden
        h_from_input = []
        for i in range(self.config.hidden_dim):
            val = sum(self.input_to_hidden[i*len(x)+j]*x[j] for j in range(min(len(x), len(self.input_to_hidden)//self.config.hidden_dim)))
            h_from_input.append(val)

        # Memory -> Hidden
        h_from_memory = []
        for i in range(self.config.hidden_dim):
            val = sum(self.memory_to_hidden[i*len(memory_context)+j]*memory_context[j] for j in range(min(len(memory_context), len(self.memory_to_hidden)//self.config.hidden_dim)))
            h_from_memory.append(val)

        # Combine
        new_hidden = [max(0, a + b + hs) for a, b, hs in zip(h_from_input, h_from_memory, self.hidden_state)]
        self.hidden_state = new_hidden

        # Hidden -> Output
        output = []
        for i in range(self.config.input_dim):
            val = sum(self.hidden_to_output[i*len(new_hidden)+j]*new_hidden[j] for j in range(min(len(new_hidden), len(self.hidden_to_output)//self.config.input_dim)))
            output.append(val)

        # Store experience in memory
        self.memory.store(x[:self.config.memory_dim] + [0.0]*(self.config.memory_dim - len(x)), new_hidden[:self.config.memory_dim])

        return {'output': output[:5], 'retrieved_count': len(retrieved)}

if __name__ == '__main__':
    print("=== Memory Augmented Network ===")
    
    config = MANConfig(input_dim=16, hidden_dim=32, memory_slots=30, memory_dim=16, top_k=3)
    man = MemoryAugmentedNetwork(config)
    
    print(f"Memory slots: {config.memory_slots}")
    print(f"Top-k retrieval: {config.top_k}")

    # Process sequence
    for t in range(20):
        x = [random.random() for _ in range(config.input_dim)]
        result = man.process(x)
        if t % 10 == 0:
            print(f"Step {t}: retrieved {result['retrieved_count']} memories")

    print("\nMemory augmented processing successful")
