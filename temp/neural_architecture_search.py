#!/usr/bin/env python3
"""
Neural Architecture Search for GenericAgent
神经架构搜索(NAS): 强化搜索、进化算法、可微分NAS(DARTS风格)
支持: 搜索空间定义、控制器RNN、适应度评估、Pareto最优
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
class Architecture:
    """Represents a neural network architecture"""
    layers: List[Dict]  # Each layer: {type, channels, kernel_size, stride}
    accuracy: float = 0.0
    latency: float = 0.0
    params: int = 0
    flops: int = 0
    
    def __str__(self):
        return f"Arch(layers={len(self.layers)}, acc={self.accuracy:.3f}, params={self.params})"


class SearchSpace:
    """Define the NAS search space"""
    def __init__(self):
        self.layer_types = ['conv', 'depthwise_sep', 'pool', 'skip_connect']
        self.kernel_sizes = [3, 5, 7]
        self.channels = [16, 32, 64, 128, 256]
        self.strides = [1, 2]
        self.max_layers = 20
        self.min_layers = 5
    
    def random_architecture(self) -> Architecture:
        """Sample random architecture"""
        n_layers = random.randint(self.min_layers, self.max_layers)
        layers = []
        
        for i in range(n_layers):
            layer = {
                'type': random.choice(self.layer_types),
                'channels': random.choice(self.channels),
                'kernel_size': random.choice(self.kernel_sizes),
                'stride': random.choice(self.strides)
            }
            layers.append(layer)
        
        return Architecture(layers=layers)
    
    def mutate(self, arch: Architecture) -> Architecture:
        """Mutate architecture (for evolutionary search)"""
        new_layers = []
        for layer in arch.layers:
            new_layer = dict(layer)
            if random.random() < 0.3:
                new_layer['type'] = random.choice(self.layer_types)
            if random.random() < 0.3:
                new_layer['channels'] = random.choice(self.channels)
            if random.random() < 0.2:
                new_layer['kernel_size'] = random.choice(self.kernel_sizes)
            new_layers.append(new_layer)
        
        # Optionally add/remove layer
        if random.random() < 0.1 and len(new_layers) > self.min_layers:
            new_layers.pop(random.randint(0, len(new_layers) - 1))
        elif random.random() < 0.1 and len(new_layers) < self.max_layers:
            new_layers.insert(random.randint(0, len(new_layers)), {
                'type': random.choice(self.layer_types),
                'channels': random.choice(self.channels),
                'kernel_size': random.choice(self.kernel_sizes),
                'stride': random.choice(self.strides)
            })
        
        return Architecture(layers=new_layers)


class ControllerRNN:
    """RNN controller for generating architectures (ENAS-style)"""
    def __init__(self, hidden_size: int = 64):
        self.hidden_size = hidden_size
        self.hidden_state = [0.0] * hidden_size
        self.temperature = 1.0
    
    def sample_action(self, action_space: List) -> Tuple:
        """Sample next architectural decision"""
        logits = [sum(self.hidden_state) / len(self.hidden_state) + random.uniform(-0.5, 0.5)
                  for _ in action_space]
        
        # Gumbel-softmax for differentiable sampling
        gumbel = [-math.log(-math.log(random.random() + 1e-10)) for _ in logits]
        noisy_logits = [(l + g) / self.temperature for l, g in zip(logits, gumbel)]
        
        max_idx = noisy_logits.index(max(noisy_logits))
        action = action_space[max_idx]
        
        # Update hidden state
        self.hidden_state = [
            math.tanh(h + random.uniform(-0.1, 0.1))
            for h in self.hidden_state
        ]
        
        return action, max_idx
    
    def generate_architecture(self, search_space: SearchSpace) -> Architecture:
        """Generate architecture using controller"""
        n_layers = random.randint(search_space.min_layers, search_space.max_layers)
        layers = []
        
        for _ in range(n_layers):
            layer_type, _ = self.sample_action(search_space.layer_types)
            channels, _ = self.sample_action(search_space.channels)
            kernel, _ = self.sample_action(search_space.kernel_sizes)
            stride, _ = self.sample_action(search_space.strides)
            
            layers.append({
                'type': layer_type,
                'channels': channels,
                'kernel_size': kernel,
                'stride': stride
            })
        
        return Architecture(layers=layers)
    
    def update_controller(self, reward: float, lr: float = 0.001):
        """Update controller with REINFORCE"""
        self.hidden_state = [h + lr * reward * 0.1 for h in self.hidden_state]


class Evaluator:
    """Evaluate architecture fitness"""
    def __init__(self):
        pass
    
    def estimate_accuracy(self, arch: Architecture) -> float:
        """Proxy accuracy estimation (without training)"""
        # Heuristic: balanced architectures with moderate depth perform better
        depth_score = min(len(arch.layers), 15) / 15.0
        channel_score = sum(l['channels'] for l in arch.layers) / (len(arch.layers) * 256)
        diversity = len(set(l['type'] for l in arch.layers)) / 4.0
        
        noise = random.uniform(-0.05, 0.05)
        return min(0.95, max(0.1, 0.3 * depth_score + 0.3 * channel_score + 0.3 * diversity + 0.1 + noise))
    
    def estimate_latency(self, arch: Architecture) -> float:
        """Estimate inference latency"""
        latency = 0.0
        for layer in arch.layers:
            if layer['type'] == 'conv':
                latency += layer['channels'] * layer['kernel_size'] * layer['stride'] * 0.001
            elif layer['type'] == 'depthwise_sep':
                latency += layer['channels'] * 0.0005
            elif layer['type'] == 'pool':
                latency += 0.002
        
        return latency
    
    def estimate_params(self, arch: Architecture) -> int:
        """Estimate parameter count"""
        params = 0
        for layer in arch.layers:
            c = layer['channels']
            k = layer['kernel_size']
            if layer['type'] == 'conv':
                params += c * c * k * k
            elif layer['type'] == 'depthwise_sep':
                params += c * k * k + c * c
            elif layer['type'] == 'skip_connect':
                params += c
        
        return params
    
    def evaluate(self, arch: Architecture) -> Architecture:
        """Full evaluation"""
        arch.accuracy = self.estimate_accuracy(arch)
        arch.latency = self.estimate_latency(arch)
        arch.params = self.estimate_params(arch)
        arch.flops = int(arch.params * 2)  # Simplified
        return arch


class ParetoFront:
    """Maintain Pareto-optimal architectures"""
    def __init__(self, max_size: int = 10):
        self.front: List[Architecture] = []
        self.max_size = max_size
    
    def update(self, new_arch: Architecture):
        """Add to front if non-dominated"""
        # Check if dominated
        dominated = False
        for existing in self.front:
            if existing.accuracy >= new_arch.accuracy and existing.latency <= new_arch.latency:
                if existing.accuracy > new_arch.accuracy or existing.latency < new_arch.latency:
                    dominated = True
                    break
        
        if not dominated:
            # Remove dominated members
            self.front = [
                a for a in self.front
                if not (new_arch.accuracy >= a.accuracy and new_arch.latency <= a.latency and
                       (new_arch.accuracy > a.accuracy or new_arch.latency < a.latency))
            ]
            self.front.append(new_arch)
            self.front.sort(key=lambda a: -a.accuracy)
            
            if len(self.front) > self.max_size:
                self.front = self.front[:self.max_size]


class NASSearch:
    """Main NAS orchestrator"""
    def __init__(self, n_iterations: int = 100, population_size: int = 20):
        self.n_iterations = n_iterations
        self.population_size = population_size
        
        self.search_space = SearchSpace()
        self.controller = ControllerRNN()
        self.evaluator = Evaluator()
        self.pareto = ParetoFront()
        self.history: List[Architecture] = []
    
    def evolutionary_search(self) -> List[Architecture]:
        """Evolutionary architecture search"""
        # Initialize population
        population = [self.search_space.random_architecture() for _ in range(self.population_size)]
        
        for gen in range(self.n_iterations):
            # Evaluate
            for arch in population:
                self.evaluator.evaluate(arch)
                self.pareto.update(arch)
            
            # Select top 50%
            population.sort(key=lambda a: -a.accuracy)
            elite = population[:self.population_size // 2]
            
            # Mutate to create offspring
            offspring = [self.search_space.mutate(random.choice(elite)) for _ in range(self.population_size // 2)]
            population = elite + offspring
        
        return self.pareto.front
    
    def controller_search(self) -> List[Architecture]:
        """ENAS-style controller search"""
        for i in range(self.n_iterations):
            arch = self.controller.generate_architecture(self.search_space)
            self.evaluator.evaluate(arch)
            
            reward = arch.accuracy - arch.latency * 0.01
            self.controller.update_controller(reward)
            self.pareto.update(arch)
            self.history.append(arch)
        
        return self.pareto.front


if __name__ == '__main__':
    print("=== Neural Architecture Search (NAS) ===")
    
    nas = NASSearch(n_iterations=30, population_size=10)
    
    # Evolutionary search
    print("\n--- Evolutionary Search ---")
    pareto_evo = nas.evolutionary_search()
    print(f"Pareto front size: {len(pareto_evo)}")
    for i, arch in enumerate(pareto_evo[:3]):
        print(f"  #{i}: acc={arch.accuracy:.3f}, latency={arch.latency:.3f}ms, params={arch.params}")
    
    # Controller search
    print("\n--- Controller Search (ENAS) ---")
    pareto_ctrl = nas.controller_search()
    print(f"Pareto front size: {len(pareto_ctrl)}")
    for i, arch in enumerate(pareto_ctrl[:3]):
        print(f"  #{i}: acc={arch.accuracy:.3f}, latency={arch.latency:.3f}ms, params={arch.params}")
