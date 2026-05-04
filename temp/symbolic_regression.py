#!/usr/bin/env python3
"""
Symbolic Regression for GenericAgent
符号回归: 通过遗传编程搜索数学表达式，拟合数据
支持: 表达式树、适应度评估、交叉/变异、Pareto前沿
"""

import os
import math
import random
import logging
from typing import Dict, List, Optional, Tuple, Callable
from dataclasses import dataclass, field

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# 基础函数集
FUNCTIONS = {
    'add': {'arity': 2, 'func': lambda a, b: a + b, 'str': '+'},
    'sub': {'arity': 2, 'func': lambda a, b: a - b, 'str': '-'},
    'mul': {'arity': 2, 'func': lambda a, b: a * b, 'str': '*'},
    'div': {'arity': 2, 'func': lambda a, b: a / b if abs(b) > 1e-10 else 1.0, 'str': '/'},
    'sin': {'arity': 1, 'func': lambda a: math.sin(a), 'str': 'sin'},
    'cos': {'arity': 1, 'func': lambda a: math.cos(a), 'str': 'cos'},
    'exp': {'arity': 1, 'func': lambda a: math.exp(min(a, 10)), 'str': 'exp'},
    'log': {'arity': 1, 'func': lambda a: math.log(max(a, 1e-10)), 'str': 'log'},
    'neg': {'arity': 1, 'func': lambda a: -a, 'str': 'neg'},
    'sq': {'arity': 1, 'func': lambda a: a * a, 'str': '^2'},
}


class ExpressionTree:
    """表达式树节点"""
    
    def __init__(self, name: str, children: List['ExpressionTree'] = None,
                 value: float = None, is_var: bool = False):
        self.name = name
        self.children = children or []
        self.value = value
        self.is_var = is_var
    
    @classmethod
    def constant(cls, val: float):
        return cls('const', value=val)
    
    @classmethod
    def variable(cls, idx: int):
        return cls(f'x{idx}', is_var=True)
    
    @classmethod
    def function(cls, name: str, children: List['ExpressionTree']):
        return cls(name, children=children)
    
    def evaluate(self, x: List[float]) -> float:
        """求值"""
        if self.is_var:
            idx = int(self.name[1:])
            return x[idx] if idx < len(x) else 0.0
        if self.value is not None:
            return self.value
        if self.name in FUNCTIONS:
            func_info = FUNCTIONS[self.name]
            args = [c.evaluate(x) for c in self.children]
            return func_info['func'](*args)
        return 0.0
    
    def size(self) -> int:
        """树大小（复杂度）"""
        if self.value is not None or self.is_var:
            return 1
        return 1 + sum(c.size() for c in self.children)
    
    def to_string(self) -> str:
        """表达式字符串"""
        if self.is_var:
            return self.name
        if self.value is not None:
            return f'{self.value:.2f}'
        func_info = FUNCTIONS.get(self.name, {})
        if func_info.get('arity', 0) == 2:
            left = self.children[0].to_string()
            right = self.children[1].to_string()
            return f'({left} {func_info["str"]} {right})'
        else:
            inner = self.children[0].to_string()
            return f'{func_info.get("str", self.name)}({inner})'
    
    def depth(self) -> int:
        """树深度"""
        if not self.children:
            return 1
        return 1 + max(c.depth() for c in self.children)
    
    def random_subtree(self, rng: random.Random = None) -> 'ExpressionTree':
        """获取随机子树"""
        rng = rng or random
        if not self.children or rng.random() < 0.3:
            return self
        child = rng.choice(self.children)
        return child.random_subtree(rng)
    
    def copy(self) -> 'ExpressionTree':
        """深拷贝"""
        return ExpressionTree(
            self.name,
            [c.copy() for c in self.children],
            self.value,
            self.is_var
        )


class SymbolicRegressor:
    """符号回归遗传编程引擎"""
    
    def __init__(self, max_depth: int = 5, pop_size: int = 100,
                 n_vars: int = 1, generations: int = 50):
        self.max_depth = max_depth
        self.pop_size = pop_size
        self.n_vars = n_vars
        self.generations = generations
        self.population = []
        self.history = []
    
    def _random_tree(self, depth: int, rng: random.Random = None) -> ExpressionTree:
        """随机生成表达式树"""
        rng = rng or random
        if depth <= 1:
            if rng.random() < 0.5:
                return ExpressionTree.constant(rng.uniform(-5, 5))
            else:
                return ExpressionTree.variable(rng.randint(0, self.n_vars - 1))
        
        # 选择函数
        func_names = list(FUNCTIONS.keys())
        name = rng.choice(func_names)
        arity = FUNCTIONS[name]['arity']
        children = [self._random_tree(depth - 1, rng) for _ in range(arity)]
        return ExpressionTree.function(name, children)
    
    def init_population(self):
        """初始化种群（ramped half-and-half）"""
        self.population = []
        for _ in range(self.pop_size):
            depth = random.randint(2, self.max_depth)
            self.population.append(self._random_tree(depth))
    
    def fitness(self, tree: ExpressionTree, 
                X: List[List[float]], y: List[float]) -> float:
        """适应度：MSE + 复杂度惩罚"""
        mse = 0.0
        for xi, yi in zip(X, y):
            try:
                pred = tree.evaluate(xi)
                if math.isinf(pred) or math.isnan(pred):
                    pred = 1e10
            except:
                pred = 1e10
            mse += (pred - yi) ** 2
        mse /= len(X)
        
        # 复杂度惩罚 (parsimony pressure)
        complexity = tree.size()
        return mse + 0.01 * complexity
    
    def tournament_select(self, X, y, k: int = 5) -> ExpressionTree:
        """锦标赛选择"""
        best = None
        best_fit = float('inf')
        for _ in range(k):
            tree = random.choice(self.population)
            fit = self.fitness(tree, X, y)
            if fit < best_fit:
                best = tree
                best_fit = fit
        return best
    
    def crossover(self, p1: ExpressionTree, p2: ExpressionTree) -> ExpressionTree:
        """交叉"""
        t1 = p1.random_subtree()
        t2 = p2.random_subtree()
        
        child = p1.copy()
        # 替换随机子树位置
        def replace(node, target, replacement):
            if node is target:
                return replacement.copy()
            for i, c in enumerate(node.children):
                if c is target:
                    node.children[i] = replacement.copy()
                    return node
                replace(c, target, replacement)
            return node
        
        # 简化: 直接构建新树
        new_tree = ExpressionTree.function('add', [t1.copy(), t2.copy()])
        return new_tree if new_tree.depth() <= self.max_depth else p1.copy()
    
    def mutate(self, tree: ExpressionTree) -> ExpressionTree:
        """变异"""
        new_tree = tree.copy()
        subtree = new_tree.random_subtree()
        
        if random.random() < 0.5:
            # 子树替换
            new_subtree = self._random_tree(min(3, self.max_depth - subtree.depth()))
            if subtree.is_var or subtree.value is not None:
                new_tree = new_subtree
            else:
                pass  # 简化变异
        else:
            # 常数变异
            if subtree.value is not None:
                subtree.value += random.gauss(0, 0.5)
        
        return new_tree if new_tree.depth() <= self.max_depth else tree
    
    def train(self, X: List[List[float]], y: List[float]) -> Dict:
        """训练符号回归"""
        self.init_population()
        best_ever = None
        best_ever_fit = float('inf')
        
        for gen in range(self.generations):
            new_pop = []
            
            # 精英保留
            fits = [(self.fitness(t, X, y), t) for t in self.population]
            fits.sort(key=lambda x: x[0])
            new_pop.extend([t for _, t in fits[:5]])
            
            # 生成新种群
            while len(new_pop) < self.pop_size:
                p1 = self.tournament_select(X, y)
                p2 = self.tournament_select(X, y)
                
                if random.random() < 0.7:
                    child = self.crossover(p1, p2)
                else:
                    child = p1.copy()
                
                child = self.mutate(child)
                new_pop.append(child)
            
            self.population = new_pop
            
            # 记录最优
            current_best = min(self.population, key=lambda t: self.fitness(t, X, y))
            current_fit = self.fitness(current_best, X, y)
            if current_fit < best_ever_fit:
                best_ever = current_best.copy()
                best_ever_fit = current_fit
            
            if gen % 10 == 0:
                avg_fit = sum(self.fitness(t, X, y) for t in self.population) / len(self.population)
                self.history.append({
                    'generation': gen,
                    'best_fit': best_ever_fit,
                    'avg_fit': avg_fit,
                    'best_expr': best_ever.to_string()
                })
        
        return {
            'best_expression': best_ever,
            'best_fitness': best_ever_fit,
            'history': self.history
        }
    
    def simplify(self, tree: ExpressionTree) -> ExpressionTree:
        """简化表达式（常量折叠）"""
        if tree.value is not None or tree.is_var:
            return tree
        
        children = [self.simplify(c) for c in tree.children]
        all_const = all(c.value is not None for c in children)
        if all_const and tree.name in FUNCTIONS:
            try:
                func_info = FUNCTIONS[tree.name]
                args = [c.value for c in children]
                val = func_info['func'](*args)
                return ExpressionTree.constant(val)
            except:
                pass
        return ExpressionTree.function(tree.name, children)


if __name__ == '__main__':
    print("=== Symbolic Regression Demo ===")
    
    # 目标: 拟合 sin(x) + x^2
    n_samples = 50
    X = [[i / n_samples * 2 * math.pi] for i in range(n_samples)]
    y = [math.sin(x[0]) + x[0]**2 for x in X]
    
    print("Target: sin(x) + x^2")
    print("Training symbolic regression...")
    
    regressor = SymbolicRegressor(
        max_depth=6,
        pop_size=80,
        n_vars=1,
        generations=30
    )
    
    result = regressor.train(X, y)
    
    best = result['best_expression']
    simplified = regressor.simplify(best)
    
    print(f"\nBest expression: {simplified.to_string()}")
    print(f"Best fitness: {result['best_fitness']:.4f}")
    print(f"\nEvolution history:")
    for h in result['history']:
        print(f"  Gen {h['generation']:3d}: fitness={h['best_fit']:.4f} | {h['best_expr']}")
