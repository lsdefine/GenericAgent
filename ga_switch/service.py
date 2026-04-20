import importlib.util
import json
import os

from .diagnostics import classify_error, normalize_message
from .store import GASwitchStore
from .testing import ModelTester


SAFE_PROVIDER_FIELDS = (
    "id",
    "name",
    "backend_kind",
    "backend_family",
    "model",
    "api_mode",
    "is_native",
    "is_enabled",
    "stream",
    "timeout",
    "read_timeout",
    "max_retries",
    "reasoning_effort",
    "thinking_type",
    "thinking_budget_tokens",
)


class GASwitchService:
    def __init__(self, db_path):
        self.db_path = db_path
        self.store = GASwitchStore(db_path)
        self.tester = ModelTester(self)

    def list_providers(self):
        return self.store.list_providers(enabled_only=False)

    def upsert_provider(self, provider):
        return self.store.upsert_provider(provider)

    def delete_provider(self, provider_id):
        return self.store.delete_provider(provider_id)

    def list_routes(self):
        return self.store.list_routes(enabled_only=False)

    def upsert_route(self, route):
        return self.store.upsert_route(route)

    def delete_route(self, route_id):
        return self.store.delete_route(route_id)

    def set_active_route(self, route_id):
        return self.store.set_active_route(route_id)

    def set_structured_config_enabled(self, enabled):
        self.store.set_setting("use_structured_config", bool(enabled))

    def use_structured_config(self):
        return bool(self.store.get_setting("use_structured_config", False))

    def has_usable_routes(self):
        return any(route["is_enabled"] for route in self.store.list_routes(enabled_only=True))

    def get_active_route_id(self):
        return self.store.get_setting("active_route_id")

    def _legacy_payload_to_provider(self, var_name, cfg):
        lower_name = str(var_name).lower()
        if "mixin" in lower_name:
            return None
        if "native" in lower_name and "claude" in lower_name:
            backend_kind = "native_claude"
        elif "native" in lower_name and "oai" in lower_name:
            backend_kind = "native_oai"
        elif "claude" in lower_name:
            backend_kind = "claude_text"
        elif "oai" in lower_name:
            backend_kind = "oai_text"
        else:
            return None
        return {
            "name": cfg.get("name") or var_name,
            "backend_kind": backend_kind,
            "apikey": cfg.get("apikey", ""),
            "apibase": cfg.get("apibase", ""),
            "model": cfg.get("model", ""),
            "api_mode": cfg.get("api_mode", "chat_completions"),
            "temperature": cfg.get("temperature", 1.0),
            "max_tokens": cfg.get("max_tokens", 8192),
            "context_win": cfg.get("context_win", 24000),
            "proxy": cfg.get("proxy"),
            "timeout": cfg.get("timeout", cfg.get("connect_timeout", 5)),
            "read_timeout": cfg.get("read_timeout", 30),
            "max_retries": cfg.get("max_retries", 1),
            "reasoning_effort": cfg.get("reasoning_effort"),
            "thinking_type": cfg.get("thinking_type"),
            "thinking_budget_tokens": cfg.get("thinking_budget_tokens"),
            "stream": cfg.get("stream", True),
            "is_enabled": True,
            "extra": {"legacy_var_name": var_name},
        }

    def _load_legacy_config(self, path=None):
        if not path:
            repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            py_path = os.path.join(repo_dir, "mykey.py")
            json_path = os.path.join(repo_dir, "mykey.json")
            path = py_path if os.path.exists(py_path) else json_path
        if not path or not os.path.exists(path):
            raise FileNotFoundError("Legacy config not found.")
        if path.lower().endswith(".json"):
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        else:
            spec = importlib.util.spec_from_file_location("ga_switch_legacy_mykey", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            payload = {key: value for key, value in vars(module).items() if not key.startswith("_")}
        return payload, path

    def import_legacy_mykey(self, path=None):
        payload, source_path = self._load_legacy_config(path)
        ordered_providers = []
        providers_by_name = {}
        for var_name, cfg in payload.items():
            if not isinstance(cfg, dict):
                continue
            provider = self._legacy_payload_to_provider(var_name, cfg)
            if not provider:
                continue
            saved = self.store.upsert_provider(provider)
            providers_by_name[saved["name"]] = saved
            ordered_providers.append(saved)
            self.store.upsert_route({
                "name": saved["name"],
                "kind": "single",
                "provider_id": saved["id"],
                "is_enabled": True,
                "is_default": False,
            })
        for var_name, cfg in payload.items():
            if not (isinstance(cfg, dict) and "mixin" in str(var_name).lower()):
                continue
            member_ids = []
            for ref in cfg.get("llm_nos") or []:
                if isinstance(ref, int):
                    if ref < 0 or ref >= len(ordered_providers):
                        raise ValueError(f"Invalid mixin index {ref} in {var_name}")
                    member_ids.append(ordered_providers[ref]["id"])
                    continue
                ref_name = str(ref).strip()
                provider = providers_by_name.get(ref_name)
                if provider is None:
                    raise ValueError(f"Mixin {var_name} references unknown provider name {ref_name}")
                member_ids.append(provider["id"])
            self.store.upsert_route({
                "name": cfg.get("name") or var_name,
                "kind": "failover",
                "member_provider_ids": member_ids,
                "is_enabled": True,
                "is_default": False,
                "config": {
                    "max_retries": cfg.get("max_retries", 3),
                    "base_delay": cfg.get("base_delay", 1.5),
                    "spring_back": cfg.get("spring_back", 300),
                },
            })
        routes = self.store.list_routes(enabled_only=False)
        if routes:
            self.store.set_setting("active_route_id", routes[0]["id"])
        self.store.set_setting("use_structured_config", True)
        return {
            "source_path": source_path,
            "providers": self.store.list_providers(enabled_only=False),
            "routes": self.store.list_routes(enabled_only=False),
        }

    def _safe_provider(self, provider):
        if provider is None:
            return None
        safe = {field: provider.get(field) for field in SAFE_PROVIDER_FIELDS}
        safe["health"] = dict(provider.get("health") or {})
        return safe

    def _safe_route(self, route):
        if route is None:
            return None
        return {
            "id": route["id"],
            "name": route["name"],
            "kind": route["kind"],
            "is_enabled": route["is_enabled"],
            "is_default": route["is_default"],
            "active": route.get("active", False),
            "config": dict(route.get("config") or {}),
            "provider": self._safe_provider(route.get("provider")),
            "members": [self._safe_provider(member) for member in route.get("members", [])],
            "member_provider_ids": list(route.get("member_provider_ids", [])),
        }

    def get_config_snapshot(self):
        providers = [self._safe_provider(provider) for provider in self.store.list_providers(enabled_only=False)]
        routes = [self._safe_route(route) for route in self.store.list_routes(enabled_only=False)]
        events = self.store.list_diagnostic_events(limit=100)
        return {
            "use_structured_config": self.use_structured_config(),
            "active_route_id": self.get_active_route_id(),
            "providers": providers,
            "routes": routes,
            "events": events,
            "stats": {
                "provider_count": len(providers),
                "route_count": len(routes),
            },
        }

    def get_runtime_diagnostics(self, config_snapshot, runtime_items):
        active_route_id = config_snapshot["active_route_id"]
        active_route = next((route for route in config_snapshot["routes"] if route["id"] == active_route_id), None)
        runtime_by_route_id = {item["route_id"]: item for item in runtime_items if item.get("route_id") is not None}
        active_runtime = runtime_by_route_id.get(active_route_id) or next((item for item in runtime_items if item.get("active")), None)
        active_route_summary = {
            "route_id": active_route_id,
            "route_name": (active_route or {}).get("name"),
            "route_kind": (active_route or {}).get("kind"),
            "provider_name": (active_runtime or {}).get("provider_name"),
            "model": (active_runtime or {}).get("model"),
            "backend_class": (active_runtime or {}).get("backend_class"),
            "backend_kind": (active_runtime or {}).get("backend_kind"),
            "api_mode": (active_runtime or {}).get("api_mode"),
            "native_tools": bool((active_runtime or {}).get("native_tools")),
            "member_names": list((active_runtime or {}).get("member_names", [])),
            "active_member_name": (active_runtime or {}).get("active_member_name"),
            "last_error_kind": (active_runtime or {}).get("last_error_kind"),
            "last_error_message": (active_runtime or {}).get("last_error_message"),
            "last_error_at": (active_runtime or {}).get("last_error_at"),
            "last_ok_at": (active_runtime or {}).get("last_ok_at"),
            "last_status_code": (active_runtime or {}).get("last_status_code"),
            "last_switch_reason": (active_runtime or {}).get("last_switch_reason"),
        }
        return {
            "use_structured_config": config_snapshot["use_structured_config"],
            "active_route_id": active_route_id,
            "active_route_summary": active_route_summary,
            "providers": config_snapshot["providers"],
            "routes": config_snapshot["routes"],
            "events": config_snapshot["events"],
            "runtime": runtime_items,
            "stats": dict(config_snapshot["stats"], runtime_count=len(runtime_items)),
        }

    def record_runtime_event(self, provider, *, route_id=None, route_name=None, backend_name="", ok=False, message="", status_code=None, latency_ms=None, ttfb_ms=None, body="", exc_type=""):
        error_kind = None if ok else classify_error(status_code=status_code, message=message, body=body, exc_type=exc_type)
        self.store.append_diagnostic_event(
            provider_id=provider["id"] if provider else None,
            route_id=route_id,
            backend_name=backend_name or (provider["name"] if provider else ""),
            ok=ok,
            error_kind=error_kind,
            message=normalize_message(message),
            status_code=status_code,
            extra={
                "route_name": route_name,
                "latency_ms": latency_ms,
                "ttfb_ms": ttfb_ms,
                "body": normalize_message(body, 1200),
                "exc_type": exc_type or None,
            },
        )
        if provider is None:
            return
        self.store.update_provider_health(
            provider["id"],
            status="healthy" if ok else "failed",
            latency_ms=latency_ms if ok else None,
            ttfb_ms=ttfb_ms if ok else None,
            last_error="" if ok else normalize_message(message),
        )

    def run_model_test(self, provider_id):
        return self.tester.run(provider_id)
