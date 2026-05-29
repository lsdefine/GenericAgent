import os
import sys
import importlib

# 模块级注册表: event_name -> [callback, ...]
_registry = {}
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def register(event):
    def decorator(fn):
        _registry.setdefault(event, []).append(fn)
        return fn
    return decorator


def trigger(event, ctx: dict):
    for fn in _registry.get(event, []):
        try:
            r = fn(ctx)
            if isinstance(r, dict):
                ctx = r
        except Exception as e:
            sys.stderr.write(f"[hooks] {event} callback error: {e}\n")
    return ctx


def unregister(event, fn):
    try:
        _registry[event] = [f for f in _registry[event] if f is not fn]
    except KeyError:
        pass


def clear(event=None):
    if event:
        _registry.pop(event, None)
    else:
        _registry.clear()


def has(event):
    return bool(_registry.get(event))


def discover_and_load(plugin_dir=None):
    if plugin_dir is None:
        plugin_dir = os.path.join(_PROJECT_ROOT, 'plugins')
    if not os.path.isdir(plugin_dir):
        return
    parent = os.path.dirname(plugin_dir)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    for fn in sorted(os.listdir(plugin_dir)):
        if fn.startswith('_') or not fn.endswith('.py'):
            continue
        name = fn[:-3]
        load(name)


def load(name):
    try:
        importlib.import_module(f'plugins.{name}')
        return True
    except Exception as e:
        sys.stderr.write(f"[hooks] plugin '{name}' load failed: {e}\n")
        return False