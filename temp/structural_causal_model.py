#!/usr/bin/env python3
"""Structural Causal Models for GenericAgent
结构因果模型: SCM表示、do-演算、因果效应估计、反事实推理"""

import os, math, random, logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class StructuralEquation:
    """结构方程: Y = f(X, U)"""
    def __init__(self, name, parents, func, noise_dist="gaussian"):
        self.name = name
        self.parents = parents  # list of parent variable names
        self.func = func  # callable(parent_values, noise) -> value
        self.noise_dist = noise_dist

    def compute(self, parent_values, noise=None):
        if noise is None:
            noise = random.gauss(0, 1)
        return self.func(parent_values, noise)


class StructuralCausalModel:
    """SCM: {U, V, F}"""
    def __init__(self):
        self.equations = {}  # var_name -> StructuralEquation
        self.variables = {}  # var_name -> value
        self.exogenous = {}  # var_name -> noise function

    def add_equation(self, eq):
        self.equations[eq.name] = eq

    def set_exogenous(self, name, noise_func):
        self.exogenous[name] = noise_func

    def sample(self, interventions=None):
        """前向采样: 拓扑序计算"""
        if interventions is None:
            interventions = {}
        values = {}

        # 拓扑排序 (BFS from nodes with no parents)
        ordered = self._topological_sort()

        for name in ordered:
            if name in interventions:
                values[name] = interventions[name]
                continue

            eq = self.equations.get(name)
            if eq is None:
                # Exogenous variable
                values[name] = self.exogenous.get(name, lambda: random.gauss(0, 1))()
                if callable(values[name]):
                    values[name] = values[name]()
            else:
                parent_vals = [values.get(p, 0) for p in eq.parents]
                noise = random.gauss(0, 1)
                values[name] = eq.compute(parent_vals, noise)

        self.variables = values
        return values

    def do(self, var, value):
        """do-演算: 干预"""
        return self.sample(interventions={var: value})

    def counterfactual(self, observed, interventions):
        """反事实推理: 三步法( abduction -> action -> prediction)"""
        # 简化: 直接使用干预后的值
        cf = self.sample(interventions=interventions)
        return cf

    def causal_effect(self, treatment, outcome, n_samples=100):
        """估计因果效应 E[Y|do(X=1)] - E[Y|do(X=0)]"""
        y_do1 = sum(self.do(treatment, 1)[outcome] for _ in range(n_samples)) / n_samples
        y_do0 = sum(self.do(treatment, 0)[outcome] for _ in range(n_samples)) / n_samples
        return y_do1 - y_do0

    def _topological_sort(self):
        """简单拓扑排序"""
        visited = set()
        order = []

        def dfs(node):
            if node in visited:
                return
            visited.add(node)
            eq = self.equations.get(node)
            if eq:
                for p in eq.parents:
                    dfs(p)
            order.append(node)

        for name in self.equations:
            dfs(name)
        # 添加外生变量
        for name in self.exogenous:
            if name not in visited:
                order.append(name)
        return order


def build_simple_scm():
    """构建简单SCM示例: X -> Y <- Z"""
    scm = StructuralCausalModel()
    scm.add_equation(StructuralEquation("X", [], lambda p, u: u))
    scm.add_equation(StructuralEquation("Z", [], lambda p, u: u))
    scm.add_equation(StructuralEquation("Y", ["X", "Z"], lambda p, u: 0.5*p[0] + 0.3*p[1] + 0.2*u))
    return scm


if __name__ == "__main__":
    print("=== Structural Causal Model Demo ===")
    random.seed(42)
    scm = build_simple_scm()

    # 观察分布
    obs = scm.sample()
    print(f"Observed: X={obs['X']:.3f}, Z={obs['Z']:.3f}, Y={obs['Y']:.3f}")

    # 干预
    intv = scm.do("X", 2.0)
    print(f"Do(X=2.0): Y={intv['Y']:.3f}")

    # 因果效应
    effect = scm.causal_effect("X", "Y", n_samples=500)
    print(f"Average Causal Effect of X on Y: {effect:.3f}")

    # 反事实
    cf = scm.counterfactual({"X": 1.0}, {"Z": 3.0})
    print(f"Counterfactual (Z=3.0): Y={cf['Y']:.3f}")
