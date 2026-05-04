#!/usr/bin/env python3
"""
Physics-Informed Neural Network (PINN) for GenericAgent
物理信息神经网络: 将物理方程约束融入神经网络训练
支持: PDE残差损失、边界条件、初值条件、多物理场耦合
"""

import os
import math
import random
import logging
from typing import Dict, List, Optional, Tuple, Callable
from dataclasses import dataclass, field

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class PINNLayer:
    """物理信息神经网络层 - 带物理约束的全连接层"""
    
    def __init__(self, input_dim: int, output_dim: int, 
                 activation: str = 'tanh', seed: int = 42):
        self.input_dim = input_dim
        self.output_dim = output_dim
        self.activation = activation
        
        # Xavier初始化
        random.seed(seed)
        limit = math.sqrt(6.0 / (input_dim + output_dim))
        self.weights = [[random.uniform(-limit, limit) for _ in range(output_dim)] 
                        for _ in range(input_dim)]
        self.biases = [0.0] * output_dim
        self.gradient_weights = [[0.0] * output_dim for _ in range(input_dim)]
        self.gradient_biases = [0.0] * output_dim
    
    def forward(self, x: List[float]) -> List[float]:
        """前向传播"""
        out = []
        for j in range(self.output_dim):
            val = self.biases[j]
            for i in range(self.input_dim):
                val += x[i] * self.weights[i][j]
            
            # 激活函数
            if self.activation == 'tanh':
                val = math.tanh(val)
            elif self.activation == 'sigmoid':
                val = 1.0 / (1.0 + math.exp(-max(-500, min(500, val))))
            elif self.activation == 'relu':
                val = max(0.0, val)
            elif self.activation == 'linear':
                pass
            
            out.append(val)
        return out
    
    def activation_derivative(self, x: float) -> float:
        """激活函数导数"""
        if self.activation == 'tanh':
            t = math.tanh(x)
            return 1.0 - t * t
        elif self.activation == 'sigmoid':
            s = 1.0 / (1.0 + math.exp(-max(-500, min(500, x))))
            return s * (1.0 - s)
        elif self.activation == 'relu':
            return 1.0 if x > 0 else 0.0
        return 1.0
    
    def backward(self, x: List[float], d_out: List[float]) -> List[float]:
        """反向传播"""
        d_input = [0.0] * self.input_dim
        
        for j in range(self.output_dim):
            # 预计算前向值用于激活导数
            pre_activation = self.biases[j]
            for i in range(self.input_dim):
                pre_activation += x[i] * self.weights[i][j]
            
            act_deriv = self.activation_derivative(pre_activation)
            delta = d_out[j] * act_deriv
            
            for i in range(self.input_dim):
                self.gradient_weights[i][j] = x[i] * delta
                d_input[i] += self.weights[i][j] * delta
            self.gradient_biases[j] = delta
        
        return d_input
    
    def update(self, lr: float):
        """更新权重"""
        for i in range(self.input_dim):
            for j in range(self.output_dim):
                self.weights[i][j] -= lr * self.gradient_weights[i][j]
        for j in range(self.output_dim):
            self.biases[j] -= lr * self.gradient_biases[j]


class PhysicsConstraint:
    """物理约束基类"""
    
    def __init__(self, name: str):
        self.name = name
    
    def residual(self, x: List[float], u: float, 
                 u_derivatives: Dict[str, float]) -> float:
        """计算PDE残差"""
        raise NotImplementedError
    
    def boundary_condition(self, x: List[float]) -> Optional[float]:
        """边界条件，返回期望值或None"""
        return None


class PoissonConstraint(PhysicsConstraint):
    """泊松方程约束: ∇²u = f"""
    
    def __init__(self, source_func: Callable = None):
        super().__init__("Poisson")
        self.source_func = source_func or (lambda x: 1.0)
    
    def residual(self, x, u, u_derivatives):
        # ∇²u - f(x) = 0
        laplacian = sum(u_derivatives.get(f'd2u_dx{i}dx{i}', 0.0) 
                        for i in range(len(x)))
        return laplacian - self.source_func(x)


class BurgersConstraint(PhysicsConstraint):
    """Burgers方程约束: ∂u/∂t + u·∂u/∂x = ν·∂²u/∂x²"""
    
    def __init__(self, viscosity: float = 0.01):
        super().__init__("Burgers")
        self.viscosity = viscosity
    
    def residual(self, x, u, u_derivatives):
        # x = [t, x]
        u_t = u_derivatives.get('du_dt', 0.0)
        u_x = u_derivatives.get('du_dx', 0.0)
        u_xx = u_derivatives.get('d2u_dx2', 0.0)
        return u_t + u * u_x - self.viscosity * u_xx


class HeatEquationConstraint(PhysicsConstraint):
    """热方程约束: ∂u/∂t = α·∇²u"""
    
    def __init__(self, alpha: float = 0.1):
        super().__init__("HeatEquation")
        self.alpha = alpha
    
    def residual(self, x, u, u_derivatives):
        u_t = u_derivatives.get('du_dt', 0.0)
        laplacian = sum(u_derivatives.get(f'd2u_dx{i}dx{i}', 0.0) 
                        for i in range(1, len(x)))  # skip time
        return u_t - self.alpha * laplacian


class PhysicsInformedNN:
    """物理信息神经网络编排器"""
    
    def __init__(self, layers_config: List[int], 
                 physics_constraint: PhysicsConstraint,
                 lr: float = 0.001):
        self.layers_config = layers_config
        self.constraint = physics_constraint
        self.lr = lr
        
        # 构建网络
        self.layers = []
        for i in range(len(layers_config) - 1):
            act = 'tanh' if i < len(layers_config) - 2 else 'linear'
            self.layers.append(PINNLayer(layers_config[i], layers_config[i+1], 
                                          activation=act, seed=42+i))
        
        self.training_log = []
    
    def forward(self, x: List[float]) -> List[float]:
        """网络前向传播"""
        out = x
        for layer in self.layers:
            out = layer.forward(out)
        return out
    
    def compute_autograd_approx(self, x: List[float], 
                                 epsilon: float = 1e-5) -> Tuple[float, Dict[str, float]]:
        """数值微分近似自动微分"""
        u = self.forward(x)[0]  # scalar output
        derivatives = {}
        
        # 一阶导数
        for i in range(len(x)):
            x_plus = x.copy()
            x_plus[i] += epsilon
            u_plus = self.forward(x_plus)[0]
            derivatives[f'du_dx{i}'] = (u_plus - u) / epsilon
        
        # 二阶导数
        for i in range(len(x)):
            x_plus = x.copy()
            x_plus[i] += epsilon
            x_minus = x.copy()
            x_minus[i] -= epsilon
            
            u_plus = self.forward(x_plus)[0]
            u_minus = self.forward(x_minus)[0]
            derivatives[f'd2u_dx{i}dx{i}'] = (u_plus - 2*u + u_minus) / (epsilon**2)
        
        return u, derivatives
    
    def compute_pinn_loss(self, collocation_points: List[List[float]],
                          boundary_points: List[List[float]],
                          boundary_values: List[float]) -> Dict:
        """计算PINN复合损失"""
        pde_residuals = []
        for x in collocation_points:
            u, derivatives = self.compute_autograd_approx(x)
            residual = self.constraint.residual(x, u, derivatives)
            pde_residuals.append(residual ** 2)
        
        # 边界条件损失
        bc_losses = []
        for x, u_target in zip(boundary_points, boundary_values):
            u_pred = self.forward(x)[0]
            bc_losses.append((u_pred - u_target) ** 2)
        
        # 组合损失
        pde_loss = sum(pde_residuals) / max(len(pde_residuals), 1)
        bc_loss = sum(bc_losses) / max(len(bc_losses), 1)
        total_loss = pde_loss + 10.0 * bc_loss  # BC权重
        
        return {
            'total_loss': total_loss,
            'pde_loss': pde_loss,
            'bc_loss': bc_loss
        }
    
    def train(self, collocation_points: List[List[float]],
              boundary_points: List[List[float]],
              boundary_values: List[float],
              epochs: int = 100) -> List[Dict]:
        """训练PINN"""
        history = []
        epsilon = 1e-5
        
        for epoch in range(epochs):
            # 前向计算损失
            losses = self.compute_pinn_loss(
                collocation_points, boundary_points, boundary_values
            )
            
            # 数值梯度下降
            for layer in self.layers:
                for i in range(layer.input_dim):
                    for j in range(layer.output_dim):
                        # 数值梯度
                        layer.weights[i][j] += epsilon
                        loss_plus = self.compute_pinn_loss(
                            collocation_points, boundary_points, boundary_values
                        )['total_loss']
                        layer.weights[i][j] -= 2 * epsilon
                        loss_minus = self.compute_pinn_loss(
                            collocation_points, boundary_points, boundary_values
                        )['total_loss']
                        layer.weights[i][j] += epsilon
                        
                        grad = (loss_plus - loss_minus) / (2 * epsilon)
                        layer.weights[i][j] -= self.lr * grad
                
                for j in range(layer.output_dim):
                    layer.biases[j] += epsilon
                    loss_plus = self.compute_pinn_loss(
                        collocation_points, boundary_points, boundary_values
                    )['total_loss']
                    layer.biases[j] -= 2 * epsilon
                    loss_minus = self.compute_pinn_loss(
                        collocation_points, boundary_points, boundary_values
                    )['total_loss']
                    layer.biases[j] += epsilon
                    
                    grad = (loss_plus - loss_minus) / (2 * epsilon)
                    layer.biases[j] -= self.lr * grad
            
            if epoch % 10 == 0:
                history.append({'epoch': epoch, **losses})
        
        self.training_log = history
        return history
    
    def predict(self, x: List[float]) -> float:
        """预测单点"""
        return self.forward(x)[0]
    
    def get_training_summary(self) -> Dict:
        """训练摘要"""
        if not self.training_log:
            return {}
        return {
            'epochs': len(self.training_log),
            'final_loss': self.training_log[-1].get('total_loss', 0),
            'final_pde_loss': self.training_log[-1].get('pde_loss', 0),
            'final_bc_loss': self.training_log[-1].get('bc_loss', 0)
        }


# Demo usage
if __name__ == '__main__':
    print("=== Physics-Informed Neural Network Demo ===")
    
    # 1D Poisson equation: u''(x) = -π²sin(πx), u(0)=u(1)=0
    # True solution: u(x) = sin(πx)
    
    def source(x):
        return -(math.pi ** 2) * math.sin(math.pi * x[0])
    
    constraint = PoissonConstraint(source)
    pinn = PhysicsInformedNN([1, 20, 20, 1], constraint, lr=0.01)
    
    # Collocation points (internal)
    collocation = [[i/10] for i in range(1, 10)]
    
    # Boundary points
    boundary_points = [[0.0], [1.0]]
    boundary_values = [0.0, 0.0]  # u(0) = u(1) = 0
    
    print(f"Training PINN for Poisson equation...")
    print(f"True solution: u(x) = sin(πx)")
    
    # Train (few epochs for demo)
    history = pinn.train(collocation, boundary_points, boundary_values, epochs=50)
    
    # Test predictions
    print("\nPrediction vs True:")
    for x_val in [0.0, 0.25, 0.5, 0.75, 1.0]:
        pred = pinn.predict([x_val])
        true_val = math.sin(math.pi * x_val)
        error = abs(pred - true_val)
        print(f"  x={x_val:.2f}: PINN={pred:.4f}, True={true_val:.4f}, Error={error:.4f}")
    
    summary = pinn.get_training_summary()
    print(f"\nTraining Summary: {summary}")
