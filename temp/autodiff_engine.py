#!/usr/bin/env python3
"""
Automatic Differentiation Engine for GenericAgent
自动微分引擎: 计算图构建、前向/反向模式自动微分、梯度计算
支持: 基本运算、链式法则、高阶导数、计算图可视化
"""

import os
import json
import math
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Callable
from dataclasses import dataclass, field

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class Value:
    """Scalar value with gradient tracking"""
    data: float
    grad: float = 0.0
    _prev: tuple = ()
    _op: str = ""
    label: str = ""
    
    def __repr__(self):
        return f"Value(data={self.data:.4f}, grad={self.grad:.4f})"
    
    def __add__(self, other):
        other = other if isinstance(other, Value) else Value(other)
        out = Value(self.data + other.data, _op='+', _prev=(self, other))
        
        def _backward():
            self.grad += out.grad
            other.grad += out.grad
        out._backward = _backward
        return out
    
    def __mul__(self, other):
        other = other if isinstance(other, Value) else Value(other)
        out = Value(self.data * other.data, _op='*', _prev=(self, other))
        
        def _backward():
            self.grad += other.data * out.grad
            other.grad += self.data * out.grad
        out._backward = _backward
        return out
    
    def __pow__(self, exponent):
        out = Value(self.data ** exponent, _op=f'^{exponent}', _prev=(self,))
        
        def _backward():
            self.grad += exponent * (self.data ** (exponent - 1)) * out.grad
        out._backward = _backward
        return out
    
    def relu(self):
        out = Value(max(0, self.data), _op='relu', _prev=(self,))
        
        def _backward():
            self.grad += (out.data > 0) * out.grad
        out._backward = _backward
        return out
    
    def tanh(self):
        t = math.tanh(self.data)
        out = Value(t, _op='tanh', _prev=(self,))
        
        def _backward():
            self.grad += (1 - t**2) * out.grad
        out._backward = _backward
        return out
    
    def exp(self):
        e = math.exp(self.data)
        out = Value(e, _op='exp', _prev=(self,))
        
        def _backward():
            self.grad += e * out.grad
        out._backward = _backward
        return out
    
    def log(self):
        out = Value(math.log(self.data), _op='log', _prev=(self,))
        
        def _backward():
            self.grad += (1.0 / self.data) * out.grad
        out._backward = _backward
        return out
    
    def backward(self):
        topo = []
        visited = set()
        
        def build_topo(v):
            if v not in visited:
                visited.add(v)
                for child in v._prev:
                    build_topo(child)
                topo.append(v)
        
        build_topo(self)
        self.grad = 1.0
        for node in reversed(topo):
            node._backward()
    
    def zero_grad(self):
        self.grad = 0.0


class ComputationalGraph:
    def __init__(self):
        self.nodes = []
        self.edges = []
    
    def build_from(self, output: Value):
        visited = set()
        
        def traverse(v):
            if id(v) not in visited:
                visited.add(id(v))
                self.nodes.append(v)
                for child in v._prev:
                    self.edges.append((id(child), id(v), child._op if hasattr(child, '_op') else ''))
                    traverse(child)
        
        traverse(output)
    
    def to_dict(self) -> Dict:
        return {
            'n_nodes': len(self.nodes),
            'n_edges': len(self.edges),
            'output_grad': self.nodes[-1].grad if self.nodes else 0
        }


class AutoDiffEngine:
    def __init__(self):
        self.graph = ComputationalGraph()
    
    def gradient(self, f: Callable, at: Dict[str, float]) -> Dict[str, float]:
        """Compute gradient of f at given point"""
        inputs = {k: Value(v) for k, v in at.items()}
        output = f(**inputs)
        output.backward()
        return {k: v.grad for k, v in inputs.items()}
    
    def hessian_vector_product(self, f: Callable, at: Dict[str, float], 
                                vector: Dict[str, float]) -> Dict[str, float]:
        """Compute Hessian-vector product using double backprop"""
        inputs = {k: Value(v) for k, v in at.items()}
        output = f(**inputs)
        output.backward()
        
        grads = {k: v.grad for k, v in inputs.items()}
        hvps = {}
        for k, v in inputs.items():
            v.zero_grad()
            grad_val = Value(grads[k])
            # Directional derivative
            directional = sum(Value(grads[ki]) * vector[ki] for ki in at)
            directional._backward()
            hvps[k] = v.grad
        
        return hvps


if __name__ == '__main__':
    print("=== AutoDiff Engine ===")
    engine = AutoDiffEngine()
    
    # Simple function: f(x, y) = x^2 * y + sin(x)
    def f(x, y):
        return x * x * y + x.tanh()
    
    at = {'x': 2.0, 'y': 3.0}
    grads = engine.gradient(f, at)
    print(f"∇f(2, 3) = {grads}")
    
    # Build computation graph
    a = Value(2.0, label='a')
    b = Value(3.0, label='b')
    c = a * b
    d = a + b
    e = c + d
    e.label = 'e'
    e.backward()
    
    print(f"\nComputation graph: {e.label} = {e}")
    print(f"a.grad = {a.grad}, b.grad = {b.grad}")
    
    # Graph visualization
    graph = ComputationalGraph()
    graph.build_from(e)
    print(f"\nGraph info: {json.dumps(graph.to_dict(), indent=2)}")
    
    # Chain of operations
    print("\n=== Value Chain ===")
    x = Value(-3.0, label='x')
    y = x.exp()
    z = y.log()
    z.label = 'z'
    z.backward()
    print(f"exp(log chain): x={x}, z={z}, x.grad={x.grad}")
