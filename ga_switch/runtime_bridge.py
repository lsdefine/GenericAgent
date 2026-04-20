from llmcore import (
    ClaudeSession,
    LLMSession,
    MixinSession,
    NativeClaudeSession,
    NativeOAISession,
    NativeToolClient,
    ToolClient,
)

from .diagnostics import classify_error


def _provider_cfg(provider, override=None):
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
        cfg.update({key: value for key, value in override.items() if value is not None})
    return cfg


def _backend_error_kind(backend):
    return classify_error(
        status_code=getattr(backend, "last_status_code", None),
        message=getattr(backend, "last_error_message", ""),
    )


def _attach_runtime_metadata(client, *, source, route_id, route_name, route_kind, backend_kind, provider=None, members=None):
    meta = {
        "source": source,
        "route_id": route_id,
        "route_name": route_name,
        "route_kind": route_kind,
        "backend_kind": backend_kind,
        "provider": provider,
        "provider_id": provider["id"] if provider else None,
        "provider_name": provider["name"] if provider else None,
        "members": list(members or []),
    }
    client.ga_switch_meta = meta
    client.ga_switch_route_id = route_id
    client.ga_switch_route_name = route_name
    client.ga_switch_route_kind = route_kind
    client.ga_switch_backend_kind = backend_kind
    client.ga_switch_members = list(members or ([] if provider is None else [provider]))
    return client


def _resolve_event_provider(client):
    meta = getattr(client, "ga_switch_meta", {})
    provider = meta.get("provider")
    if provider is not None:
        return provider
    active_member_name = getattr(client.backend, "active_member_name", None)
    if not active_member_name:
        return None
    for member in meta.get("members", []):
        if member.get("name") == active_member_name:
            return member
    return None


def _wrap_client_chat(service, client):
    if getattr(client, "_ga_switch_chat_wrapped", False):
        return client

    original_chat = client.chat

    def wrapped_chat(messages, tools=None):
        generator = original_chat(messages, tools=tools)
        last_chunk = ""
        response = None
        try:
            while True:
                chunk = next(generator)
                last_chunk = chunk
                yield chunk
        except StopIteration as stop:
            response = stop.value

        backend = client.backend
        provider = _resolve_event_provider(client)
        meta = getattr(client, "ga_switch_meta", {})
        last_error_message = getattr(backend, "last_error_message", "") or ""
        status_code = getattr(backend, "last_status_code", None)
        ok = not last_error_message and not (isinstance(last_chunk, str) and last_chunk.startswith("Error:"))
        message = "OK" if ok else (last_error_message or str(last_chunk or "Error"))
        service.record_runtime_event(
            provider,
            route_id=meta.get("route_id"),
            route_name=meta.get("route_name"),
            backend_name=getattr(backend, "name", ""),
            ok=ok,
            message=message,
            status_code=status_code,
            latency_ms=getattr(backend, "last_latency_ms", None),
            ttfb_ms=getattr(backend, "last_ttfb_ms", None),
        )
        return response

    client.chat = wrapped_chat
    client._ga_switch_chat_wrapped = True
    return client


def _build_client_from_provider(service, provider, *, source, route_id=None, route_name=None, route_kind="single", override=None):
    cfg = _provider_cfg(provider, override=override)
    backend_kind = provider["backend_kind"]
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
    _attach_runtime_metadata(
        client,
        source=source,
        route_id=route_id,
        route_name=route_name or provider["name"],
        route_kind=route_kind,
        backend_kind=backend_kind,
        provider=provider,
    )
    return _wrap_client_chat(service, client)


def build_test_client(service, provider, override=None):
    return _build_client_from_provider(
        service,
        provider,
        source="test",
        route_id=None,
        route_name=f"test:{provider['name']}",
        route_kind="single",
        override=override,
    )


def _build_structured_clients(service):
    routes = service.store.list_routes(enabled_only=True)
    active_route_id = service.get_active_route_id()
    clients = []
    for route in routes:
        if route["kind"] == "single":
            provider = route["provider"]
            if provider is None:
                raise ValueError(f"Single route {route['name']} is missing provider.")
            client = _build_client_from_provider(
                service,
                provider,
                source="store",
                route_id=route["id"],
                route_name=route["name"],
                route_kind=route["kind"],
            )
            client.ga_switch_members = [provider]
        else:
            members = [
                _build_client_from_provider(
                    service,
                    provider,
                    source="store",
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
            client = NativeToolClient(mixin) if route["members"] and route["members"][0]["is_native"] else ToolClient(mixin)
            _attach_runtime_metadata(
                client,
                source="store",
                route_id=route["id"],
                route_name=route["name"],
                route_kind=route["kind"],
                backend_kind="mixin",
                provider=None,
                members=route["members"],
            )
            _wrap_client_chat(service, client)
        clients.append(client)
    active_index = next((index for index, route in enumerate(routes) if route["id"] == active_route_id), 0)
    return clients, {"source": "store", "routes": routes, "active_route_id": active_route_id, "active_index": active_index}


def _build_legacy_clients():
    from llmcore import mykeys

    sessions = []
    for key, cfg in mykeys.items():
        if not any(token in key for token in ("api", "config", "cookie")):
            continue
        route_name = cfg.get("name") or key
        try:
            if "native" in key and "claude" in key:
                client = NativeToolClient(NativeClaudeSession(cfg=cfg))
                backend_kind = "native_claude"
            elif "native" in key and "oai" in key:
                client = NativeToolClient(NativeOAISession(cfg=cfg))
                backend_kind = "native_oai"
            elif "claude" in key:
                client = ToolClient(ClaudeSession(cfg=cfg))
                backend_kind = "claude_text"
            elif "oai" in key:
                client = ToolClient(LLMSession(cfg=cfg))
                backend_kind = "oai_text"
            elif "mixin" in key:
                sessions.append({"mixin_cfg": cfg, "route_name": route_name})
                continue
            else:
                continue
            sessions.append(_attach_runtime_metadata(
                client,
                source="legacy",
                route_id=None,
                route_name=route_name,
                route_kind="single",
                backend_kind=backend_kind,
                provider=None,
            ))
        except Exception as exc:
            print(f"[WARN] Failed to init legacy session {key}: {exc}")
    for index, item in enumerate(sessions):
        if not isinstance(item, dict):
            continue
        try:
            mixin = MixinSession(sessions, item["mixin_cfg"])
            client = NativeToolClient(mixin) if "Native" in type(mixin._sessions[0]).__name__ else ToolClient(mixin)
            sessions[index] = _attach_runtime_metadata(
                client,
                source="legacy",
                route_id=None,
                route_name=item["route_name"],
                route_kind="failover",
                backend_kind="mixin",
                provider=None,
            )
        except Exception as exc:
            print(f"[WARN] Failed to init MixinSession with cfg {item['mixin_cfg']}: {exc}")
    clients = [client for client in sessions if not isinstance(client, dict)]
    return clients, {"source": "legacy", "routes": [], "active_route_id": None, "active_index": 0}


def load_clients(agent, preserve_history=True, initial=False):
    old_client = getattr(agent, "llmclient", None)
    old_history = getattr(old_client.backend, "history", None) if old_client is not None and preserve_history else None
    old_index = getattr(agent, "llm_no", 0)

    if agent.ga_switch.use_structured_config():
        clients, meta = _build_structured_clients(agent.ga_switch)
    else:
        clients, meta = _build_legacy_clients()

    agent.llmclients = clients
    agent.config_source = meta["source"]
    agent.config_meta = meta
    if not clients:
        agent.llm_no = 0
        agent.llmclient = None
        return []

    target_index = meta.get("active_index", 0)
    if not initial and meta["source"] == "legacy" and old_index < len(clients):
        target_index = old_index
    agent.llm_no = target_index % len(clients)
    agent.llmclient = clients[agent.llm_no]
    if preserve_history and old_history is not None:
        agent.llmclient.backend.history = old_history
    if hasattr(agent, "_sync_tool_schema"):
        agent._sync_tool_schema()
    return clients


def _switch_index(agent, index):
    if not agent.llmclients:
        agent.llmclient = None
        return None
    last_client = agent.llmclient
    agent.llm_no = index % len(agent.llmclients)
    agent.llmclient = agent.llmclients[agent.llm_no]
    if last_client is not None:
        agent.llmclient.backend.history = last_client.backend.history
    if hasattr(agent.llmclient, "last_tools"):
        agent.llmclient.last_tools = ""
    if agent.config_source == "store":
        route_id = getattr(agent.llmclient, "ga_switch_route_id", None)
        if route_id is not None:
            agent.ga_switch.set_active_route(route_id)
    if hasattr(agent, "_sync_tool_schema"):
        agent._sync_tool_schema()
    return agent.llmclient


def next_client(agent, n=-1):
    if not agent.llmclients:
        agent.llmclient = None
        return None
    index = (agent.llm_no + 1) if n < 0 else n
    return _switch_index(agent, index)


def set_active_route(agent, route_id_or_idx):
    if agent.config_source == "store":
        runtime_items = describe_runtime(agent)
        target = next((item for item in runtime_items if item["route_id"] == route_id_or_idx), None)
        if target is None and isinstance(route_id_or_idx, int) and 0 <= route_id_or_idx < len(runtime_items):
            target = runtime_items[route_id_or_idx]
        if target is None:
            raise ValueError(f"Unknown route id: {route_id_or_idx}")
        agent.ga_switch.set_active_route(target["route_id"])
        load_clients(agent, preserve_history=True, initial=False)
        return describe_runtime(agent)[agent.llm_no]
    if not isinstance(route_id_or_idx, int):
        raise ValueError(f"Legacy mode only supports index switching, got {route_id_or_idx!r}")
    next_client(agent, route_id_or_idx)
    return describe_runtime(agent)[agent.llm_no]


def describe_runtime(agent):
    runtime_items = []
    for index, client in enumerate(getattr(agent, "llmclients", [])):
        backend = client.backend
        metadata = getattr(client, "ga_switch_meta", {})
        diagnostics = backend.describe_diagnostics() if hasattr(backend, "describe_diagnostics") else {}
        provider_name = metadata.get("provider_name") or getattr(backend, "name", None)
        backend_class = type(backend).__name__
        last_error_message = diagnostics.get("last_error_message", "")
        runtime_items.append({
            "idx": index,
            "active": index == getattr(agent, "llm_no", 0),
            "source": getattr(agent, "config_source", metadata.get("source", "legacy")),
            "route_id": metadata.get("route_id"),
            "name": metadata.get("route_name") or getattr(backend, "name", ""),
            "route_kind": metadata.get("route_kind", "single"),
            "backend_class": backend_class,
            "backend_kind": metadata.get("backend_kind"),
            "provider_id": metadata.get("provider_id"),
            "provider_name": provider_name,
            "model": getattr(backend, "model", None),
            "api_mode": getattr(backend, "api_mode", None),
            "native_tools": isinstance(client, NativeToolClient) or "Native" in backend_class,
            "member_names": [member.get("name", "") for member in metadata.get("members", [])],
            "active_member_name": diagnostics.get("active_member_name", getattr(backend, "name", None)),
            "last_error_kind": classify_error(
                status_code=diagnostics.get("last_status_code"),
                message=last_error_message,
            ) if last_error_message else None,
            "last_error_message": last_error_message,
            "last_error_at": diagnostics.get("last_error_at"),
            "last_ok_at": diagnostics.get("last_ok_at"),
            "last_status_code": diagnostics.get("last_status_code"),
            "last_latency_ms": diagnostics.get("last_latency_ms"),
            "last_ttfb_ms": diagnostics.get("last_ttfb_ms"),
            "last_switch_reason": diagnostics.get("last_switch_reason", ""),
            "spring_back_seconds": diagnostics.get("spring_back_seconds"),
        })
    return runtime_items


def build_runtime_snapshot(config_snapshot, runtime_items):
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
