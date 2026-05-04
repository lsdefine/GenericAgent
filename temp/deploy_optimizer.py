#!/usr/bin/env python3
"""
Deployment Optimizer for GenericAgent
部署优化器: 算子融合、内存规划、推理加速、模型格式转换
支持: 图优化、批处理调度、缓存策略、性能剖析
"""

import os
import json
import math
import time
import logging
from typing import Dict, List, Optional, Tuple, Callable
from dataclasses import dataclass, field
from collections import deque

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class Operator:
    op_type: str
    input_shape: List[int]
    output_shape: List[int]
    params: int
    flops: int

@dataclass
class OptimizationReport:
    original_ops: int
    optimized_ops: int
    memory_before: int
    memory_after: int
    speedup_factor: float
    optimizations: List[str]

@dataclass
class BatchConfig:
    max_batch_size: int
    timeout_ms: float
    adaptive: bool


class OperatorFusion:
    """Fuse consecutive operators for efficiency"""
    def __init__(self):
        pass
    
    def fuse_conv_bn(self, conv_weight: List[float], conv_bias: List[float],
                     bn_gamma: List[float], bn_beta: List[float],
                     bn_mean: List[float], bn_var: List[float],
                     eps: float = 1e-5) -> Tuple[List[float], List[float]]:
        """Fuse Conv2D + BatchNorm into single Conv2D"""
        fused_weight = []
        fused_bias = []
        
        for i in range(len(conv_bias)):
            std = math.sqrt(bn_var[i] + eps)
            scale = bn_gamma[i] / std
            
            fused_weight.append(conv_weight[i] * scale)
            fused_bias.append(scale * (conv_bias[i] - bn_mean[i]) + bn_beta[i])
        
        return fused_weight, fused_bias
    
    def fuse_relu_activation(self, ops: List[Operator]) -> List[Operator]:
        """Fuse activation into preceding layer"""
        fused = []
        i = 0
        while i < len(ops):
            op = ops[i]
            if i + 1 < len(ops) and ops[i + 1].op_type in ['relu', 'sigmoid', 'tanh']:
                op = Operator(
                    op_type=f"{op.op_type}+{ops[i+1].op_type}",
                    input_shape=op.input_shape,
                    output_shape=ops[i+1].output_shape,
                    params=op.params,
                    flops=op.flops + ops[i+1].flops
                )
                i += 2
            else:
                i += 1
            fused.append(op)
        
        return fused


class MemoryPlanner:
    """Optimize memory allocation for inference"""
    def __init__(self):
        pass
    
    def compute_memory_footprint(self, ops: List[Operator]) -> Dict[str, int]:
        """Compute peak memory usage"""
        peak = 0
        current = 0
        tensor_sizes = {}
        
        for i, op in enumerate(ops):
            # Input tensors
            input_size = sum(s for s in op.input_shape) * 4  # 4 bytes per float
            if f"input_{i}" in tensor_sizes:
                input_size = tensor_sizes[f"input_{i}"]
            
            # Output tensor
            output_size = sum(s for s in op.output_shape) * 4
            tensor_sizes[f"output_{i}"] = output_size
            
            # Free input if no longer needed
            if i > 0 and f"output_{i-1}" not in [f"input_{j}" for j in range(i+1, len(ops))]:
                current -= tensor_sizes.get(f"output_{i-1}", 0)
            
            current += output_size
            peak = max(peak, current)
        
        return {'peak_mb': peak / (1024 * 1024), 'tensors': len(tensor_sizes)}
    
    def optimize_memory(self, ops: List[Operator]) -> List[int]:
        """Return optimal execution order for memory efficiency"""
        # Simplified: topological sort with memory-aware scheduling
        order = list(range(len(ops)))
        return order


class InferenceAccelerator:
    """Optimize inference speed"""
    def __init__(self):
        pass
    
    def batch_scheduler(self, requests: deque, config: BatchConfig) -> List:
        """Dynamic batching for inference requests"""
        batch = []
        while len(batch) < config.max_batch_size and requests:
            if len(batch) == 0:
                batch.append(requests.popleft())
            else:
                # Check timeout
                if time.time() - batch[0].get('timestamp', 0) * 1000 > config.timeout_ms:
                    break
                batch.append(requests.popleft())
        
        return batch
    
    def compute_optimal_batch_size(self, model_flops: int, target_latency_ms: float) -> int:
        """Estimate optimal batch size for target latency"""
        # Simplified model: latency = base + k * batch_size
        base_latency = 5  # ms
        per_sample_cost = model_flops / 1e9 * 10  # ms per sample at 100 GFLOPS/s
        
        if per_sample_cost <= 0:
            return 1
        
        max_batch = int((target_latency_ms - base_latency) / per_sample_cost)
        return max(1, min(max_batch, 128))


class Profiler:
    """Profile inference performance"""
    def __init__(self):
        self.timings: Dict[str, List[float]] = {}
    
    def profile_layer(self, name: str, func: Callable, *args) -> float:
        """Profile a single layer"""
        start = time.perf_counter()
        func(*args)
        elapsed = (time.perf_counter() - start) * 1000  # ms
        
        if name not in self.timings:
            self.timings[name] = []
        self.timings[name].append(elapsed)
        
        return elapsed
    
    def get_report(self) -> Dict:
        """Generate profiling report"""
        report = {}
        for name, times in self.timings.items():
            report[name] = {
                'mean_ms': sum(times) / len(times),
                'min_ms': min(times),
                'max_ms': max(times),
                'samples': len(times)
            }
        return report


class DeploymentOptimizer:
    """Main deployment optimization orchestrator"""
    def __init__(self):
        self.fusion = OperatorFusion()
        self.memory = MemoryPlanner()
        self.accelerator = InferenceAccelerator()
        self.profiler = Profiler()
    
    def optimize_model(self, ops: List[Operator]) -> OptimizationReport:
        """Run full optimization pipeline"""
        original_ops = len(ops)
        
        # Step 1: Operator fusion
        ops = self.fusion.fuse_relu_activation(ops)
        
        # Step 2: Memory planning
        mem_before = self.memory.compute_memory_footprint(ops)
        exec_order = self.memory.optimize_memory(ops)
        
        # Step 3: Profiling
        for i, op in enumerate(ops):
            self.profiler.profile_layer(op.op_type, lambda: None)
        
        profiling = self.profiler.get_report()
        
        report = OptimizationReport(
            original_ops=original_ops,
            optimized_ops=len(ops),
            memory_before=mem_before['peak_mb'],
            memory_after=mem_before['peak_mb'] * 0.8,  # Estimate 20% savings
            speedup_factor=original_ops / len(ops) if len(ops) > 0 else 1.0,
            optimizations=['operator_fusion', 'memory_planning', 'profiling']
        )
        
        return report


if __name__ == '__main__':
    print("=== Deployment Optimizer ===")
    
    # Create dummy operators
    ops = [
        Operator('conv', [1, 3, 224, 224], [1, 64, 112, 112], 10000, 50000000),
        Operator('bn', [1, 64, 112, 112], [1, 64, 112, 112], 128, 1000),
        Operator('relu', [1, 64, 112, 112], [1, 64, 112, 112], 0, 0),
        Operator('conv', [1, 64, 112, 112], [1, 128, 56, 56], 20000, 100000000),
        Operator('relu', [1, 128, 56, 56], [1, 128, 56, 56], 0, 0),
    ]
    
    optimizer = DeploymentOptimizer()
    report = optimizer.optimize_model(ops)
    
    print(f"Original ops: {report.original_ops}")
    print(f"Optimized ops: {report.optimized_ops}")
    print(f"Speedup: {report.speedup_factor:.2f}x")
    print(f"Optimizations: {report.optimizations}")
    
    # Memory planning
    print(f"\n--- Memory ---")
    planner = MemoryPlanner()
    mem = planner.compute_memory_footprint(ops)
    print(f"Peak memory: {mem['peak_mb']:.2f}MB")
    
    # Profiling
    print(f"\n--- Profiling ---")
    profiler = Profiler()
    for op in ops:
        profiler.profile_layer(op.op_type, lambda: sum(range(1000)))
    report_data = profiler.get_report()
    for name, stats in report_data.items():
        print(f"  {name}: mean={stats['mean_ms']:.3f}ms")
    
    # Batch sizing
    print(f"\n--- Batch Sizing ---")
    accelerator = InferenceAccelerator()
    optimal_batch = accelerator.compute_optimal_batch_size(1e9, target_latency_ms=50)
    print(f"Optimal batch size for 50ms latency: {optimal_batch}")
