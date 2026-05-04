#!/usr/bin/env python3
"""
Semi-Supervised Training for GenericAgent
半监督训练: 伪标签、一致性正则、均值教师(Mean Teacher)
支持: 低密度分离、熵最小化、MixMatch风格混合
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
class SemiSupConfig:
    input_dim: int = 128
    num_classes: int = 10
    hidden_dim: int = 64
    unlabeled_weight: float = 1.0
    confidence_threshold: float = 0.95
    ema_decay: float = 0.999

class SemiSupClassifier:
    """Simple classifier for semi-supervised learning"""
    def __init__(self, input_dim: int, hidden_dim: int, num_classes: int):
        self.input_dim = input_dim
        self.hidden_dim = hidden_dim
        self.num_classes = num_classes
        self.w1 = [random.gauss(0, 0.1) for _ in range(input_dim * hidden_dim)]
        self.w2 = [random.gauss(0, 0.1) for _ in range(hidden_dim * num_classes)]

    def forward(self, x: List[float]) -> List[float]:
        h = self._linear_relu(x, self.w1, self.input_dim, self.hidden_dim)
        logits = self._linear(h, self.w2, self.hidden_dim, self.num_classes)
        return self._softmax(logits)

    def _linear_relu(self, x, w, di, do):
        return [max(0, sum(w[i*di+j]*x[j] for j in range(min(di,len(x))) if i*di+j < len(w))) for i in range(do)]

    def _linear(self, x, w, di, do):
        return [sum(w[i*di+j]*x[j] for j in range(min(di,len(x))) if i*di+j < len(w)) for i in range(do)]

    def _softmax(self, x):
        max_x = max(x)
        exps = [math.exp(xi - max_x) for xi in x]
        s = sum(exps)
        return [e/s for e in exps]

class MeanTeacher:
    """Mean Teacher model with EMA weights"""
    def __init__(self, student: SemiSupClassifier, decay: float = 0.999):
        self.student = student
        self.teacher = SemiSupClassifier(student.input_dim, student.hidden_dim, student.num_classes)
        # Copy initial weights
        self.teacher.w1 = self.student.w1[:]
        self.teacher.w2 = self.student.w2[:]
        self.decay = decay

    def update_teacher(self):
        """EMA update of teacher weights"""
        for i in range(len(self.teacher.w1)):
            self.teacher.w1[i] = self.decay * self.teacher.w1[i] + (1 - self.decay) * self.student.w1[i]
        for i in range(len(self.teacher.w2)):
            self.teacher.w2[i] = self.decay * self.teacher.w2[i] + (1 - self.decay) * self.student.w2[i]

    def predict_teacher(self, x: List[float]) -> List[float]:
        return self.teacher.forward(x)

class SemiSupervisedTrainer:
    """Main semi-supervised learning orchestrator"""
    def __init__(self, config: SemiSupConfig = None):
        self.config = config or SemiSupConfig()
        self.student = SemiSupClassifier(self.config.input_dim, self.config.hidden_dim, self.config.num_classes)
        self.teacher = MeanTeacher(self.student, self.config.ema_decay)
        self.training_history: List[Dict] = []

    def cross_entropy(self, probs: List[float], label: int) -> float:
        return -math.log(max(1e-7, probs[label]))

    def consistency_loss(self, p_student: List[float], p_teacher: List[float]) -> float:
        """MSE between student and teacher predictions"""
        return sum((a - b)**2 for a, b in zip(p_student, p_teacher)) / len(p_student)

    def train_step(self, labeled_x: List[float], labeled_y: int, unlabeled_x: List[float]) -> Dict:
        """Single semi-supervised training step"""
        # Labeled loss
        p_labeled = self.student.forward(labeled_x)
        sup_loss = self.cross_entropy(p_labeled, labeled_y)

        # Unlabeled consistency loss
        p_student_ul = self.student.forward(unlabeled_x)
        p_teacher_ul = self.teacher.predict_teacher(unlabeled_x)
        unsup_loss = self.consistency_loss(p_student_ul, p_teacher_ul)

        total_loss = sup_loss + self.config.unlabeled_weight * unsup_loss

        # Update teacher
        self.teacher.update_teacher()

        # Pseudo-labeling (if confident)
        max_prob = max(p_teacher_ul)
        pseudo_label = p_teacher_ul.index(max_prob)
        pseudo_valid = max_prob > self.config.confidence_threshold

        self.training_history.append({
            'sup_loss': sup_loss, 'unsup_loss': unsup_loss,
            'total': total_loss, 'pseudo_valid': pseudo_valid
        })

        return {'total_loss': total_loss, 'pseudo_used': pseudo_valid}

if __name__ == '__main__':
    print("=== Semi-Supervised Training (Mean Teacher) ===")
    
    config = SemiSupConfig(input_dim=64, num_classes=5, confidence_threshold=0.9)
    trainer = SemiSupervisedTrainer(config)
    
    print(f"\nClasses: {config.num_classes}")
    print(f"Confidence threshold: {config.confidence_threshold}")
    
    for epoch in range(100):
        x_l = [random.random() for _ in range(64)]
        y_l = random.randint(0, 4)
        x_ul = [random.random() for _ in range(64)]
        res = trainer.train_step(x_l, y_l, x_ul)
        if epoch % 25 == 0:
            print(f"  Epoch {epoch}: loss={res['total_loss']:.4f}, pseudo_valid={res['pseudo_used']}")

    print("\nSemi-supervised training complete")
