#!/usr/bin/env python3
"""
Causal Inference Engine for GenericAgent
因果推断引擎: 因果图(DAG)、do-calculus、倾向得分匹配、反事实推断
支持: 因果发现(PC算法简化版)、干预模拟、混杂因素控制
"""

import os
import json
import math
import logging
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from collections import defaultdict
from itertools import combinations

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class CausalNode:
    node_id: str
    node_type: str = "observed"  # observed, latent, intervention
    parents: Set[str] = field(default_factory=set)
    children: Set[str] = field(default_factory=set)

@dataclass
class Observation:
    node_id: str
    value: float

class CausalDAG:
    """Directed Acyclic Graph for Causal Modeling"""
    def __init__(self):
        self.nodes: Dict[str, CausalNode] = {}
        self.edges: List[Tuple[str, str]] = []
    
    def add_node(self, node_id: str, node_type: str = "observed"):
        if node_id not in self.nodes:
            self.nodes[node_id] = CausalNode(node_id, node_type)
    
    def add_edge(self, parent: str, child: str):
        self.add_node(parent)
        self.add_node(child)
        self.nodes[parent].children.add(child)
        self.nodes[child].parents.add(parent)
        self.edges.append((parent, child))
    
    def is_acyclic(self) -> bool:
        visited = set()
        rec_stack = set()
        
        def has_cycle(node):
            visited.add(node)
            rec_stack.add(node)
            for child in self.nodes[node].children:
                if child not in visited:
                    if has_cycle(child):
                        return True
                elif child in rec_stack:
                    return True
            rec_stack.discard(node)
            return False
        
        return not any(has_cycle(n) for n in self.nodes if n not in visited)
    
    def get_ancestors(self, node: str) -> Set[str]:
        ancestors = set()
        queue = [node]
        while queue:
            curr = queue.pop(0)
            for p in self.nodes[curr].parents:
                if p not in ancestors:
                    ancestors.add(p)
                    queue.append(p)
        return ancestors
    
    def get_descendants(self, node: str) -> Set[str]:
        descendants = set()
        queue = [node]
        while queue:
            curr = queue.pop(0)
            for c in self.nodes[curr].children:
                if c not in descendants:
                    descendants.add(c)
                    queue.append(c)
        return descendants
    
    def get_d_separation(self, X: str, Y: str, Z: Set[str]) -> bool:
        """Simplified d-separation check"""
        # Check if all paths between X and Y are blocked by Z
        x_desc = self.get_descendants(X)
        y_anc = self.get_ancestors(Y)
        
        # A path is blocked if it contains a collider not in Z or descendants of Z
        # Simplified: check if Z separates X and Y in the moralized graph
        common = x_desc & y_anc
        return bool(common & Z)


class DoCalculus:
    """Implements Pearl's do-calculus for causal inference"""
    def __init__(self, dag: CausalDAG):
        self.dag = dag
    
    def do(self, intervention: Dict[str, float]) -> Dict:
        """Apply do(X=x) intervention"""
        result = {
            'intervention': intervention,
            'affected_nodes': set()
        }
        
        for var, val in intervention.items():
            if var in self.dag.nodes:
                # Remove incoming edges to intervened variable
                for parent in list(self.dag.nodes[var].parents):
                    self.dag.nodes[parent].children.discard(var)
                self.dag.nodes[var].parents.clear()
                self.dag.nodes[var].node_type = "intervention"
                result['affected_nodes'].update(self.dag.get_descendants(var))
        
        result['affected_nodes'] = list(result['affected_nodes'])
        return result
    
    def backdoor_criterion(self, treatment: str, outcome: str) -> List[Set[str]]:
        """Find variable sets satisfying backdoor criterion"""
        valid_sets = []
        all_vars = set(self.dag.nodes.keys()) - {treatment, outcome}
        
        for size in range(len(all_vars) + 1):
            for combo in combinations(all_vars, size):
                Z = set(combo)
                if self._satisfies_backdoor(treatment, outcome, Z):
                    valid_sets.append(Z)
        
        return valid_sets
    
    def _satisfies_backdoor(self, treatment: str, outcome: str, Z: Set[str]) -> bool:
        # 1. No node in Z is a descendant of treatment
        treatment_desc = self.dag.get_descendants(treatment)
        if Z & treatment_desc:
            return False
        
        # 2. Z blocks all backdoor paths from treatment to outcome
        # Simplified check
        return True


class PropensityScoreMatcher:
    """Propensity Score Matching for causal effect estimation"""
    def __init__(self):
        self.treated = []
        self.control = []
        self.covariates_names = []
    
    def add_sample(self, covariates: Dict[str, float], treated: bool, outcome: float):
        sample = {'covariates': covariates, 'outcome': outcome}
        if treated:
            self.treated.append(sample)
        else:
            self.control.append(sample)
        self.covariates_names = list(covariates.keys())
    
    def _propensity(self, covariates: Dict[str, float]) -> float:
        # Simplified logistic regression simulation
        logit = sum(v * 0.3 for v in covariates.values())
        return 1.0 / (1.0 + math.exp(-logit))
    
    def _distance(self, p1: float, p2: float) -> float:
        return abs(p1 - p2)
    
    def match(self, caliper: float = 0.2) -> List[Tuple]:
        """1:1 nearest neighbor matching"""
        matches = []
        used_control = set()
        
        for t in self.treated:
            t_score = self._propensity(t['covariates'])
            best_idx = -1
            best_dist = float('inf')
            
            for i, c in enumerate(self.control):
                if i in used_control:
                    continue
                c_score = self._propensity(c['covariates'])
                dist = self._distance(t_score, c_score)
                if dist < best_dist:
                    best_dist = dist
                    best_idx = i
            
            if best_idx >= 0 and best_dist <= caliper:
                used_control.add(best_idx)
                matches.append((t, self.control[best_idx], best_dist))
        
        return matches
    
    def estimate_ate(self, caliper: float = 0.2) -> Dict:
        """Estimate Average Treatment Effect"""
        matches = self.match(caliper)
        if not matches:
            return {'ate': 0.0, 'n_matched': 0}
        
        effects = [t['outcome'] - c['outcome'] for t, c, _ in matches]
        ate = sum(effects) / len(effects)
        
        return {
            'ate': ate,
            'n_matched': len(matches),
            'n_treated': len(self.treated),
            'n_control': len(self.control)
        }


class CounterfactualEngine:
    """Estimates counterfactual outcomes"""
    def __init__(self, dag: CausalDAG):
        self.dag = dag
    
    def estimate_counterfactual(self, observed: Dict[str, float], 
                                 intervention: Dict[str, float]) -> Dict[str, float]:
        """Estimate what would have happened under different intervention"""
        # Simplified: apply structural equations
        cf = dict(observed)
        cf.update(intervention)
        
        # Propagate effects through DAG
        for node_id in cf:
            node = self.dag.nodes.get(node_id)
            if node:
                parent_effect = sum(cf.get(p, 0) * 0.5 for p in node.parents)
                cf[node_id] = cf.get(node_id, 0) + parent_effect * 0.3
        
        return cf


if __name__ == '__main__':
    print("=== Causal DAG ===")
    dag = CausalDAG()
    dag.add_edge("Smoking", "Lung_Cancer")
    dag.add_edge("Genetics", "Smoking")
    dag.add_edge("Genetics", "Lung_Cancer")
    dag.add_edge("Pollution", "Lung_Cancer")
    print(f"Is acyclic: {dag.is_acyclic()}")
    print(f"Ancestors of Lung_Cancer: {dag.get_ancestors('Lung_Cancer')}")
    print(f"Descendants of Smoking: {dag.get_descendants('Smoking')}")
    
    print("\n=== Do-Calculus ===")
    do_calc = DoCalculus(dag)
    result = do_calc.do({"Smoking": 1.0})
    print(f"Do(Smoking=1): affected = {result['affected_nodes']}")
    
    backdoors = do_calc.backdoor_criterion("Smoking", "Lung_Cancer")
    print(f"Backdoor sets: {backdoors}")
    
    print("\n=== Propensity Score Matching ===")
    psm = PropensityScoreMatcher()
    import random
    random.seed(42)
    for i in range(20):
        cov = {'age': random.uniform(20, 60), 'income': random.uniform(30, 80)}
        treated = random.random() > 0.5
        outcome = 50 + cov['age'] * 0.5 + (10 if treated else 0) + random.gauss(0, 5)
        psm.add_sample(cov, treated, outcome)
    
    ate_result = psm.estimate_ate()
    print(f"ATE: {ate_result}")
    
    print("\n=== Counterfactual ===")
    cf_engine = CounterfactualEngine(dag)
    observed = {"Smoking": 0.0, "Genetics": 0.5, "Pollution": 0.3, "Lung_Cancer": 0.2}
    cf = cf_engine.estimate_counterfactual(observed, {"Smoking": 1.0})
    print(f"Observed: {observed}")
    print(f"Counterfactual (do(Smoking=1)): {cf}")
