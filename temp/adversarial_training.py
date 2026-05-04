#!/usr/bin/env python3
"""
Adversarial Training Framework for GenericAgent
对抗训练框架: FGSM攻击、PGD攻击、对抗样本生成、鲁棒性评估
支持: 多攻击方法、对抗训练循环、鲁棒性度量、防御机制
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
class ModelPrediction:
    logits: List[float]
    predicted_class: int
    confidence: float

@dataclass
class AttackResult:
    original_input: List[float]
    adversarial_input: List[float]
    original_pred: int
    adversarial_pred: int
    perturbation_norm: float
    success: bool


def clip(value: float, min_val: float, max_val: float) -> float:
    return max(min_val, min(max_val, value))


def clamp_vector(vec: List[float], min_val: float, max_val: float) -> List[float]:
    return [clip(v, min_val, max_val) for v in vec]


def vector_norm(vec: List[float], p: int = 2) -> float:
    if p == float('inf'):
        return max(abs(v) for v in vec)
    return sum(abs(v)**p for v in vec) ** (1/p)


class FGSM:
    """Fast Gradient Sign Method"""
    def __init__(self, epsilon: float = 0.1):
        self.epsilon = epsilon
    
    def generate(self, input_vec: List[float], gradient: List[float], 
                 target: int = None) -> List[float]:
        sign_grad = [1 if g > 0 else -1 if g < 0 else 0 for g in gradient]
        perturbation = [self.epsilon * s for s in sign_grad]
        adversarial = [x + p for x, p in zip(input_vec, perturbation)]
        return clamp_vector(adversarial, 0.0, 1.0)


class PGD:
    """Projected Gradient Descent"""
    def __init__(self, epsilon: float = 0.1, n_steps: int = 10, step_size: float = 0.01):
        self.epsilon = epsilon
        self.n_steps = n_steps
        self.step_size = step_size
    
    def generate(self, input_vec: List[float], grad_fn: Callable, 
                 predict_fn: Callable, target: int = None) -> List[float]:
        adversarial = list(input_vec)
        original_norm = vector_norm([x for x in input_vec], p=2)
        
        for step in range(self.n_steps):
            grad = grad_fn(adversarial)
            
            if target is not None:
                grad = [-g for g in grad]
            
            adversarial = [a + self.step_size * (1 if g > 0 else -1 if g < 0 else 0) 
                         for a, g in zip(adversarial, grad)]
            
            # Project back to epsilon ball
            perturbation = [a - o for a, o in zip(adversarial, input_vec)]
            pert_norm = vector_norm(perturbation, p=2)
            if pert_norm > self.epsilon:
                scale = self.epsilon / pert_norm
                perturbation = [p * scale for p in perturbation]
            adversarial = [o + p for o, p in zip(input_vec, perturbation)]
            adversarial = clamp_vector(adversarial, 0.0, 1.0)
        
        return adversarial


class CWAttack:
    """Carlini-Wagner L2 Attack (simplified)"""
    def __init__(self, confidence: float = 0.0, n_steps: int = 100, lr: float = 0.01):
        self.confidence = confidence
        self.n_steps = n_steps
        self.lr = lr
    
    def generate(self, input_vec: List[float], grad_fn: Callable, 
                 predict_fn: Callable, target: int = None) -> List[float]:
        delta = [0.0] * len(input_vec)
        
        for step in range(self.n_steps):
            adversarial = [clip(x + d, 0.0, 1.0) for x, d in zip(input_vec, delta)]
            grad = grad_fn(adversarial)
            
            # Update delta with gradient
            delta = [d - self.lr * g for d, g in zip(delta, grad)]
            
            # L2 penalty on perturbation
            pert_norm = vector_norm(delta, p=2)
            if pert_norm > 1.0:
                delta = [d / pert_norm for d in delta]
        
        adversarial = [clip(x + d, 0.0, 1.0) for x, d in zip(input_vec, delta)]
        return adversarial


class AdversarialTrainer:
    def __init__(self, epsilon: float = 0.1, attack_type: str = "fgsm"):
        self.epsilon = epsilon
        self.attack_type = attack_type
        self.robustness_history = []
    
    def generate_adversarial(self, input_vec: List[float], grad_fn: Callable, 
                             predict_fn: Callable, target: int = None) -> List[float]:
        if self.attack_type == "fgsm":
            grad = grad_fn(input_vec)
            return FGSM(self.epsilon).generate(input_vec, grad)
        elif self.attack_type == "pgd":
            return PGD(self.epsilon).generate(input_vec, grad_fn, predict_fn, target)
        elif self.attack_type == "cw":
            return CWAttack().generate(input_vec, grad_fn, predict_fn, target)
        return input_vec
    
    def evaluate_robustness(self, inputs: List[List[float]], labels: List[int],
                            grad_fn: Callable, predict_fn: Callable) -> Dict:
        n_success = 0
        results = []
        
        for inp, label in zip(inputs, labels):
            pred = predict_fn(inp)
            adv = self.generate_adversarial(inp, grad_fn, predict_fn)
            adv_pred = predict_fn(adv)
            pert_norm = vector_norm([a - i for a, i in zip(adv, inp)])
            
            success = adv_pred != pred
            if success:
                n_success += 1
            
            results.append(AttackResult(inp, adv, pred, adv_pred, pert_norm, success))
        
        attack_rate = n_success / max(len(inputs), 1)
        avg_pert = sum(r.perturbation_norm for r in results) / max(len(results), 1)
        
        report = {
            'attack_type': self.attack_type,
            'epsilon': self.epsilon,
            'n_samples': len(inputs),
            'successful_attacks': n_success,
            'attack_success_rate': attack_rate,
            'avg_perturbation_norm': avg_pert,
            'robustness_score': 1 - attack_rate
        }
        self.robustness_history.append(report)
        return report
    
    def adversarial_training_step(self, inputs: List[List[float]], labels: List[int],
                                   grad_fn: Callable, predict_fn: Callable) -> List[List[float]]:
        augmented = []
        for inp, label in zip(inputs, labels):
            adv = self.generate_adversarial(inp, grad_fn, predict_fn)
            augmented.append((inp + adv) / 2)  # Mix original and adversarial
        return augmented


if __name__ == '__main__':
    print("=== Adversarial Training ===")
    
    # Simulated model
    def simple_predict(x: List[float]) -> int:
        score = sum(w * xi for w, xi in zip([1.0, -0.5, 0.8], x))
        return 1 if score > 0 else 0
    
    def simple_grad(x: List[float]) -> List[float]:
        return [1.0, -0.5, 0.8]
    
    # Test FGSM
    fgsm = FGSM(epsilon=0.3)
    original = [0.5, 0.5, 0.5]
    grad = simple_grad(original)
    adv_fgsm = fgsm.generate(original, grad)
    print(f"FGSM: {original} -> {adv_fgsm}")
    print(f"  Pred: {simple_predict(original)} -> {simple_predict(adv_fgsm)}")
    
    # Test PGD
    pgd = PGD(epsilon=0.2, n_steps=5, step_size=0.05)
    adv_pgd = pgd.generate(original, simple_grad, simple_predict)
    print(f"\nPGD: {original} -> {adv_pgd}")
    print(f"  Perturbation norm: {vector_norm([a-o for a,o in zip(adv_pgd, original)]):.4f}")
    
    # Robustness evaluation
    trainer = AdversarialTrainer(epsilon=0.3, attack_type="fgsm")
    test_inputs = [[0.6, 0.4, 0.5], [0.3, 0.7, 0.2], [0.8, 0.1, 0.9]]
    test_labels = [1, 0, 1]
    
    report = trainer.evaluate_robustness(test_inputs, test_labels, simple_grad, simple_predict)
    print(f"\nRobustness Report: {json.dumps(report, indent=2)}")
    
    # Adversarial training augmentation
    augmented = trainer.adversarial_training_step(test_inputs, test_labels, simple_grad, simple_predict)
    print(f"\nAugmented samples: {len(augmented)}")
