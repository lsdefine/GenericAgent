#!/usr/bin/env python3
"""Interpreter Pattern - DSL expression evaluator with parsing and execution"""
from typing import Dict, Any, Union, List
from abc import ABC, abstractmethod
import re

class Context:
    def __init__(self):
        self.variables: Dict[str, float] = {}
    
    def set_var(self, name: str, value: float):
        self.variables[name] = value
    
    def get_var(self, name: str) -> float:
        return self.variables.get(name, 0)

class Expression(ABC):
    @abstractmethod
    def interpret(self, context: Context) -> float:
        pass

class NumberExpression(Expression):
    def __init__(self, value: float):
        self.value = value
    
    def interpret(self, context: Context) -> float:
        return self.value

class VariableExpression(Expression):
    def __init__(self, name: str):
        self.name = name
    
    def interpret(self, context: Context) -> float:
        return context.get_var(self.name)

class AddExpression(Expression):
    def __init__(self, left: Expression, right: Expression):
        self.left = left
        self.right = right
    
    def interpret(self, context: Context) -> float:
        return self.left.interpret(context) + self.right.interpret(context)

class SubtractExpression(Expression):
    def __init__(self, left: Expression, right: Expression):
        self.left = left
        self.right = right
    
    def interpret(self, context: Context) -> float:
        return self.left.interpret(context) - self.right.interpret(context)

class MultiplyExpression(Expression):
    def __init__(self, left: Expression, right: Expression):
        self.left = left
        self.right = right
    
    def interpret(self, context: Context) -> float:
        return self.left.interpret(context) * self.right.interpret(context)

class DivideExpression(Expression):
    def __init__(self, left: Expression, right: Expression):
        self.left = left
        self.right = right
    
    def interpret(self, context: Context) -> float:
        right_val = self.right.interpret(context)
        if right_val == 0:
            raise ZeroDivisionError("Division by zero")
        return self.left.interpret(context) / right_val

class PowerExpression(Expression):
    def __init__(self, base: Expression, exp: Expression):
        self.base = base
        self.exp = exp
    
    def interpret(self, context: Context) -> float:
        return self.base.interpret(context) ** self.exp.interpret(context)

class ExpressionParser:
    @staticmethod
    def parse(expression: str) -> Expression:
        tokens = ExpressionParser._tokenize(expression)
        pos = [0]
        
        def parse_expr():
            left = parse_term()
            while pos[0] < len(tokens) and tokens[pos[0]] in ('+', '-'):
                op = tokens[pos[0]]
                pos[0] += 1
                right = parse_term()
                if op == '+':
                    left = AddExpression(left, right)
                else:
                    left = SubtractExpression(left, right)
            return left
        
        def parse_term():
            left = parse_power()
            while pos[0] < len(tokens) and tokens[pos[0]] in ('*', '/'):
                op = tokens[pos[0]]
                pos[0] += 1
                right = parse_power()
                if op == '*':
                    left = MultiplyExpression(left, right)
                else:
                    left = DivideExpression(left, right)
            return left
        
        def parse_power():
            base = parse_primary()
            if pos[0] < len(tokens) and tokens[pos[0]] == '^':
                pos[0] += 1
                exp = parse_power()  # right-associative
                base = PowerExpression(base, exp)
            return base
        
        def parse_primary():
            token = tokens[pos[0]]
            pos[0] += 1
            if token == '(':
                expr = parse_expr()
                if pos[0] < len(tokens) and tokens[pos[0]] == ')':
                    pos[0] += 1
                return expr
            elif re.match(r'^-?\d+\.?\d*$', token):
                return NumberExpression(float(token))
            elif re.match(r'^[a-zA-Z_]\w*$', token):
                return VariableExpression(token)
            else:
                raise ValueError(f"Unexpected token: {token}")
        
        def parse_power():
            base = parse_primary()
            if pos[0] < len(tokens) and tokens[pos[0]] == '^':
                pos[0] += 1
                exp = parse_primary()
                base = PowerExpression(base, exp)
            return base
        
        result = parse_expr()
        if pos[0] < len(tokens):
            raise ValueError(f"Unexpected token: {tokens[pos[0]]}")
        return result
    
    @staticmethod
    def _tokenize(expression: str) -> List[str]:
        tokens = []
        pattern = r'\s*([+\-*/^()])\s*|\s*([a-zA-Z_]\w*|\-?\d+\.?\d*)\s*'
        for match in re.finditer(pattern, expression):
            if match.group(1):
                tokens.append(match.group(1))
            elif match.group(2):
                tokens.append(match.group(2))
        return tokens

if __name__ == "__main__":
    context = Context()
    context.set_var("x", 10)
    context.set_var("y", 3)
    context.set_var("z", 2)
    
    # Test arithmetic
    expr1 = ExpressionParser.parse("x + y * z")
    print(f"x + y * z = {expr1.interpret(context)} (expect 16)")
    
    expr2 = ExpressionParser.parse("(x + y) * z")
    print(f"(x + y) * z = {expr2.interpret(context)} (expect 26)")
    
    expr3 = ExpressionParser.parse("x ^ z + y")
    print(f"x ^ z + y = {expr3.interpret(context)} (expect 103)")
    
    expr4 = ExpressionParser.parse("x / z - y")
    print(f"x / z - y = {expr4.interpret(context)} (expect 2)")
    
    # Nested expression
    expr5 = ExpressionParser.parse("(x + y) * (z + 1)")
    print(f"(x+y)*(z+1) = {expr5.interpret(context)} (expect 39)")
    
    print("\nInterpreter pattern ready.")
