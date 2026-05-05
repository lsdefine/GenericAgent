#!/usr/bin/env python3
"""Dependency Injection - Lightweight DI container with singleton/transient scopes and auto-wiring"""
import inspect
from typing import Dict, Type, Any, Callable, Optional

class DependencyInjector:
    """
    Dependency injection container supporting:
    - register(cls, impl, scope="singleton"|"transient")
    - resolve(cls) - auto-wires constructor dependencies
    - inject decorator for functions/methods
    """
    def __init__(self):
        self._registrations: Dict[Type, dict] = {}
        self._singletons: Dict[Type, Any] = {}
    
    def register(self, interface: Type, implementation: Optional[Type] = None, scope: str = "singleton"):
        impl = implementation or interface
        self._registrations[interface] = {"impl": impl, "scope": scope}
    
    def register_instance(self, interface: Type, instance: Any):
        self._singletons[interface] = instance
        self._registrations[interface] = {"impl": interface, "scope": "singleton"}
    
    def resolve(self, interface: Type) -> Any:
        if interface in self._singletons:
            return self._singletons[interface]
        
        reg = self._registrations.get(interface)
        if not reg:
            raise ValueError(f"No registration for {interface}")
        
        impl = reg["impl"]
        if reg["scope"] == "singleton" and impl in self._singletons:
            return self._singletons[impl]
        
        instance = self._instantiate(impl)
        if reg["scope"] == "singleton":
            self._singletons[impl] = instance
        return instance
    
    def _instantiate(self, cls: Type) -> Any:
        sig = inspect.signature(cls.__init__)
        kwargs = {}
        for name, param in sig.parameters.items():
            if name == "self":
                continue
            if param.annotation != inspect.Parameter.empty and param.annotation in self._registrations:
                kwargs[name] = self.resolve(param.annotation)
            elif param.default != inspect.Parameter.empty:
                kwargs[name] = param.default
        return cls(**kwargs)
    
    def inject(self, **dependencies: Type):
        def decorator(func: Callable):
            def wrapper(*args, **kwargs):
                resolved = {}
                for name, iface in dependencies.items():
                    if name not in kwargs:
                        resolved[name] = self.resolve(iface)
                return func(*args, **{**kwargs, **resolved})
            return wrapper
        return decorator


if __name__ == "__main__":
    class Database:
        def __init__(self, host: str = "localhost"):
            self.host = host
        def query(self): return f"Querying {self.host}"
    
    class Cache:
        def get(self, key): return f"Cached:{key}"
    
    class UserService:
        def __init__(self, db: Database, cache: Cache):
            self.db = db
            self.cache = cache
        def get_user(self, uid):
            cached = self.cache.get(uid)
            return f"User {uid}: {cached}, db={self.db.query()}"
    
    container = DependencyInjector()
    container.register(Database, scope="singleton")
    container.register(Cache)
    container.register(UserService, scope="transient")
    
    svc1 = container.resolve(UserService)
    svc2 = container.resolve(UserService)
    print(f"UserService transient: {svc1 is not svc2}")
    print(f"Result: {svc1.get_user('123')}")
    
    db = container.resolve(Database)
    db2 = container.resolve(Database)
    print(f"Database singleton: {db is db2}")
    
    @container.inject(db=Database, cache=Cache)
    def fetch_data(db, cache):
        return cache.get("data") + " | " + db.query()
    
    print(f"Injected: {fetch_data()}")
    print("Dependency injection ready.")
