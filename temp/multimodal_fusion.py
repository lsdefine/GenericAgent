#!/usr/bin/env python3
"""
Multimodal Fusion Engine for GenericAgent
多模态融合引擎: 早期融合、晚期融合、交叉注意力、模态对齐
支持: 文本-图像-音频融合、模态缺失处理、特征投影、跨模态检索
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
class ModalityFeature:
    modality: str  # text, image, audio, video
    features: List[float]
    confidence: float = 1.0
    embedding_dim: int = 0
    
    def __post_init__(self):
        if self.embedding_dim == 0:
            self.embedding_dim = len(self.features)


@dataclass
class FusedRepresentation:
    fused_features: List[float]
    modality_weights: Dict[str, float]
    fusion_type: str
    confidence: float


class EarlyFusion:
    """Concatenate features from different modalities before processing"""
    def __init__(self, projection_dim: int = 64):
        self.projection_dim = projection_dim
    
    def fuse(self, modalities: List[ModalityFeature]) -> FusedRepresentation:
        # Project all features to same dimension
        projected = []
        weights = {}
        
        for m in modalities:
            feat = m.features[:self.projection_dim]
            # Pad if needed
            while len(feat) < self.projection_dim:
                feat.append(0.0)
            projected.extend(feat[:self.projection_dim // len(modalities)])
            weights[m.modality] = m.confidence
        
        # Normalize
        norm = math.sqrt(sum(x**2 for x in projected) + 1e-10)
        projected = [x / norm for x in projected]
        
        avg_conf = sum(m.confidence for m in modalities) / len(modalities)
        
        return FusedRepresentation(
            fused_features=projected,
            modality_weights=weights,
            fusion_type="early",
            confidence=avg_conf
        )


class LateFusion:
    """Process each modality separately, then combine predictions"""
    def __init__(self):
        pass
    
    def fuse(self, predictions: Dict[str, List[float]], 
             confidences: Dict[str, float]) -> Dict:
        """Weighted average of predictions"""
        modalities = list(predictions.keys())
        n_classes = len(predictions[modalities[0]])
        
        fused = [0.0] * n_classes
        total_weight = 0.0
        
        for mod in modalities:
            w = confidences.get(mod, 1.0)
            for i in range(n_classes):
                fused[i] += w * predictions[mod][i]
            total_weight += w
        
        if total_weight > 0:
            fused = [f / total_weight for f in fused]
        
        # Softmax
        max_f = max(fused)
        exp_f = [math.exp(f - max_f) for f in fused]
        total = sum(exp_f)
        probs = [e / total for e in exp_f]
        
        return {
            'fused_predictions': probs,
            'predicted_class': probs.index(max(probs)),
            'confidence': max(probs),
            'modality_contributions': {m: confidences.get(m, 1.0) for m in modalities}
        }


class CrossAttention:
    """Cross-modal attention mechanism"""
    def __init__(self, dim: int = 32, n_heads: int = 2):
        self.dim = dim
        self.n_heads = n_heads
        self.head_dim = dim // n_heads
    
    def _attention(self, Q: List[float], K: List[float], V: List[float]) -> List[float]:
        """Simplified single-head attention"""
        # Dot product attention
        score = sum(q * k for q, k in zip(Q, K)) / math.sqrt(len(Q))
        weight = math.exp(score)
        return [weight * v for v in V]
    
    def fuse(self, modality_a: ModalityFeature, modality_b: ModalityFeature) -> FusedRepresentation:
        """Cross-attention between two modalities"""
        dim = min(len(modality_a.features), len(modality_b.features), self.dim)
        feat_a = modality_a.features[:dim]
        feat_b = modality_b.features[:dim]
        
        # Q from A, K, V from B
        attended = self._attention(feat_a, feat_b, feat_b)
        
        # Residual connection
        fused = [(a + b) / 2 for a, b in zip(feat_a, attended)]
        
        # Normalize
        norm = math.sqrt(sum(x**2 for x in fused) + 1e-10)
        fused = [x / norm for x in fused]
        
        weights = {
            modality_a.modality: modality_a.confidence,
            modality_b.modality: modality_b.confidence
        }
        
        return FusedRepresentation(
            fused_features=fused,
            modality_weights=weights,
            fusion_type="cross_attention",
            confidence=(modality_a.confidence + modality_b.confidence) / 2
        )


class ModalityAligner:
    """Align features from different modalities to shared space"""
    def __init__(self, shared_dim: int = 128):
        self.shared_dim = shared_dim
    
    def project(self, modality: ModalityFeature) -> List[float]:
        """Project modality features to shared embedding space"""
        feat = modality.features
        n = len(feat)
        
        # Simplified projection (zero-padding + normalization)
        projected = list(feat[:self.shared_dim])
        while len(projected) < self.shared_dim:
            projected.append(0.0)
        
        # L2 normalization
        norm = math.sqrt(sum(x**2 for x in projected) + 1e-10)
        return [x / norm for x in projected]
    
    def compute_similarity(self, feat_a: List[float], feat_b: List[float]) -> float:
        """Cosine similarity"""
        dot = sum(a * b for a, b in zip(feat_a, feat_b))
        norm_a = math.sqrt(sum(x**2 for x in feat_a) + 1e-10)
        norm_b = math.sqrt(sum(x**2 for x in feat_b) + 1e-10)
        return dot / (norm_a * norm_b)


class CrossModalRetrieval:
    """Retrieve matching items across modalities"""
    def __init__(self, shared_dim: int = 128):
        self.aligner = ModalityAligner(shared_dim)
        self.index: Dict[str, List[Dict]] = defaultdict(list)
    
    def add_item(self, item_id: str, modality: str, features: List[float]):
        mf = ModalityFeature(modality, features)
        projected = self.aligner.project(mf)
        self.index[modality].append({
            'id': item_id,
            'features': projected
        })
    
    def search(self, query_modality: str, query_features: List[float], 
               target_modality: str, top_k: int = 5) -> List[Dict]:
        query_mf = ModalityFeature(query_modality, query_features)
        query_proj = self.aligner.project(query_mf)
        
        results = []
        for item in self.index.get(target_modality, []):
            sim = self.aligner.compute_similarity(query_proj, item['features'])
            results.append({'id': item['id'], 'similarity': sim})
        
        results.sort(key=lambda x: x['similarity'], reverse=True)
        return results[:top_k]


if __name__ == '__main__':
    print("=== Multimodal Fusion Engine ===")
    
    # Create sample modalities
    import random
    random.seed(42)
    
    text_feat = ModalityFeature("text", [random.uniform(0, 1) for _ in range(64)], confidence=0.9)
    image_feat = ModalityFeature("image", [random.uniform(0, 1) for _ in range(128)], confidence=0.85)
    audio_feat = ModalityFeature("audio", [random.uniform(0, 1) for _ in range(48)], confidence=0.7)
    
    # Early Fusion
    print("\n--- Early Fusion ---")
    early = EarlyFusion(projection_dim=64)
    early_result = early.fuse([text_feat, image_feat, audio_feat])
    print(f"Fusion type: {early_result.fusion_type}")
    print(f"Features dim: {len(early_result.fused_features)}")
    print(f"Modality weights: {early_result.modality_weights}")
    
    # Late Fusion
    print("\n--- Late Fusion ---")
    late = LateFusion()
    predictions = {
        'text': [0.7, 0.2, 0.1],
        'image': [0.3, 0.6, 0.1],
        'audio': [0.4, 0.3, 0.3]
    }
    confidences = {'text': 0.9, 'image': 0.85, 'audio': 0.7}
    late_result = late.fuse(predictions, confidences)
    print(f"Fused predictions: {[f'{p:.3f}' for p in late_result['fused_predictions']]}")
    print(f"Predicted class: {late_result['predicted_class']}")
    print(f"Confidence: {late_result['confidence']:.3f}")
    
    # Cross Attention
    print("\n--- Cross Attention ---")
    ca = CrossAttention(dim=32)
    ca_result = ca.fuse(text_feat, image_feat)
    print(f"Fusion type: {ca_result.fusion_type}")
    print(f"Features dim: {len(ca_result.fused_features)}")
    
    # Cross-Modal Retrieval
    print("\n--- Cross-Modal Retrieval ---")
    cmr = CrossModalRetrieval(shared_dim=64)
    for i in range(10):
        cmr.add_item(f"img_{i}", "image", [random.uniform(0, 1) for _ in range(64)])
    
    query = [random.uniform(0, 1) for _ in range(64)]
    results = cmr.search("text", query, "image", top_k=3)
    print(f"Top-3 matches:")
    for r in results:
        print(f"  {r['id']}: similarity={r['similarity']:.4f}")
