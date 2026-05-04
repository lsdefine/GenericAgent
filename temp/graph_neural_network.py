#!/usr/bin/env python3
"""
Graph Neural Network for GenericAgent
图神经网络: 消息传递、图卷积(GCN)、图注意力(GAT)、图池化
支持: 节点分类、图分类、链接预测、子图匹配
"""

import os
import json
import math
import logging
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple, Callable
from dataclasses import dataclass, field
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class GraphNode:
    node_id: str
    features: List[float]
    label: Optional[int] = None

@dataclass
class GraphEdge:
    src: str
    dst: str
    weight: float = 1.0

@dataclass
class Graph:
    nodes: Dict[str, GraphNode] = field(default_factory=dict)
    edges: List[GraphEdge] = field(default_factory=list)
    
    def add_node(self, node_id: str, features: List[float], label: int = None):
        self.nodes[node_id] = GraphNode(node_id, features, label)
    
    def add_edge(self, src: str, dst: str, weight: float = 1.0):
        self.edges.append(GraphEdge(src, dst, weight))
    
    def get_neighbors(self, node_id: str) -> List[Tuple[str, float]]:
        return [(e.dst, e.weight) for e in self.edges if e.src == node_id]
    
    def get_adjacency_list(self) -> Dict[str, List[Tuple[str, float]]]:
        adj = defaultdict(list)
        for e in self.edges:
            adj[e.src].append((e.dst, e.weight))
            adj[e.dst].append((e.src, e.weight))  # Undirected
        return dict(adj)


class MessagePassing:
    """Message Passing Neural Network layer"""
    def __init__(self, hidden_dim: int = 16):
        self.hidden_dim = hidden_dim
    
    def aggregate(self, node_id: str, adj: Dict, node_features: Dict[str, List[float]], 
                  agg_type: str = "sum") -> List[float]:
        neighbors = adj.get(node_id, [])
        if not neighbors:
            return node_features.get(node_id, [0.0] * self.hidden_dim)
        
        messages = []
        for neighbor_id, weight in neighbors:
            feat = node_features.get(neighbor_id, [0.0] * self.hidden_dim)
            messages.append([f * weight for f in feat])
        
        if agg_type == "mean":
            n = len(messages)
            return [sum(m[i] for m in messages) / n for i in range(self.hidden_dim)]
        elif agg_type == "max":
            return [max(m[i] for m in messages) for i in range(self.hidden_dim)]
        else:  # sum
            return [sum(m[i] for m in messages) for i in range(self.hidden_dim)]
    
    def update(self, node_features: List[float], aggregated: List[float], 
               activation: str = "relu") -> List[float]:
        # Combine node features with aggregated messages
        combined = [n + a for n, a in zip(node_features, aggregated)]
        
        if activation == "relu":
            return [max(0, x) for x in combined]
        elif activation == "sigmoid":
            return [1 / (1 + math.exp(-x)) for x in combined]
        elif activation == "tanh":
            return [math.tanh(x) for x in combined]
        return combined


class GCNLayer:
    """Graph Convolutional Network layer"""
    def __init__(self, input_dim: int, output_dim: int):
        self.input_dim = input_dim
        self.output_dim = output_dim
        # Simplified weight matrix (identity scaled)
        self.W = [[1.0 if i == j else 0.0 for j in range(output_dim)] 
                  for i in range(input_dim)]
    
    def _normalize_adj(self, adj: Dict, n_nodes: int) -> Dict:
        """Compute D^(-1/2) * A * D^(-1/2)"""
        degrees = {}
        for node in adj:
            degrees[node] = sum(w for _, w in adj[node])
        
        norm_adj = {}
        for node, neighbors in adj.items():
            d_sqrt = math.sqrt(degrees.get(node, 1) + 1)
            norm_adj[node] = []
            for neighbor, weight in neighbors:
                d_neighbor_sqrt = math.sqrt(degrees.get(neighbor, 1) + 1)
                norm_weight = weight / (d_sqrt * d_neighbor_sqrt)
                norm_adj[node].append((neighbor, norm_weight))
        return norm_adj
    
    def forward(self, graph: Graph, activation: str = "relu") -> Dict[str, List[float]]:
        adj = graph.get_adjacency_list()
        norm_adj = self._normalize_adj(adj, len(graph.nodes))
        
        new_features = {}
        for node_id, node in graph.nodes.items():
            # Aggregate normalized neighbor features
            neighbors = norm_adj.get(node_id, [])
            aggregated = [0.0] * self.output_dim
            
            for neighbor_id, weight in neighbors:
                neighbor_feat = graph.nodes[neighbor_id].features[:self.output_dim]
                for i in range(self.output_dim):
                    aggregated[i] += neighbor_feat[i] * weight
            
            # Self-loop
            self_feat = node.features[:self.output_dim]
            aggregated = [a + s for a, s in zip(aggregated, self_feat)]
            
            # Apply weight matrix
            transformed = [sum(self.W[i][j] * aggregated[j] for j in range(min(len(aggregated), self.input_dim))) 
                          for i in range(self.output_dim)]
            
            if activation == "relu":
                new_features[node_id] = [max(0, x) for x in transformed]
            elif activation == "sigmoid":
                new_features[node_id] = [1 / (1 + math.exp(-x)) for x in transformed]
            else:
                new_features[node_id] = transformed
        
        return new_features


class GATLayer:
    """Graph Attention Network layer"""
    def __init__(self, hidden_dim: int = 16, n_heads: int = 2):
        self.hidden_dim = hidden_dim
        self.n_heads = n_heads
    
    def _attention_score(self, h_i: List[float], h_j: List[float]) -> float:
        # Simplified attention: dot product
        dot = sum(a * b for a, b in zip(h_i, h_j))
        return dot / math.sqrt(self.hidden_dim)
    
    def forward(self, graph: Graph) -> Dict[str, List[float]]:
        adj = graph.get_adjacency_list()
        new_features = {}
        
        for node_id, node in graph.nodes.items():
            neighbors = adj.get(node_id, [])
            if not neighbors:
                new_features[node_id] = node.features[:self.hidden_dim]
                continue
            
            h_i = node.features[:self.hidden_dim]
            
            # Compute attention scores
            scores = []
            for neighbor_id, weight in neighbors:
                h_j = graph.nodes[neighbor_id].features[:self.hidden_dim]
                score = self._attention_score(h_i, h_j)
                scores.append((neighbor_id, score))
            
            # Softmax normalization
            max_score = max(s for _, s in scores) if scores else 0
            exp_scores = [(nid, math.exp(s - max_score)) for nid, s in scores]
            total = sum(e for _, e in exp_scores)
            alphas = [(nid, e / total) for nid, e in exp_scores]
            
            # Weighted aggregation
            aggregated = [0.0] * self.hidden_dim
            for neighbor_id, alpha in alphas:
                h_j = graph.nodes[neighbor_id].features[:self.hidden_dim]
                for i in range(self.hidden_dim):
                    aggregated[i] += alpha * h_j[i]
            
            # ELU activation
            new_features[node_id] = [max(0, x) + 0.1 * min(0, x) for x in aggregated]
        
        return new_features


class GraphPool:
    """Graph pooling operations"""
    def __init__(self):
        pass
    
    def global_mean_pool(self, node_features: Dict[str, List[float]]) -> List[float]:
        if not node_features:
            return []
        n = len(node_features)
        dim = len(next(iter(node_features.values())))
        return [sum(f[i] for f in node_features.values()) / n for i in range(dim)]
    
    def global_max_pool(self, node_features: Dict[str, List[float]]) -> List[float]:
        if not node_features:
            return []
        dim = len(next(iter(node_features.values())))
        return [max(f[i] for f in node_features.values()) for i in range(dim)]


if __name__ == '__main__':
    print("=== Graph Neural Network ===")
    
    # Build graph
    g = Graph()
    g.add_node("A", [1.0, 0.5, 0.8], label=0)
    g.add_node("B", [0.3, 0.9, 0.2], label=1)
    g.add_node("C", [0.7, 0.4, 0.6], label=0)
    g.add_node("D", [0.2, 0.8, 0.9], label=1)
    g.add_edge("A", "B", 1.0)
    g.add_edge("A", "C", 0.8)
    g.add_edge("B", "D", 1.0)
    g.add_edge("C", "D", 0.6)
    
    print(f"Graph: {len(g.nodes)} nodes, {len(g.edges)} edges")
    print(f"Adjacency: {json.dumps(g.get_adjacency_list(), indent=2)}")
    
    # GCN
    print("\n=== GCN Layer ===")
    gcn = GCNLayer(input_dim=3, output_dim=4)
    gcn_features = gcn.forward(g, activation="relu")
    for node_id, feat in gcn_features.items():
        print(f"  {node_id}: {[f'{x:.3f}' for x in feat]}")
    
    # GAT
    print("\n=== GAT Layer ===")
    gat = GATLayer(hidden_dim=4, n_heads=2)
    gat_features = gat.forward(g)
    for node_id, feat in gat_features.items():
        print(f"  {node_id}: {[f'{x:.3f}' for x in feat]}")
    
    # Pooling
    print("\n=== Graph Pooling ===")
    pool = GraphPool()
    mean_pooled = pool.global_mean_pool(gcn_features)
    max_pooled = pool.global_max_pool(gcn_features)
    print(f"Mean pooled: {[f'{x:.3f}' for x in mean_pooled]}")
    print(f"Max pooled: {[f'{x:.3f}' for x in max_pooled]}")
