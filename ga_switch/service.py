import importlib.util
import json
import os

from .models import PROVIDER_BACKEND_KINDS, is_native_backend_kind
from .store import GASwitchStore
from .testing import ModelTester


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
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        else:
            spec = importlib.util.spec_from_file_location("ga_switch_legacy_mykey", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            payload = {k: v for k, v in vars(module).items() if not k.startswith("_")}
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
            llm_nos = cfg.get("llm_nos") or []
            member_ids = []
            for ref in llm_nos:
                if isinstance(ref, int):
                    if ref < 0 or ref >= len(ordered_providers):
                        raise ValueError(f"Invalid mixin index {ref} in {var_name}")
                    member_ids.append(ordered_providers[ref]["id"])
                else:
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

    def export_legacy_config(self):
        payload = {}
        for provider in self.store.list_providers(enabled_only=False):
            payload[provider["name"]] = {
                "name": provider["name"],
                "apikey": provider["apikey"],
                "apibase": provider["apibase"],
                "model": provider["model"],
                "api_mode": provider["api_mode"],
                "temperature": provider["temperature"],
                "max_tokens": provider["max_tokens"],
                "context_win": provider["context_win"],
                "proxy": provider["proxy"],
                "timeout": provider["timeout"],
                "read_timeout": provider["read_timeout"],
                "max_retries": provider["max_retries"],
                "reasoning_effort": provider["reasoning_effort"],
                "thinking_type": provider["thinking_type"],
                "thinking_budget_tokens": provider["thinking_budget_tokens"],
                "stream": provider["stream"],
            }
        for route in self.store.list_routes(enabled_only=False):
            if route["kind"] != "failover":
                continue
            payload[f"mixin_{route['name']}"] = {
                "name": route["name"],
                "llm_nos": [member["name"] for member in route["members"]],
                "max_retries": route["config"].get("max_retries", 3),
                "base_delay": route["config"].get("base_delay", 1.5),
                "spring_back": route["config"].get("spring_back", 300),
            }
        return payload

    def _build_provider_cfg(self, provider, override=None):
        cfg = {
            "name": provider["name"],
            "apikey": provider["apikey"],
            "apibase": provider["apibase"],
            "model": provider.get("model") or "",
            "api_mode": provider.get("api_mode") or "chat_completions",
            "temperature": provider.get("temperature", 1.0),
            "max_tokens": provider.get("max_tokens", 8192),
            "context_win": provider.get("context_win", 24000),
            "proxy": provider.get("proxy"),
            "timeout": provider.get("timeout", 5),
            "read_timeout": provider.get("read_timeout", 30),
            "max_retries": provider.get("max_retries", 1),
            "reasoning_effort": provider.get("reasoning_effort"),
            "thinking_type": provider.get("thinking_type"),
            "thinking_budget_tokens": provider.get("thinking_budget_tokens"),
            "stream": provider.get("stream", True),
        }
        if override:
            cfg.update({k: v for k, v in override.items() if v is not None})
        return cfg

    def _diagnostic_recorder(self, provider, route_id, route_name):
        def _record(event):
            self.store.append_diagnostic_event(
                provider_id=provider["id"],
                route_id=route_id,
                backend_name=event.get("backend_name") or provider["name"],
                ok=event.get("ok", False),
                error_kind=event.get("error_kind"),
                message=event.get("message", ""),
                status_code=event.get("status_code"),
                extra=event.get("extra") or {"route_name": route_name},
            )
            if event.get("ok"):
                self.store.update_provider_health(
                    provider["id"],
                    status="healthy",
                    latency_ms=(event.get("extra") or {}).get("latency_ms"),
                    ttfb_ms=(event.get("extra") or {}).get("ttfb_ms"),
                    last_error="",
                )
            else:
                self.store.update_provider_health(
                    provider["id"],
                    status="failed",
                    last_error=event.get("message", ""),
                )
        return _record

    def build_client_from_provider(self, provider, *, route_id=None, route_name=None, route_kind="single", for_testing=False, override=None):
        from llmcore import LLMSession, ToolClient, ClaudeSession, NativeToolClient, NativeClaudeSession, NativeOAISession

        cfg = self._build_provider_cfg(provider, override=override)
        backend_kind = provider["backend_kind"]
        if backend_kind not in PROVIDER_BACKEND_KINDS:
            raise ValueError(f"Unsupported backend_kind: {backend_kind}")
        if backend_kind == "native_claude":
            backend = NativeClaudeSession(cfg=cfg)
            client = NativeToolClient(backend)
        elif backend_kind == "native_oai":
            backend = NativeOAISession(cfg=cfg)
            client = NativeToolClient(backend)
        elif backend_kind == "claude_text":
            backend = ClaudeSession(cfg=cfg)
            client = ToolClient(backend)
        else:
            backend = LLMSession(cfg=cfg)
            client = ToolClient(backend)
        backend.provider_id = provider["id"]
        backend.provider_name = provider["name"]
        backend.route_id = route_id
        backend.route_name = route_name or provider["name"]
        backend.route_kind = route_kind
        backend.backend_kind = backend_kind
        backend._diagnostic_recorder = self._diagnostic_recorder(provider, route_id, route_name or provider["name"])
        backend._ga_switch_testing = bool(for_testing)
        client.ga_switch_provider = provider
        client.ga_switch_route_id = route_id
        client.ga_switch_route_name = route_name or provider["name"]
        client.ga_switch_route_kind = route_kind
        client.ga_switch_backend_kind = backend_kind
        return client

    def build_client_for_route(self, route):
        from llmcore import MixinSession, ToolClient, NativeToolClient

        if route["kind"] == "single":
            provider = route["provider"]
            if provider is None:
                raise ValueError(f"Single route {route['name']} is missing provider.")
            client = self.build_client_from_provider(
                provider,
                route_id=route["id"],
                route_name=route["name"],
                route_kind=route["kind"],
            )
            client.ga_switch_members = [provider]
            return client
        members = [
            self.build_client_from_provider(
                provider,
                route_id=route["id"],
                route_name=route["name"],
                route_kind=route["kind"],
            )
            for provider in route["members"]
        ]
        mixin_cfg = {
            "llm_nos": [member.backend.name for member in members],
            "max_retries": route["config"].get("max_retries", 3),
            "base_delay": route["config"].get("base_delay", 1.5),
            "spring_back": route["config"].get("spring_back", 300),
        }
        mixin = MixinSession(members, mixin_cfg)
        mixin.name = route["name"]
        mixin.route_id = route["id"]
        mixin.route_name = route["name"]
        mixin.route_kind = route["kind"]
        mixin.ga_switch_members = route["members"]
        if is_native_backend_kind(route["members"][0]["backend_kind"]):
            client = NativeToolClient(mixin)
        else:
            client = ToolClient(mixin)
        client.ga_switch_provider = None
        client.ga_switch_route_id = route["id"]
        client.ga_switch_route_name = route["name"]
        client.ga_switch_route_kind = route["kind"]
        client.ga_switch_backend_kind = "mixin"
        client.ga_switch_members = route["members"]
        return client

    def build_clients_from_store(self):
        routes = self.store.list_routes(enabled_only=True)
        clients = [self.build_client_for_route(route) for route in routes]
        active_route_id = self.store.get_setting("active_route_id")
        if not clients:
            return [], {"active_route_id": active_route_id, "routes": routes, "source": "store", "active_index": 0}
        active_index = next((i for i, route in enumerate(routes) if route["id"] == active_route_id), 0)
        return clients, {"active_route_id": active_route_id, "routes": routes, "source": "store", "active_index": active_index}

    def run_model_test(self, provider_id):
        return self.tester.run(provider_id)

    def reload_agent(self, agent, preserve_history=True):
        return agent.reload_llm_config(preserve_history=preserve_history)

    def get_ui_snapshot(self, agent=None):
        providers = self.store.list_providers(enabled_only=False)
        routes = self.store.list_routes(enabled_only=False)
        events = self.store.list_diagnostic_events(limit=100)
        runtime = agent.describe_llms() if agent is not None and hasattr(agent, "describe_llms") else []
        active_route_id = self.get_active_route_id()
        active_route = next((route for route in routes if route["id"] == active_route_id), None)
        runtime_by_route_id = {item["route_id"]: item for item in runtime if item.get("route_id") is not None}
        active_runtime = runtime_by_route_id.get(active_route_id) or next((item for item in runtime if item.get("active")), None)
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
            "use_structured_config": self.use_structured_config(),
            "active_route_id": active_route_id,
            "active_route": active_route,
            "active_runtime": active_runtime,
            "active_route_summary": active_route_summary,
            "providers": providers,
            "providers_by_id": {provider["id"]: provider for provider in providers},
            "routes": routes,
            "routes_by_id": {route["id"]: route for route in routes},
            "runtime": runtime,
            "runtime_by_route_id": runtime_by_route_id,
            "events": events,
            "recent_events": events[:20],
            "stats": {
                "provider_count": len(providers),
                "route_count": len(routes),
                "runtime_count": len(runtime),
            },
        }

    def get_runtime_diagnostics(self, agent=None):
        snapshot = self.get_ui_snapshot(agent)
        return {
            "use_structured_config": snapshot["use_structured_config"],
            "active_route_id": snapshot["active_route_id"],
            "providers": snapshot["providers"],
            "routes": snapshot["routes"],
            "events": snapshot["events"],
            "runtime": snapshot["runtime"],
            "active_route_summary": snapshot["active_route_summary"],
        }
