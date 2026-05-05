#!/usr/bin/env python3
"""Plugin System - Dynamic loading, lifecycle management, and hook system"""
import os
import sys
import importlib
import importlib.util
from typing import Dict, List, Callable, Any, Optional, Type
from enum import Enum
from datetime import datetime

class PluginState(Enum):
    UNLOADED = "unloaded"
    LOADED = "loaded"
    ACTIVE = "active"
    DISABLED = "disabled"
    ERROR = "error"

class Plugin:
    """Base plugin with lifecycle management"""
    
    def __init__(self, name: str, version: str = "1.0.0", description: str = ""):
        self.name = name
        self.version = version
        self.description = description
        self.state = PluginState.UNLOADED
        self.load_time = None
        self.hooks: Dict[str, List[Callable]] = {}
    
    def initialize(self):
        """Called when plugin is first loaded"""
        pass
    
    def activate(self):
        """Called when plugin becomes active"""
        self.state = PluginState.ACTIVE
    
    def deactivate(self):
        """Called when plugin is deactivated"""
        self.state = PluginState.DISABLED
    
    def cleanup(self):
        """Called when plugin is unloaded"""
        pass
    
    def register_hook(self, hook_name: str, callback: Callable):
        if hook_name not in self.hooks:
            self.hooks[hook_name] = []
        self.hooks[hook_name].append(callback)


class PluginManager:
    """Manages plugin lifecycle, discovery, and execution"""
    
    def __init__(self, plugin_dirs: List[str] = None):
        self.plugin_dirs = plugin_dirs or []
        self.plugins: Dict[str, Plugin] = {}
        self._hook_registry: Dict[str, List[Callable]] = {}
    
    def register(self, plugin: Plugin):
        """Register a plugin instance"""
        self.plugins[plugin.name] = plugin
    
    def load(self, name: str) -> bool:
        """Load and initialize a plugin"""
        plugin = self.plugins.get(name)
        if not plugin:
            return False
        
        try:
            plugin.initialize()
            plugin.state = PluginState.LOADED
            plugin.load_time = str(datetime.now())[:19]
            
            # Register hooks
            for hook_name, callbacks in plugin.hooks.items():
                if hook_name not in self._hook_registry:
                    self._hook_registry[hook_name] = []
                self._hook_registry[hook_name].extend(callbacks)
            
            return True
        except Exception as e:
            plugin.state = PluginState.ERROR
            return False
    
    def activate(self, name: str) -> bool:
        plugin = self.plugins.get(name)
        if plugin and plugin.state == PluginState.LOADED:
            plugin.activate()
            return True
        return False
    
    def deactivate(self, name: str) -> bool:
        plugin = self.plugins.get(name)
        if plugin and plugin.state == PluginState.ACTIVE:
            plugin.deactivate()
            return True
        return False
    
    def unload(self, name: str) -> bool:
        plugin = self.plugins.get(name)
        if plugin:
            try:
                plugin.cleanup()
                # Remove hooks
                for hook_name, callbacks in plugin.hooks.items():
                    if hook_name in self._hook_registry:
                        for cb in callbacks:
                            if cb in self._hook_registry[hook_name]:
                                self._hook_registry[hook_name].remove(cb)
                plugin.state = PluginState.UNLOADED
                plugin.load_time = None
                return True
            except Exception:
                return False
        return False
    
    def execute_hook(self, hook_name: str, *args, **kwargs) -> List[Any]:
        """Execute all callbacks registered for a hook"""
        results = []
        for callback in self._hook_registry.get(hook_name, []):
            try:
                result = callback(*args, **kwargs)
                results.append(result)
            except Exception:
                pass
        return results
    
    def discover_from_dir(self, directory: str):
        """Discover Python files in a directory as potential plugins"""
        if not os.path.isdir(directory):
            return
        
        for fn in os.listdir(directory):
            if fn.endswith(".py") and not fn.startswith("_"):
                path = os.path.join(directory, fn)
                module_name = fn[:-3]
                
                spec = importlib.util.spec_from_file_location(module_name, path)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    try:
                        spec.loader.exec_module(module)
                        
                        # Look for Plugin subclass instances
                        for attr_name in dir(module):
                            attr = getattr(module, attr_name)
                            if isinstance(attr, Plugin) and not isinstance(attr, type):
                                self.register(attr)
                    except Exception:
                        pass
    
    def get_status(self) -> Dict:
        return {
            name: {"version": p.version, "state": p.state.value, "load_time": p.load_time}
            for name, p in self.plugins.items()
        }
    
    def list_plugins(self) -> List[Dict]:
        return [
            {"name": p.name, "version": p.version, "state": p.state.value, "hooks": len(p.hooks)}
            for p in self.plugins.values()
        ]


if __name__ == "__main__":
    manager = PluginManager()
    
    # Create test plugins
    class LoggerPlugin(Plugin):
        def __init__(self):
            super().__init__("logger", "1.0.0", "Simple logger")
            self.register_hook("on_start", lambda: "Logger started")
            self.register_hook("on_data", lambda d: f"Logged: {d}")
            self.log = []
        
        def initialize(self):
            self.log.append("Initialized")
        
        def activate(self):
            super().activate()
            self.log.append("Activated")
    
    class CachePlugin(Plugin):
        def __init__(self):
            super().__init__("cache", "2.0.0", "In-memory cache")
            self.register_hook("on_data", lambda d: f"Cached: {d}")
        
        def initialize(self):
            pass
    
    lp = LoggerPlugin()
    cp = CachePlugin()
    
    manager.register(lp)
    manager.register(cp)
    
    # Lifecycle test
    manager.load("logger")
    manager.activate("logger")
    manager.load("cache")
    manager.activate("cache")
    
    print("Status:", manager.get_status())
    
    # Hook execution
    results = manager.execute_hook("on_data", "test_payload")
    print(f"Hook results: {results}")
    
    # Deactivate and unload
    manager.deactivate("logger")
    manager.unload("logger")
    
    print("After unload:", manager.get_status())
    print("Plugin list:", manager.list_plugins())
    
    print("Plugin system ready.")
