#!/usr/bin/env python3
"""
Explainability Analyzer for GenericAgent
可解释性分析器: LIME、SHAP简化版、特征重要性、注意力可视化
支持: 局部解释、全局解释、特征归因、反事实解释
"""

import os
import json
import math
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Callable
from dataclasses import dataclass, field
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class FeatureImportance:
    feature_name: str
    importance: float
    direction: str  # positive, negative, neutral

@dataclass
class Explanation:
    instance_id: str
    prediction: int
    confidence: float
    feature_attributions: List[FeatureImportance]
    explanation_type: str  # lime, shap, permutation


class LIMEExplainer:
    """Local Interpretable Model-agnostic Explanations (simplified)"""
    def __init__(self, n_features: int = 5, n_samples: int = 100):
        self.n_features = n_features
        self.n_samples = n_samples
    
    def _perturb_instance(self, instance: List[float], std: float = 0.1) -> List[List[float]]:
        import random
        samples = []
        for _ in range(self.n_samples):
            perturbed = [x + random.gauss(0, std) for x in instance]
            perturbed = [max(0.0, min(1.0, p)) for p in perturbed]
            samples.append(perturbed)
        return samples
    
    def _compute_weights(self, perturbed: List[List[float]], original: List[float]) -> List[float]:
        import random
        weights = []
        for p in perturbed:
            dist = math.sqrt(sum((pi - oi)**2 for pi, oi in zip(p, original)))
            w = math.exp(-(dist ** 2) / (2 * 0.1 ** 2))
            weights.append(w)
        return weights
    
    def explain(self, instance: List[float], predict_fn: Callable, 
                feature_names: List[str] = None) -> Explanation:
        if feature_names is None:
            feature_names = [f"f{i}" for i in range(len(instance))]
        
        perturbed = self._perturb_instance(instance)
        predictions = [predict_fn(p) for p in perturbed]
        weights = self._compute_weights(perturbed, instance)
        
        # Simple weighted linear regression to find feature importance
        n = len(perturbed)
        attributions = [0.0] * len(instance)
        
        for j in range(len(instance)):
            weighted_sum = 0.0
            weight_total = 0.0
            for i in range(n):
                diff = perturbed[i][j] - instance[j]
                pred_diff = predictions[i] - predict_fn(instance)
                weighted_sum += weights[i] * diff * pred_diff
                weight_total += weights[i] * diff ** 2
            
            attributions[j] = weighted_sum / (weight_total + 1e-10)
        
        importances = []
        for name, attr in zip(feature_names, attributions):
            direction = "positive" if attr > 0.01 else "negative" if attr < -0.01 else "neutral"
            importances.append(FeatureImportance(name, attr, direction))
        
        importances.sort(key=lambda x: abs(x.importance), reverse=True)
        
        pred = predict_fn(instance)
        conf = max(pred, 1 - pred) if isinstance(pred, float) else 0.5
        
        return Explanation(
            instance_id="local",
            prediction=int(pred),
            confidence=conf,
            feature_attributions=importances,
            explanation_type="lime"
        )


class SHAPExplainer:
    """SHAP (SHapley Additive exPlanations) - simplified"""
    def __init__(self):
        self.feature_values: Dict[str, List[float]] = {}
    
    def _shapley_value(self, feature_idx: int, instance: List[float], 
                       predict_fn: Callable, n_features: int) -> float:
        # Simplified Shapley value computation
        base_pred = predict_fn([0.5] * n_features)
        full_pred = predict_fn(instance)
        
        # Marginal contribution approximation
        with_feat = predict_fn(instance)
        without = predict_fn([instance[i] if i != feature_idx else 0.5 for i in range(n_features)])
        
        return with_feat - without
    
    def explain(self, instance: List[float], predict_fn: Callable,
                feature_names: List[str] = None) -> Explanation:
        n = len(instance)
        if feature_names is None:
            feature_names = [f"f{i}" for i in range(n)]
        
        attributions = []
        for j in range(n):
            shap_val = self._shapley_value(j, instance, predict_fn, n)
            direction = "positive" if shap_val > 0.01 else "negative" if shap_val < -0.01 else "neutral"
            attributions.append(FeatureImportance(feature_names[j], shap_val, direction))
        
        attributions.sort(key=lambda x: abs(x.importance), reverse=True)
        
        pred = predict_fn(instance)
        conf = max(pred, 1 - pred) if isinstance(pred, float) else 0.5
        
        return Explanation(
            instance_id="shap",
            prediction=int(pred),
            confidence=conf,
            feature_attributions=attributions,
            explanation_type="shap"
        )


class CounterfactualExplainer:
    """Generates counterfactual explanations"""
    def __init__(self):
        pass
    
    def generate(self, instance: List[float], current_pred: int, target_pred: int,
                 predict_fn: Callable, feature_names: List[str] = None,
                 max_steps: int = 50, lr: float = 0.05) -> Dict:
        if feature_names is None:
            feature_names = [f"f{i}" for i in range(len(instance))]
        
        counterfactual = list(instance)
        changes = []
        
        for step in range(max_steps):
            pred = predict_fn(counterfactual)
            if pred == target_pred:
                break
            
            # Gradient-based search for minimal change
            for j in range(len(counterfactual)):
                # Try increasing
                test_up = list(counterfactual)
                test_up[j] = min(1.0, test_up[j] + lr)
                pred_up = predict_fn(test_up)
                
                # Try decreasing
                test_down = list(counterfactual)
                test_down[j] = max(0.0, test_down[j] - lr)
                pred_down = predict_fn(test_down)
                
                if pred_up == target_pred:
                    counterfactual[j] = test_up[j]
                    changes.append(feature_names[j])
                    break
                elif pred_down == target_pred:
                    counterfactual[j] = test_down[j]
                    changes.append(feature_names[j])
                    break
        
        distance = sum(abs(c - i) for c, i in zip(counterfactual, instance))
        
        return {
            'original': instance,
            'counterfactual': counterfactual,
            'original_pred': current_pred,
            'counterfactual_pred': predict_fn(counterfactual),
            'features_changed': changes,
            'total_change': distance,
            'success': predict_fn(counterfactual) == target_pred
        }


class GlobalExplainer:
    """Global feature importance across dataset"""
    def __init__(self):
        self.importance_accum: Dict[str, float] = defaultdict(float)
        self.n_explanations = 0
    
    def add_explanation(self, explanation: Explanation):
        for fi in explanation.feature_attributions:
            self.importance_accum[fi.feature_name] += abs(fi.importance)
        self.n_explanations += 1
    
    def get_global_importance(self, top_k: int = 10) -> List[FeatureImportance]:
        if self.n_explanations == 0:
            return []
        
        sorted_feats = sorted(self.importance_accum.items(), key=lambda x: x[1], reverse=True)
        return [
            FeatureImportance(name, imp / self.n_explanations, 
                            "positive" if imp > 0 else "neutral")
            for name, imp in sorted_feats[:top_k]
        ]


if __name__ == '__main__':
    def model(x: List[float]) -> float:
        return 1.0 / (1.0 + math.exp(-(0.8*x[0] - 0.3*x[1] + 0.5*x[2] - 0.2)))
    
    instance = [0.7, 0.3, 0.5]
    features = ["age", "income", "education"]
    
    print("=== LIME Explanation ===")
    lime = LIMEExplainer(n_features=3, n_samples=200)
    lime_exp = lime.explain(instance, model, features)
    print(f"Prediction: {lime_exp.prediction}")
    for fi in lime_exp.feature_attributions:
        print(f"  {fi.feature_name}: {fi.importance:.4f} ({fi.direction})")
    
    print("\n=== SHAP Explanation ===")
    shap = SHAPExplainer()
    shap_exp = shap.explain(instance, model, features)
    for fi in shap_exp.feature_attributions:
        print(f"  {fi.feature_name}: {fi.importance:.4f} ({fi.direction})")
    
    print("\n=== Counterfactual Explanation ===")
    cf_exp = CounterfactualExplainer()
    cf = cf_exp.generate(instance, int(model(instance)), 1 - int(model(instance)), model, features)
    print(f"Original: {instance} -> Pred: {cf['original_pred']}")
    print(f"Counterfactual: {cf['counterfactual']} -> Pred: {cf['counterfactual_pred']}")
    print(f"Features changed: {cf['features_changed']}")
    print(f"Success: {cf['success']}")
    
    print("\n=== Global Importance ===")
    global_exp = GlobalExplainer()
    global_exp.add_explanation(lime_exp)
    global_exp.add_explanation(shap_exp)
    for fi in global_exp.get_global_importance():
        print(f"  {fi.feature_name}: {fi.importance:.4f}")
