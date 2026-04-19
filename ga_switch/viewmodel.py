import json

from .models import is_native_backend_kind


SECTIONS = (
    ("overview", "总览"),
    ("routes", "全部路由"),
    ("providers", "模型服务"),
    ("diagnostics", "诊断记录"),
)


def _bool(value):
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def _int(value, default=0):
    if value in (None, ""):
        return default
    return int(value)


def _float(value, default=0.0):
    if value in (None, ""):
        return default
    return float(value)


def _json(value, default=None):
    if value in (None, ""):
        return {} if default is None else default
    if isinstance(value, dict):
        return value
    return json.loads(value)


def _caption(parts):
    return " · ".join(str(part) for part in parts if part)


def _route_kind_label(kind):
    return "备用链路" if kind == "failover" else "单路由"


def _route_subtitle(route, runtime):
    if route.get("kind") == "single":
        provider = (route.get("provider") or {}).get("name") or "未绑定模型服务"
        return provider
    members = " -> ".join(member.get("name", "") for member in route.get("members", []))
    return members or "未配置备用链路成员"


def _health_tone(last_error_kind, status=None):
    if last_error_kind:
        return "error"
    if status == "healthy":
        return "active"
    if status in ("degraded", "failed"):
        return "warn" if status == "degraded" else "error"
    return "neutral"


def _health_label(last_error_kind, status=None):
    if last_error_kind:
        return f"最近错误：{last_error_kind}"
    if status == "healthy":
        return "状态正常"
    if status == "degraded":
        return "状态波动"
    if status == "failed":
        return "状态异常"
    return "状态未知"


def _route_status_label(route, active=False):
    if active:
        return "当前生效"
    if not route.get("is_enabled", True):
        return "已停用"
    return "待命"


def _overview_actions(has_routes):
    base = [
        {"id": "import_legacy", "label": "导入 mykey", "primary": not has_routes},
        {"id": "create_provider", "label": "新建模型服务", "primary": False},
        {"id": "continue_chat", "label": "继续使用当前模型", "primary": False},
    ]
    if has_routes:
        return [
            {"id": "switch_route", "label": "切换到所选路由", "primary": True},
            {"id": "soft_reload", "label": "软重载", "primary": False},
            {"id": "import_legacy", "label": "导入 mykey", "primary": False},
            {"id": "more_actions", "label": "更多操作", "primary": False},
        ]
    return base


def _route_edit_groups():
    return [
        {
            "id": "basic",
            "label": "基础信息",
            "expanded": True,
            "fields": ["name", "kind", "provider_id", "member_provider_ids", "is_default", "is_enabled"],
        },
        {
            "id": "advanced",
            "label": "高级设置",
            "expanded": False,
            "fields": ["member_order", "max_retries", "base_delay", "spring_back"],
        },
    ]


def _provider_edit_groups():
    return [
        {
            "id": "basic",
            "label": "基础信息",
            "expanded": True,
            "fields": ["name", "backend_kind", "model", "apibase"],
        },
        {
            "id": "advanced",
            "label": "高级设置",
            "expanded": False,
            "fields": ["apikey", "api_mode", "temperature", "max_tokens", "timeout", "read_timeout", "proxy", "extra"],
        },
    ]


def build_ui_viewmodel(snapshot):
    routes = snapshot.get("routes", [])
    providers = snapshot.get("providers", [])
    runtime = snapshot.get("runtime", [])
    events = snapshot.get("events", [])
    runtime_by_route_id = snapshot.get("runtime_by_route_id", {})
    active_summary = dict(snapshot.get("active_route_summary") or {})
    active_runtime = snapshot.get("active_runtime") or next((item for item in runtime if item.get("active")), None) or {}

    summary = {
        "route_id": active_summary.get("route_id") if active_summary.get("route_id") is not None else active_runtime.get("route_id"),
        "route_name": active_summary.get("route_name") or active_runtime.get("name") or "当前模型",
        "route_kind": active_summary.get("route_kind") or active_runtime.get("route_kind") or "single",
        "route_kind_label": _route_kind_label(active_summary.get("route_kind") or active_runtime.get("route_kind") or "single"),
        "provider_name": active_summary.get("provider_name") or active_runtime.get("provider_name") or "未配置模型服务",
        "model": active_summary.get("model") or active_runtime.get("model") or "未指定模型",
        "backend_class": active_summary.get("backend_class") or active_runtime.get("backend_class") or "未指定后端",
        "backend_kind": active_summary.get("backend_kind") or active_runtime.get("backend_kind"),
        "api_mode": active_summary.get("api_mode") or active_runtime.get("api_mode"),
        "native_tools": bool(active_summary.get("native_tools") if active_summary.get("native_tools") is not None else active_runtime.get("native_tools")),
        "active_member_name": active_summary.get("active_member_name") or active_runtime.get("active_member_name"),
        "member_names": list(active_summary.get("member_names") or active_runtime.get("member_names") or []),
        "last_error_kind": active_summary.get("last_error_kind") or active_runtime.get("last_error_kind"),
        "last_error_message": active_summary.get("last_error_message") or active_runtime.get("last_error_message") or "",
        "last_status_code": active_summary.get("last_status_code") or active_runtime.get("last_status_code"),
        "last_switch_reason": active_summary.get("last_switch_reason") or active_runtime.get("last_switch_reason") or "",
        "last_ok_at": active_summary.get("last_ok_at") or active_runtime.get("last_ok_at"),
        "last_error_at": active_summary.get("last_error_at") or active_runtime.get("last_error_at"),
        "headline": active_summary.get("route_name") or active_runtime.get("name") or "当前模型",
        "meta": _caption([
            active_summary.get("provider_name") or active_runtime.get("provider_name"),
            active_summary.get("model") or active_runtime.get("model"),
            active_summary.get("backend_class") or active_runtime.get("backend_class"),
        ]) or "继续使用当前模型",
    }
    summary["health_label"] = _health_label(summary["last_error_kind"])
    summary["health_tone"] = _health_tone(summary["last_error_kind"])

    route_items = []
    for route in routes:
        runtime_item = runtime_by_route_id.get(route["id"], {})
        member_ids = [member["id"] for member in route.get("members", [])]
        active = route["id"] == snapshot.get("active_route_id")
        last_error_kind = runtime_item.get("last_error_kind")
        route_items.append({
            "id": route["id"],
            "name": route["name"],
            "title": route["name"],
            "kind": route["kind"],
            "kind_label": _route_kind_label(route["kind"]),
            "active": active,
            "enabled": bool(route.get("is_enabled", True)),
            "status_label": _route_status_label(route, active=active),
            "is_default": bool(route.get("is_default", False)),
            "provider_id": ((route.get("provider") or {}).get("id")),
            "provider_name": ((route.get("provider") or {}).get("name")),
            "member_provider_ids": member_ids,
            "member_names": [member.get("name", "") for member in route.get("members", [])],
            "subtitle": _route_subtitle(route, runtime_item),
            "model": runtime_item.get("model"),
            "backend_class": runtime_item.get("backend_class"),
            "backend_kind": runtime_item.get("backend_kind"),
            "api_mode": runtime_item.get("api_mode"),
            "native_tools": bool(runtime_item.get("native_tools")),
            "active_member_name": runtime_item.get("active_member_name"),
            "last_error_kind": last_error_kind,
            "last_error_message": runtime_item.get("last_error_message") or "",
            "last_switch_reason": runtime_item.get("last_switch_reason") or "",
            "health_label": _health_label(last_error_kind),
            "health_tone": _health_tone(last_error_kind),
            "config": dict(route.get("config") or {}),
            "edit_groups": _route_edit_groups(),
        })

    provider_items = []
    for provider in providers:
        health = dict(provider.get("health") or {})
        health_status = health.get("status") or "unknown"
        provider_items.append({
            "id": provider["id"],
            "name": provider["name"],
            "title": provider["name"],
            "backend_kind": provider["backend_kind"],
            "is_native": is_native_backend_kind(provider["backend_kind"]),
            "model": provider.get("model") or "",
            "api_mode": provider.get("api_mode") or "chat_completions",
            "subtitle": _caption([provider.get("model"), provider.get("backend_kind"), provider.get("api_mode")]) or "未配置模型 ID",
            "health_status": health_status,
            "health_label": _health_label(None, status=health_status),
            "health_tone": _health_tone(None, status=health_status),
            "latency_ms": health.get("latency_ms"),
            "ttfb_ms": health.get("ttfb_ms"),
            "last_error": health.get("last_error") or "",
            "payload": provider,
            "edit_groups": _provider_edit_groups(),
        })

    event_items = []
    for event in events:
        ok = bool(event.get("ok"))
        tone = "active" if ok else "error"
        event_items.append({
            "id": event["id"],
            "route_id": event.get("route_id"),
            "provider_id": event.get("provider_id"),
            "title": event.get("backend_name") or f"记录 {event['id']}",
            "subtitle": event.get("message") or "没有详细消息",
            "created_at": event.get("created_at") or "",
            "tone": tone,
            "status_code": event.get("status_code"),
            "error_kind": event.get("error_kind"),
            "raw_label": "查看原始详情",
            "payload": event,
        })

    runtime_items = []
    for item in runtime:
        runtime_items.append({
            "id": item.get("route_id") if item.get("route_id") is not None else item.get("idx"),
            "route_id": item.get("route_id"),
            "idx": item.get("idx"),
            "name": item.get("name") or item.get("display_name") or "运行时",
            "title": item.get("name") or item.get("display_name") or "运行时",
            "subtitle": _caption([item.get("provider_name"), item.get("model"), item.get("backend_class")]) or "暂无运行时信息",
            "active": bool(item.get("active")),
            "active_member_name": item.get("active_member_name"),
            "last_error_kind": item.get("last_error_kind"),
            "last_error_message": item.get("last_error_message") or "",
            "payload": item,
        })

    has_routes = bool(routes)
    empty_state = None
    if not has_routes:
        empty_state = {
            "title": "还没有结构化路由",
            "message": "可以先导入 mykey，或者新建模型服务。当前仍可继续使用现有模型。",
            "actions": [
                {"id": "import_legacy", "label": "导入 mykey", "primary": True},
                {"id": "create_provider", "label": "新建模型服务", "primary": False},
                {"id": "continue_chat", "label": "继续使用当前模型", "primary": False},
            ],
        }

    overview = {
        "current_route_card": {
            "title": "当前路由",
            "headline": summary["headline"],
            "subtitle": summary["meta"],
            "status_label": summary["health_label"],
            "status_tone": summary["health_tone"],
            "badges": [
                summary["route_kind_label"],
                summary["active_member_name"] or "",
                "原生工具" if summary["native_tools"] else "文本接口",
            ],
        },
        "health_card": {
            "title": "健康状态",
            "headline": summary["health_label"],
            "detail": summary["last_error_message"] or "最近没有记录到错误。",
            "tone": summary["health_tone"],
        },
        "quick_actions": _overview_actions(has_routes),
        "route_summary_items": route_items[:5],
        "has_routes": has_routes,
    }

    return {
        "sections": [{"id": section_id, "label": label} for section_id, label in SECTIONS],
        "summary": summary,
        "overview": overview,
        "empty_state": empty_state,
        "routes": route_items,
        "providers": provider_items,
        "events": event_items,
        "runtime": runtime_items,
        "stats": {
            "provider_count": len(provider_items),
            "route_count": len(route_items),
            "runtime_count": len(runtime_items),
        },
        "use_structured_config": bool(snapshot.get("use_structured_config")),
    }


def build_provider_payload(values, provider_id=None):
    payload = {
        "name": str(values.get("name", "")).strip(),
        "backend_kind": str(values.get("backend_kind", "oai_text")).strip() or "oai_text",
        "apikey": str(values.get("apikey", "")).strip(),
        "apibase": str(values.get("apibase", "")).strip(),
        "model": str(values.get("model", "")).strip(),
        "api_mode": str(values.get("api_mode", "chat_completions")).strip() or "chat_completions",
        "temperature": _float(values.get("temperature"), 1.0),
        "max_tokens": _int(values.get("max_tokens"), 8192),
        "timeout": _int(values.get("timeout"), 5),
        "read_timeout": _int(values.get("read_timeout"), 30),
        "proxy": str(values.get("proxy", "")).strip() or None,
        "extra": _json(values.get("extra"), default={}),
    }
    if provider_id is not None:
        payload["id"] = provider_id
    return payload


def build_route_payload(values, route_id=None):
    kind = str(values.get("kind", "single")).strip() or "single"
    payload = {
        "name": str(values.get("name", "")).strip(),
        "kind": kind,
        "is_default": _bool(values.get("is_default")),
        "is_enabled": _bool(values.get("is_enabled", True)),
        "provider_id": values.get("provider_id"),
        "member_provider_ids": list(values.get("member_provider_ids") or []),
        "config": {
            "max_retries": _int(values.get("max_retries"), 3),
            "base_delay": _float(values.get("base_delay"), 1.5),
            "spring_back": _int(values.get("spring_back"), 300),
        },
    }
    if kind == "single":
        payload["member_provider_ids"] = []
    else:
        payload["provider_id"] = None
    if route_id is not None:
        payload["id"] = route_id
    return payload
