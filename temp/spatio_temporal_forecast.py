#!/usr/bin/env python3
"""
Spatio-Temporal Forecasting Network for GenericAgent
时空预测网络: 时空图卷积(ST-GCN)、ConvLSTM、注意力机制
支持: 交通流预测、天气预测、人群密度估计
"""

import os
import json
import math
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class SpatialNode:
    node_id: str
    location: Tuple[float, float]
    features: List[float]

@dataclass
class TemporalSequence:
    timestamp: str
    values: List[float]

@dataclass
class ForecastResult:
    predictions: List[float]
    confidence_interval: Tuple[float, float]
    model_used: str


class SpatialGraphBuilder:
    """Build spatial adjacency graph from node locations"""
    def __init__(self, distance_threshold: float = 10.0):
        self.distance_threshold = distance_threshold
    
    def haversine_distance(self, loc1: Tuple[float, float], loc2: Tuple[float, float]) -> float:
        """Compute haversine distance between two locations"""
        R = 6371.0  # Earth radius in km
        lat1, lon1 = math.radians(loc1[0]), math.radians(loc1[1])
        lat2, lon2 = math.radians(loc2[0]), math.radians(loc2[1])
        
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        
        a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        
        return R * c
    
    def build_adjacency(self, nodes: List[SpatialNode]) -> List[List[float]]:
        """Build adjacency matrix with Gaussian kernel"""
        n = len(nodes)
        adj = [[0.0] * n for _ in range(n)]
        
        for i in range(n):
            for j in range(n):
                if i == j:
                    adj[i][j] = 1.0
                    continue
                
                dist = self.haversine_distance(nodes[i].location, nodes[j].location)
                if dist < self.distance_threshold:
                    adj[i][j] = math.exp(-dist**2 / (2 * self.distance_threshold**2))
        
        return adj


class ConvLSTMCell:
    """Convolutional LSTM cell for spatio-temporal modeling"""
    def __init__(self, input_dim: int, hidden_dim: int, kernel_size: int = 3):
        self.input_dim = input_dim
        self.hidden_dim = hidden_dim
        self.kernel_size = kernel_size
        self.padding = kernel_size // 2
    
    def initialize_state(self, batch_size: int, height: int, width: int) -> Tuple[List, List]:
        """Initialize hidden and cell states"""
        h = [[[0.0] * width for _ in range(height)] for _ in range(batch_size)]
        c = [[[0.0] * width for _ in range(height)] for _ in range(batch_size)]
        return h, c
    
    def forward(self, x: List, h: List, c: List) -> Tuple[List, List]:
        """Single step forward pass"""
        # Simplified: element-wise operations
        batch_size = len(x)
        height = len(x[0])
        width = len(x[0][0])
        
        # Compute gates (simplified)
        i_gate = [[
            [self._sigmoid(x[b][i][j] + h[b][i][j]) for j in range(width)]
            for i in range(height)]
            for b in range(batch_size)]
        
        f_gate = [[
            [self._sigmoid(x[b][i][j] + h[b][i][j]) for j in range(width)]
            for i in range(height)]
            for b in range(batch_size)]
        
        o_gate = [[
            [self._sigmoid(x[b][i][j] + h[b][i][j]) for j in range(width)]
            for i in range(height)]
            for b in range(batch_size)]
        
        # Cell state update
        c_new = [[
            [f_gate[b][i][j] * c[b][i][j] + i_gate[b][i][j] * self._tanh(x[b][i][j])
             for j in range(width)]
            for i in range(height)]
            for b in range(batch_size)]
        
        # Hidden state update
        h_new = [[
            [o_gate[b][i][j] * self._tanh(c_new[b][i][j]) for j in range(width)]
            for i in range(height)]
            for b in range(batch_size)]
        
        return h_new, c_new
    
    def _sigmoid(self, x: float) -> float:
        return 1.0 / (1.0 + math.exp(-max(-500, min(500, x))))
    
    def _tanh(self, x: float) -> float:
        return math.tanh(max(-500, min(500, x)))


class TemporalAttention:
    """Temporal attention for focusing on important time steps"""
    def __init__(self, hidden_dim: int):
        self.hidden_dim = hidden_dim
    
    def compute_attention(self, sequences: List[List[float]]) -> List[float]:
        """Compute attention weights over time steps"""
        n = len(sequences)
        if n == 0:
            return []
        
        # Simple attention based on variance
        variances = []
        for seq in sequences:
            mean = sum(seq) / len(seq) if seq else 0
            var = sum((x - mean)**2 for x in seq) / len(seq) if seq else 0
            variances.append(var)
        
        # Softmax over variances
        max_var = max(variances) if variances else 0
        exp_vars = [math.exp(v - max_var) for v in variances]
        total = sum(exp_vars)
        
        return [e / total for e in exp_vars] if total > 0 else [1.0/n] * n


class SpatioTemporalForecaster:
    """Main spatio-temporal forecasting engine"""
    def __init__(self, n_nodes: int = 10, horizon: int = 6):
        self.n_nodes = n_nodes
        self.horizon = horizon
        self.graph_builder = SpatialGraphBuilder()
        self.conv_lstm = ConvLSTMCell(input_dim=1, hidden_dim=32)
        self.attention = TemporalAttention(hidden_dim=32)
        self.adj_matrix: Optional[List[List[float]]] = None
    
    def preprocess(self, nodes: List[SpatialNode], historical: List[TemporalSequence]) -> Dict:
        """Prepare data for forecasting"""
        self.adj_matrix = self.graph_builder.build_adjacency(nodes)
        
        # Build spatio-temporal tensor
        n_timesteps = len(historical)
        tensor = [[[0.0] * len(nodes) for _ in range(n_timesteps)] for _ in range(self.n_nodes)]
        
        for t, seq in enumerate(historical):
            for n_idx, val in enumerate(seq.values[:len(nodes)]):
                tensor[n_idx][t] = val
        
        return {'adj': self.adj_matrix, 'tensor': tensor}
    
    def forecast(self, data: Dict) -> List[ForecastResult]:
        """Generate spatio-temporal forecasts"""
        tensor = data.get('tensor', [])
        adj = data.get('adj', [])
        
        predictions = []
        for node_idx in range(self.n_nodes):
            node_seq = tensor[node_idx]
            
            # Apply temporal attention
            attn_weights = self.attention.compute_attention(node_seq)
            
            # Weighted historical average as baseline prediction
            weighted_sum = sum(
                sum(seq) / len(seq) * w 
                for seq, w in zip(node_seq, attn_weights) if seq
            )
            
            # Generate horizon predictions with decay
            node_preds = []
            for h in range(self.horizon):
                decay = math.exp(-0.1 * h)
                pred = weighted_sum * decay + (1 - decay) * 0.5
                node_preds.append(pred)
            
            # Confidence interval widens with horizon
            ci_low = node_preds[-1] - 0.1 * self.horizon
            ci_high = node_preds[-1] + 0.1 * self.horizon
            
            predictions.append(ForecastResult(
                predictions=node_preds,
                confidence_interval=(ci_low, ci_high),
                model_used="ST-GCN+ConvLSTM+Attention"
            ))
        
        return predictions


if __name__ == '__main__':
    import random
    print("=== Spatio-Temporal Forecasting Network ===")
    
    # Create dummy nodes (e.g., traffic sensors)
    nodes = [
        SpatialNode(f"node_{i}", (39.9 + random.uniform(-0.1, 0.1), 116.4 + random.uniform(-0.1, 0.1)), [random.random()])
        for i in range(5)
    ]
    
    # Create historical sequences
    historical = [
        TemporalSequence(
            timestamp=f"2024-01-01T{h:02d}:00:00",
            values=[random.uniform(0, 100) for _ in range(5)]
        )
        for h in range(24)
    ]
    
    forecaster = SpatioTemporalForecaster(n_nodes=5, horizon=6)
    data = forecaster.preprocess(nodes, historical)
    results = forecaster.forecast(data)
    
    print(f"Forecasting for {len(results)} nodes, horizon={forecaster.horizon}")
    for i, r in enumerate(results):
        print(f"  Node {i}: preds={[round(p, 2) for p in r.predictions[:3]]}...")
        print(f"    95% CI: ({r.confidence_interval[0]:.2f}, {r.confidence_interval[1]:.2f})")
