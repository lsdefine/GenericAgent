#!/usr/bin/env python3
"""Observer Pattern - Reactive event system with typed events and async support"""
from typing import Dict, List, Callable, Any, Optional
from abc import ABC, abstractmethod
import asyncio
from dataclasses import dataclass, field
from datetime import datetime

@dataclass
class Event:
    name: str
    source: Any
    timestamp: datetime = field(default_factory=datetime.now)
    data: Dict[str, Any] = field(default_factory=dict)

class Observer(ABC):
    @abstractmethod
    def update(self, event: Event):
        pass

class Subject:
    def __init__(self):
        self._observers: List[Observer] = []
    
    def attach(self, observer: Observer):
        if observer not in self._observers:
            self._observers.append(observer)
    
    def detach(self, observer: Observer):
        self._observers.remove(observer)
    
    def notify(self, event: Event):
        for observer in self._observers:
            observer.update(event)

class EventBus(Subject):
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not hasattr(self, '_initialized'):
            super().__init__()
            self._event_handlers: Dict[str, List[Callable]] = {}
            self._event_log: List[Event] = []
            self._initialized = True
    
    def on(self, event_name: str, handler: Callable):
        if event_name not in self._event_handlers:
            self._event_handlers[event_name] = []
        self._event_handlers[event_name].append(handler)
    
    def off(self, event_name: str, handler: Callable):
        if event_name in self._event_handlers:
            self._event_handlers[event_name].remove(handler)
    
    def emit(self, event_name: str, source: Any = None, **data):
        event = Event(name=event_name, source=source, data=data)
        self._event_log.append(event)
        
        # Notify subscribers
        if event_name in self._event_handlers:
            for handler in self._event_handlers[event_name]:
                handler(event)
        
        self.notify(event)
    
    def get_log(self) -> List[Event]:
        return self._event_log.copy()

class DataStore:
    def __init__(self):
        self._data = {}
        self._bus = EventBus()
    
    def set(self, key: str, value: Any):
        old_value = self._data.get(key)
        self._data[key] = value
        self._bus.emit("data_changed", source=self, key=key, value=value, old_value=old_value)
    
    def get(self, key: str) -> Any:
        return self._data.get(key)
    
    def delete(self, key: str):
        if key in self._data:
            value = self._data.pop(key)
            self._bus.emit("data_deleted", source=self, key=key, value=value)

class AuditObserver(Observer):
    def __init__(self):
        self.audit_log = []
    
    def update(self, event: Event):
        self.audit_log.append({
            "time": event.timestamp.isoformat(),
            "event": event.name,
            "key": event.data.get("key"),
            "value": event.data.get("value")
        })

class ValidationObserver(Observer):
    def __init__(self):
        self.validation_errors = []
    
    def update(self, event: Event):
        if event.name == "data_changed" and event.data.get("value") is None:
            self.validation_errors.append(f"Null value set for key: {event.data.get('key')}")

if __name__ == "__main__":
    bus = EventBus()
    
    # Observer pattern demo
    audit = AuditObserver()
    validation = ValidationObserver()
    
    store = DataStore()
    bus.attach(audit)
    bus.attach(validation)
    
    # Simulate data changes
    store.set("user", {"name": "Alice"})
    store.set("config", None)  # Should trigger validation
    store.set("count", 42)
    store.delete("user")
    
    print(f"Audit entries: {len(audit.audit_log)}")
    for entry in audit.audit_log[:2]:
        print(f"  {entry['event']}: key={entry['key']}")
    
    print(f"Validation errors: {validation.validation_errors}")
    
    # Handler-based events
    notifications = []
    bus.on("order_placed", lambda e: notifications.append(f"Order: {e.data.get('id')}"))
    bus.emit("order_placed", source=None, id="ORD-001", amount=99.99)
    print(f"Notifications: {notifications}")
    
    print("\nObserver pattern ready.")
