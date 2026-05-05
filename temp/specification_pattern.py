#!/usr/bin/env python3
"""Specification Pattern - Composable predicates for domain object filtering"""
from typing import Callable, Any, List
from abc import ABC, abstractmethod

class Specification(ABC):
    @abstractmethod
    def is_satisfied_by(self, candidate: Any) -> bool:
        pass
    
    def and_spec(self, other: "Specification") -> "Specification":
        return AndSpecification(self, other)
    
    def or_spec(self, other: "Specification") -> "Specification":
        return OrSpecification(self, other)
    
    def not_spec(self) -> "Specification":
        return NotSpecification(self)

class AndSpecification(Specification):
    def __init__(self, left: Specification, right: Specification):
        self.left = left
        self.right = right
    def is_satisfied_by(self, candidate: Any) -> bool:
        return self.left.is_satisfied_by(candidate) and self.right.is_satisfied_by(candidate)

class OrSpecification(Specification):
    def __init__(self, left: Specification, right: Specification):
        self.left = left
        self.right = right
    def is_satisfied_by(self, candidate: Any) -> bool:
        return self.left.is_satisfied_by(candidate) or self.right.is_satisfied_by(candidate)

class NotSpecification(Specification):
    def __init__(self, spec: Specification):
        self.spec = spec
    def is_satisfied_by(self, candidate: Any) -> bool:
        return not self.spec.is_satisfied_by(candidate)

class LambdaSpecification(Specification):
    def __init__(self, predicate: Callable[[Any], bool]):
        self.predicate = predicate
    def is_satisfied_by(self, candidate: Any) -> bool:
        return self.predicate(candidate)

class EqualsSpecification(Specification):
    def __init__(self, attribute: str, value: Any):
        self.attribute = attribute
        self.value = value
    def is_satisfied_by(self, candidate: Any) -> bool:
        return getattr(candidate, self.attribute, None) == self.value

class RangeSpecification(Specification):
    def __init__(self, attribute: str, min_val: Any = None, max_val: Any = None, inclusive: bool = True):
        self.attribute = attribute
        self.min_val = min_val
        self.max_val = max_val
        self.inclusive = inclusive
    def is_satisfied_by(self, candidate: Any) -> bool:
        val = getattr(candidate, self.attribute, None)
        if val is None:
            return False
        if self.min_val is not None:
            if self.inclusive and val < self.min_val:
                return False
            if not self.inclusive and val <= self.min_val:
                return False
        if self.max_val is not None:
            if self.inclusive and val > self.max_val:
                return False
            if not self.inclusive and val >= self.max_val:
                return False
        return True

class SpecificationEvaluator:
    def filter(self, items: List[Any], spec: Specification) -> List[Any]:
        return [item for item in items if spec.is_satisfied_by(item)]

if __name__ == "__main__":
    class Product:
        def __init__(self, name, price, category, active=True):
            self.name = name
            self.price = price
            self.category = category
            self.active = active
        def __repr__(self): return f"Product({self.name}, ${self.price}, {self.category})"
    
    products = [
        Product("Laptop", 1200, "electronics"),
        Product("Phone", 800, "electronics", active=False),
        Product("Book", 25, "books"),
        Product("Tablet", 500, "electronics"),
        Product("Pen", 5, "stationery"),
    ]
    
    evaluator = SpecificationEvaluator()
    
    is_electronic = EqualsSpecification("category", "electronics")
    is_active = EqualsSpecification("active", True)
    under_1000 = RangeSpecification("price", max_val=1000)
    expensive = LambdaSpecification(lambda p: p.price > 600)
    
    # Active electronics under $1000
    spec1 = is_electronic.and_spec(is_active).and_spec(under_1000)
    print(f"Active electronics < $1000: {evaluator.filter(products, spec1)}")
    
    # Expensive OR electronics
    spec2 = expensive.or_spec(is_electronic)
    print(f"Expensive or electronics: {evaluator.filter(products, spec2)}")
    
    # Not electronics
    spec3 = is_electronic.not_spec()
    print(f"Not electronics: {evaluator.filter(products, spec3)}")
    
    print("Specification pattern ready.")
