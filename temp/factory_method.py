#!/usr/bin/env python3
"""Factory Method Pattern - Object creation with configurable factories and product families"""
from typing import Dict, Type, Any, Optional
from abc import ABC, abstractmethod
from dataclasses import dataclass
import json

class Product(ABC):
    @abstractmethod
    def describe(self) -> str:
        pass
    
    @abstractmethod
    def cost(self) -> float:
        pass

class SimpleProduct(Product):
    def __init__(self, name: str, price: float):
        self.name = name
        self.price = price
    
    def describe(self) -> str:
        return f"Simple: {self.name} (${self.price:.2f})"
    
    def cost(self) -> float:
        return self.price

class PremiumProduct(Product):
    def __init__(self, name: str, price: float, features: list):
        self.name = name
        self.price = price
        self.features = features
    
    def describe(self) -> str:
        return f"Premium: {self.name} (${self.price:.2f}, {len(self.features)} features)"
    
    def cost(self) -> float:
        return self.price * 1.2  # 20% premium

class ServiceProduct(Product):
    def __init__(self, name: str, hourly_rate: float, hours: float):
        self.name = name
        self.hourly_rate = hourly_rate
        self.hours = hours
    
    def describe(self) -> str:
        return f"Service: {self.name} (${self.hourly_rate}/hr x {self.hours}h)"
    
    def cost(self) -> float:
        return self.hourly_rate * self.hours

class ProductFactory(ABC):
    @abstractmethod
    def create(self, **kwargs) -> Product:
        pass
    
    @abstractmethod
    def product_type(self) -> str:
        pass

class SimpleFactory(ProductFactory):
    def create(self, **kwargs) -> Product:
        return SimpleProduct(kwargs["name"], kwargs["price"])
    
    @property
    def product_type(self) -> str:
        return "simple"

class PremiumFactory(ProductFactory):
    def create(self, **kwargs) -> Product:
        return PremiumProduct(kwargs["name"], kwargs["price"], kwargs.get("features", []))
    
    @property
    def product_type(self) -> str:
        return "premium"

class ServiceFactory(ProductFactory):
    def create(self, **kwargs) -> Product:
        return ServiceProduct(kwargs["name"], kwargs["hourly_rate"], kwargs["hours"])
    
    @property
    def product_type(self) -> str:
        return "service"

class FactoryRegistry:
    def __init__(self):
        self._factories: Dict[str, ProductFactory] = {}
    
    def register(self, factory: ProductFactory):
        self._factories[factory.product_type] = factory
    
    def create(self, factory_type: str, **kwargs) -> Product:
        if factory_type not in self._factories:
            raise ValueError(f"Unknown factory: {factory_type}")
        return self._factories[factory_type].create(**kwargs)
    
    def list_types(self) -> list:
        return list(self._factories.keys())

@dataclass
class OrderItem:
    factory_type: str
    kwargs: Dict[str, Any]
    quantity: int = 1

class OrderProcessor:
    def __init__(self, registry: FactoryRegistry):
        self.registry = registry
        self.items: list = []
    
    def add_item(self, factory_type: str, **kwargs):
        self.items.append(OrderItem(factory_type, kwargs, kwargs.pop("quantity", 1)))
    
    def process(self) -> list:
        results = []
        for item in self.items:
            for _ in range(item.quantity):
                product = self.registry.create(item.factory_type, **item.kwargs)
                results.append({"product": product.describe(), "cost": product.cost()})
        return results
    
    def total_cost(self) -> float:
        return sum(item["cost"] for item in self.process())

if __name__ == "__main__":
    registry = FactoryRegistry()
    registry.register(SimpleFactory())
    registry.register(PremiumFactory())
    registry.register(ServiceFactory())
    
    print(f"Registered: {registry.list_types()}")
    
    # Create products directly
    p1 = registry.create("simple", name="Widget", price=9.99)
    p2 = registry.create("premium", name="Pro Widget", price=49.99, features=["fast", "secure"])
    p3 = registry.create("service", name="Consulting", hourly_rate=150, hours=4)
    
    print(p1.describe())
    print(p2.describe())
    print(p3.describe())
    
    # Process an order
    processor = OrderProcessor(registry)
    processor.add_item("simple", name="Widget", price=9.99, quantity=3)
    processor.add_item("premium", name="Pro Widget", price=49.99, features=["fast"])
    processor.add_item("service", name="Setup", hourly_rate=200, hours=2)
    
    results = processor.process()
    print(f"\nOrder items: {len(results)}")
    for r in results:
        print(f"  {r['product']} = ${r['cost']:.2f}")
    print(f"Total: ${processor.total_cost():.2f}")
    
    print("\nFactory method pattern ready.")
