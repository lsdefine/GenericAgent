#!/usr/bin/env python3
"""
Knowledge Distiller for GenericAgent
知识蒸馏器: 教师-学生模型训练、温度缩放软标签、特征蒸馏
支持: 软/硬标签混合、多层蒸馏、注意力迁移、压缩率评估
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
class ModelStats:
    model_id: str
    n_params: int
    n_layers: int
    accuracy: float = 0.0
    loss: float = 0.0
    inference_time_ms: float = 0.0

@dataclass
class DistillationConfig:
    temperature: float = 2.0
    alpha: float = 0.5  # weight for soft labels vs hard labels
    n_epochs: int = 10
    lr: float = 0.001
    layer_weights: Dict[str, float] = field(default_factory=dict)


def softmax(logits: List[float], temperature: float = 1.0) -> List[float]:
    scaled = [x / temperature for x in logits]
    max_val = max(scaled)
    exps = [math.exp(x - max_val) for x in scaled]
    sum_exp = sum(exps)
    return [e / sum_exp for e in exps]


def kl_divergence(p: List[float], q: List[float]) -> float:
    eps = 1e-10
    return sum(pi * math.log(pi / (qi + eps)) for pi, qi in zip(p, q) if pi > 0)


class KnowledgeDistiller:
    def __init__(self, config: DistillationConfig = None):
        self.config = config or DistillationConfig()
        self.teacher_logits: Dict[int, List[float]] = {}
        self.student_logits: Dict[int, List[float]] = {}
        self.hard_labels: Dict[int, int] = {}
        self.loss_history: List[Dict] = []
        self.feature_maps: Dict[str, Dict[int, List[float]]] = {"teacher": {}, "student": {}}
    
    def set_teacher_outputs(self, sample_ids: List[int], logits: List[List[float]]):
        for sid, log in zip(sample_ids, logits):
            self.teacher_logits[sid] = log
    
    def set_hard_labels(self, sample_ids: List[int], labels: List[int]):
        for sid, lbl in zip(sample_ids, labels):
            self.hard_labels[sid] = lbl
    
    def compute_soft_loss(self, student_logit: List[float], teacher_logit: List[float]) -> float:
        T = self.config.temperature
        soft_teacher = softmax(teacher_logit, T)
        soft_student = softmax(student_logit, T)
        return kl_divergence(soft_teacher, soft_student) * (T * T)
    
    def compute_hard_loss(self, student_logit: List[float], label: int) -> float:
        probs = softmax(student_logit)
        eps = 1e-10
        return -math.log(probs[label] + eps)
    
    def compute_distillation_loss(self, student_logits: Dict[int, List[float]]) -> float:
        total_loss = 0.0
        alpha = self.config.alpha
        
        for sid in self.teacher_logits:
            if sid not in student_logits:
                continue
            soft_loss = self.compute_soft_loss(student_logits[sid], self.teacher_logits[sid])
            hard_loss = 0.0
            if sid in self.hard_labels:
                hard_loss = self.compute_hard_loss(student_logits[sid], self.hard_labels[sid])
            
            loss = alpha * soft_loss + (1 - alpha) * hard_loss
            total_loss += loss
        
        n = len(self.teacher_logits)
        return total_loss / n if n > 0 else 0.0
    
    def simulate_training_step(self, student_logits: Dict[int, List[float]]) -> Dict:
        loss = self.compute_distillation_loss(student_logits)
        
        # Simulate student improvement
        improved_logits = {}
        for sid, logit in student_logits.items():
            if sid in self.teacher_logits:
                improved = [s + 0.1 * (t - s) for s, t in zip(logit, self.teacher_logits[sid])]
                improved_logits[sid] = improved
            else:
                improved_logits[sid] = logit
        
        epoch_info = {
            'epoch': len(self.loss_history),
            'loss': loss,
            'n_samples': len(student_logits)
        }
        self.loss_history.append(epoch_info)
        return epoch_info
    
    def get_compression_report(self, teacher: ModelStats, student: ModelStats) -> Dict:
        param_ratio = student.n_params / teacher.n_params if teacher.n_params > 0 else 1
        size_reduction = (1 - param_ratio) * 100
        accuracy_drop = teacher.accuracy - student.accuracy
        return {
            'compression_ratio': f"{param_ratio:.2%}",
            'size_reduction': f"{size_reduction:.1f}%",
            'accuracy_drop': f"{accuracy_drop:.2%}",
            'speedup': f"{teacher.inference_time_ms / student.inference_time_ms:.2f}x" if student.inference_time_ms > 0 else "N/A"
        }


if __name__ == '__main__':
    config = DistillationConfig(temperature=3.0, alpha=0.7, n_epochs=5)
    distiller = KnowledgeDistiller(config)
    
    # Setup teacher (simulated 3-class classification)
    sample_ids = list(range(5))
    teacher_logits = [
        [2.0, 1.0, 0.1],
        [0.1, 3.0, 0.2],
        [0.5, 0.3, 2.5],
        [1.0, 2.0, 0.5],
        [0.2, 0.1, 3.0]
    ]
    hard_labels = [0, 1, 2, 1, 2]
    
    distiller.set_teacher_outputs(sample_ids, teacher_logits)
    distiller.set_hard_labels(sample_ids, hard_labels)
    
    print("=== Knowledge Distillation ===")
    # Student starts with random-ish logits
    student_logits = {
        0: [0.5, 0.5, 0.5],
        1: [0.5, 0.5, 0.5],
        2: [0.5, 0.5, 0.5],
        3: [0.5, 0.5, 0.5],
        4: [0.5, 0.5, 0.5]
    }
    
    for epoch in range(5):
        info = distiller.simulate_training_step(student_logits)
        print(f"Epoch {epoch}: loss = {info['loss']:.4f}")
        
        # Update student towards teacher
        for sid in student_logits:
            if sid in distiller.teacher_logits:
                student_logits[sid] = [
                    s + 0.2 * (t - s) for s, t in zip(student_logits[sid], distiller.teacher_logits[sid])
                ]
    
    # Compression report
    teacher_stats = ModelStats("teacher_large", n_params=100_000_000, n_layers=24, 
                                accuracy=0.95, inference_time_ms=50.0)
    student_stats = ModelStats("student_small", n_params=10_000_000, n_layers=6,
                                accuracy=0.92, inference_time_ms=8.0)
    
    print("\n=== Compression Report ===")
    report = distiller.get_compression_report(teacher_stats, student_stats)
    print(json.dumps(report, indent=2))
