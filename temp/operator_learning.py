#!/usr/bin/env python3
"""
Operator Learning for GenericAgent
算子学习: DeepONet架构，学习函数到函数的映射
支持: 分支- trunk网络、算子逼近、参数化PDE求解
"""

import os
import math
import random
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class BranchNetwork:
    """分支网络：编码输入函数（离散采样点）"""
    
    def __init__(self, input_dim: int, hidden_dims: List[int], 
                 output_dim: int, seed: int = 42):
        self.layers = []
        dims = [input_dim] + hidden_dims + [output_dim]
        for i in range(len(dims) - 1):
            act = 'tanh' if i < len(dims) - 2 else 'linear'
            self.layers.append(self._make_layer(dims[i], dims[i+1], act, seed+i))
    
    def _make_layer(self, in_dim, out_dim, act, seed):
        random.seed(seed)
        limit = math.sqrt(6.0 / (in_dim + out_dim))
        w = [[random.uniform(-limit, limit) for _ in range(out_dim)] for _ in range(in_dim)]
        b = [0.0] * out_dim
        return {'weights': w, 'biases': b, 'activation': act}
    
    def forward(self, x: List[float]) -> List[float]:
        out = x
        for layer in self.layers:
            new_out = []
            for j in range(len(layer['biases'])):
                val = layer['biases'][j]
                for i in range(len(out)):
                    val += out[i] * layer['weights'][i][j]
                if layer['activation'] == 'tanh':
                    val = math.tanh(val)
                elif layer['activation'] == 'relu':
                    val = max(0, val)
                new_out.append(val)
            out = new_out
        return out


class TrunkNetwork:
    """Trunk网络：编码查询坐标"""
    
    def __init__(self, coord_dim: int, hidden_dims: List[int],
                 output_dim: int, seed: int = 100):
        self.branch = BranchNetwork(coord_dim, hidden_dims, output_dim, seed)
    
    def forward(self, x: List[float]) -> List[float]:
        return self.branch.forward(x)


class DeepONet:
    """Deep Operator Network: 分支×Trunk内积"""
    
    def __init__(self, branch_input_dim: int, trunk_input_dim: int,
                 branch_hidden: List[int], trunk_hidden: List[int],
                 embedding_dim: int = 32):
        self.branch = BranchNetwork(branch_input_dim, branch_hidden, embedding_dim)
        self.trunk = TrunkNetwork(trunk_input_dim, trunk_hidden, embedding_dim)
        self.embedding_dim = embedding_dim
        self.training_log = []
    
    def forward(self, func_input: List[float], coord: List[float]) -> float:
        """计算DeepONet输出: b(u)·t(x) 内积"""
        b = self.branch.forward(func_input)
        t = self.trunk.forward(coord)
        return sum(bi * ti for bi, ti in zip(b, t))
    
    def train(self, func_inputs: List[List[float]], 
              coords: List[List[float]],
              targets: List[float],
              epochs: int = 100, lr: float = 0.001) -> List[Dict]:
        """训练DeepONet"""
        history = []
        eps = 1e-4
        
        for epoch in range(epochs):
            total_loss = 0.0
            # 简化: 随机梯度采样
            idx = random.randint(0, len(targets) - 1)
            pred = self.forward(func_inputs[idx], coords[idx])
            loss = (pred - targets[idx]) ** 2
            total_loss = loss
            
            # 数值梯度更新分支网络
            for layer in self.branch.layers:
                for i in range(len(layer['weights'])):
                    for j in range(len(layer['weights'][i])):
                        layer['weights'][i][j] += eps
                        loss_plus = (self.forward(func_inputs[idx], coords[idx]) - targets[idx]) ** 2
                        layer['weights'][i][j] -= 2*eps
                        loss_minus = (self.forward(func_inputs[idx], coords[idx]) - targets[idx]) ** 2
                        layer['weights'][i][j] += eps
                        grad = (loss_plus - loss_minus) / (2*eps)
                        layer['weights'][i][j] -= lr * grad
                
                for j in range(len(layer['biases'])):
                    layer['biases'][j] += eps
                    loss_plus = (self.forward(func_inputs[idx], coords[idx]) - targets[idx]) ** 2
                    layer['biases'][j] -= 2*eps
                    loss_minus = (self.forward(func_inputs[idx], coords[idx]) - targets[idx]) ** 2
                    layer['biases'][j] += eps
                    grad = (loss_plus - loss_minus) / (2*eps)
                    layer['biases'][j] -= lr * grad
            
            if epoch % 25 == 0:
                history.append({'epoch': epoch, 'loss': total_loss})
        
        self.training_log = history
        return history
    
    def predict(self, func_input: List[float], coord: List[float]) -> float:
        return self.forward(func_input, coord)


class OperatorLearner:
    """算子学习编排器"""
    
    def __init__(self, config: Dict = None):
        self.config = config or {
            'branch_input': 50,    # 函数采样点数
            'trunk_input': 1,      # 坐标维度
            'embedding': 32,
            'hidden': [64, 32]
        }
        self.model = DeepONet(
            self.config['branch_input'],
            self.config['trunk_input'],
            self.config['hidden'],
            self.config['hidden'],
            self.config['embedding']
        )
    
    def sample_function(self, func_type: str = 'sine', 
                        n_points: int = 50) -> List[float]:
        """采样函数作为输入"""
        if func_type == 'sine':
            phase = random.uniform(0, 2*math.pi)
            freq = random.uniform(0.5, 3.0)
            return [math.sin(freq * i/n_points * 2*math.pi + phase) 
                    for i in range(n_points)]
        elif func_type == 'polynomial':
            coeffs = [random.uniform(-1, 1) for _ in range(4)]
            return [sum(c*(i/n_points)**p for p,c in enumerate(coeffs)) 
                    for i in range(n_points)]
        return [random.gauss(0, 1) for _ in range(n_points)]
    
    def generate_training_data(self, n_samples: int = 200) -> Tuple:
        """生成训练数据"""
        func_inputs = []
        coords = []
        targets = []
        
        for _ in range(n_samples):
            f = self.sample_function('sine')
            x = [random.uniform(0, 1)]
            # 目标: 函数在坐标处的积分近似
            target = sum(f[i] * math.sin(x[0] * math.pi) for i in range(len(f))) / len(f)
            
            func_inputs.append(f)
            coords.append(x)
            targets.append(target)
        
        return func_inputs, coords, targets
    
    def train(self, n_samples: int = 200, epochs: int = 100) -> Dict:
        """完整训练流程"""
        func_inputs, coords, targets = self.generate_training_data(n_samples)
        history = self.model.train(func_inputs, coords, targets, epochs)
        
        return {
            'history': history,
            'final_loss': history[-1]['loss'] if history else None
        }


if __name__ == '__main__':
    print("=== Operator Learning (DeepONet) Demo ===")
    
    learner = OperatorLearner({
        'branch_input': 20,
        'trunk_input': 1,
        'embedding': 8,
        'hidden': [16, 8]
    })
    
    print("Training DeepONet...")
    result = learner.train(n_samples=100, epochs=50)
    
    print(f"Final training loss: {result['final_loss']:.6f}")
    
    # Test prediction
    test_func = learner.sample_function('sine', 20)
    test_coord = [0.5]
    pred = learner.model.predict(test_func, test_coord)
    print(f"Prediction at x=0.5: {pred:.4f}")
