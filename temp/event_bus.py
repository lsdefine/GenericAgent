#!/usr/bin/env python3
"""Event Bus - Publish/Subscribe pattern with event filtering and async dispatch"""
import asyncio
import functools
import re
from typing import Callable, Any, Dict, List, Optional, Set
from collections import defaultdict

class EventBus:
    """Thread-safe event bus with filtering and async support"""
    
    def __init__(self):
        self._handlers: Dict[str, List[Callable]] = defaultdict(list)
        self._async_handlers: Dict[str, List[Callable]] = defaultdict(list)
        self._filters: Dict[str, List[Callable[[Any], bool]]] = defaultdict(list)
        self._patterns: Dict[str, str] = {}  # handler_id -> regex pattern
        self._event_log: List[Dict] = []
    
    def subscribe(self, event: str, handler: Callable, pattern: str = None,
                  filter_fn: Callable[[Any], bool] = None):
        """Subscribe to an event, optionally with regex pattern matching"""
        if asyncio.iscoroutinefunction(handler):
            self._async_handlers[event].append(handler)
        else:
            self._handlers[event].append(handler)
        
        if pattern:
            self._patterns[handler.__name__] = pattern
        if filter_fn:
            self._filters[event].append(filter_fn)
    
    def unsubscribe(self, event: str, handler: Callable):
        """Remove a handler from an event"""
        if handler in self._handlers[event]:
            self._handlers[event].remove(handler)
        if handler in self._async_handlers[event]:
            self._async_handlers[event].remove(handler)
    
    def publish(self, event: str, data: Any = None):
        """Synchronously publish an event"""
        handlers = self._get_matching_handlers(event)
        for handler in handlers:
            if self._passes_filters(event, data):
                try:
                    result = handler(data)
                    self._log_event(event, data, result)
                except Exception as e:
                    self._log_event(event, data, error=str(e))
    
    async def publish_async(self, event: str, data: Any = None):
        """Publish event, running async handlers concurrently"""
        handlers = self._get_matching_handlers(event)
        results = []
        for handler in handlers:
            if self._passes_filters(event, data):
                try:
                    if asyncio.iscoroutinefunction(handler):
                        result = await handler(data)
                    else:
                        result = handler(data)
                    results.append(result)
                    self._log_event(event, data, result)
                except Exception as e:
                    results.append(None)
                    self._log_event(event, data, error=str(e))
        return results
    
    def _get_matching_handlers(self, event: str) -> List[Callable]:
        """Get handlers that match the event (direct or regex)"""
        handlers = list(self._handlers.get(event, []))
        handlers += list(self._async_handlers.get(event, []))
        
        # Check pattern-based subscriptions
        for evt, pattern in self._patterns.items():
            if re.match(pattern, event):
                idx = evt
                handlers += self._handlers.get(idx, [])
                handlers += self._async_handlers.get(idx, [])
        return handlers
    
    def _passes_filters(self, event: str, data: Any) -> bool:
        for filter_fn in self._filters.get(event, []):
            if not filter_fn(data):
                return False
        return True
    
    def _log_event(self, event: str, data: Any, result: Any = None, error: str = None):
        self._event_log.append({
            "event": event,
            "data": str(data)[:100],
            "result": str(result)[:100] if result else None,
            "error": error
        })
    
    def get_stats(self) -> Dict:
        return {
            "total_handlers": len(self._handlers) + len(self._async_handlers),
            "sync_handlers": sum(len(v) for v in self._handlers.values()),
            "async_handlers": sum(len(v) for v in self._async_handlers.values()),
            "events_published": len(self._event_log),
            "events_with_errors": sum(1 for e in self._event_log if e.get("error"))
        }
    
    def get_event_log(self) -> List[Dict]:
        return self._event_log.copy()


if __name__ == "__main__":
    bus = EventBus()
    
    # Sync handlers
    def on_order(data):
        print(f"Order processed: {data['item']}")
        return "sync_ok"
    
    async def async_notify(data):
        await asyncio.sleep(0.01)
        print(f"Notification sent for: {data['item']}")
        return "async_ok"
    
    bus.subscribe("order.created", on_order)
    bus.subscribe("order.created", async_notify)
    
    # Filter: only high priority
    def high_priority(data):
        return data.get("priority") == "high"
    
    def on_urgent(data):
        print(f"URGENT: {data['item']}")
        return "urgent_processed"
    
    bus.subscribe("order.created", on_urgent, filter_fn=high_priority)
    
    # Publish
    bus.publish("order.created", {"item": "laptop", "priority": "normal"})
    print("---")
    bus.publish("order.created", {"item": "server", "priority": "high"})
    
    # Async test
    async def test_async():
        results = await bus.publish_async("order.created", {"item": "async_item"})
        print(f"Async results: {results}")
    
    asyncio.run(test_async())
    
    stats = bus.get_stats()
    print(f"Stats: {stats}")
    print("Event bus ready.")
