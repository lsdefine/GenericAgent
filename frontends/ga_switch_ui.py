import json
import os
import sys

import streamlit as st

script_dir = os.path.dirname(__file__)
repo_dir = os.path.abspath(os.path.join(script_dir, ".."))
if repo_dir not in sys.path:
    sys.path.append(repo_dir)

from ga_switch.models import PROVIDER_BACKEND_KINDS, ROUTE_KINDS
from ga_switch.viewmodel import build_ui_viewmodel
from shared_runtime import get_shared_runtime

NAV_ITEMS = [
    ("routes", "Routes", "R"),
    ("providers", "Providers", "P"),
    ("diagnostics", "Diagnostics", "D"),
    ("tests", "Tests", "T"),
    ("runtime", "Runtime", "RT"),
]


def setup_switch_page(page_title="GA Switch Admin"):
    st.set_page_config(page_title=page_title, layout="wide", initial_sidebar_state="collapsed")
    inject_switch_css()


def inject_switch_css():
    st.markdown(
        """
        <style>
        :root {
            --ga-bg: #0b1020;
            --ga-panel: rgba(17, 24, 39, 0.92);
            --ga-panel-2: rgba(15, 23, 42, 0.92);
            --ga-line: rgba(148, 163, 184, 0.18);
            --ga-text: #e5eefc;
            --ga-muted: #93a4bd;
            --ga-accent: #5ea0ff;
            --ga-accent-2: #22c55e;
            --ga-danger: #ef4444;
            --ga-warn: #f59e0b;
        }
        .stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"] {
            background:
                radial-gradient(circle at top right, rgba(96, 165, 250, 0.16), transparent 34%),
                radial-gradient(circle at top left, rgba(34, 197, 94, 0.10), transparent 28%),
                linear-gradient(180deg, #07101f 0%, #0b1020 100%);
            color: var(--ga-text);
        }
        [data-testid="collapsedControl"], [data-testid="stToolbar"], #MainMenu, footer {
            visibility: hidden;
        }
        .block-container {
            padding-top: 1.6rem;
            padding-bottom: 1.5rem;
            max-width: 1500px;
        }
        h1, h2, h3, p, label, [data-testid="stMarkdownContainer"] {
            color: var(--ga-text);
        }
        .ga-shell {
            border: 1px solid var(--ga-line);
            background: linear-gradient(180deg, rgba(15, 23, 42, 0.82), rgba(15, 23, 42, 0.68));
            border-radius: 28px;
            padding: 1rem 1.1rem;
            box-shadow: 0 24px 80px rgba(0, 0, 0, 0.28);
        }
        .ga-hero {
            border: 1px solid var(--ga-line);
            background: linear-gradient(135deg, rgba(17, 24, 39, 0.94), rgba(23, 37, 84, 0.86));
            border-radius: 26px;
            padding: 1.1rem 1.25rem;
            margin-bottom: 1rem;
        }
        .ga-hero-title {
            font-size: 2rem;
            font-weight: 700;
            letter-spacing: -0.03em;
            margin: 0;
        }
        .ga-hero-subtitle {
            color: var(--ga-muted);
            margin: 0.35rem 0 0 0;
            font-size: 0.98rem;
        }
        .ga-chip {
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            border-radius: 999px;
            padding: 0.26rem 0.7rem;
            font-size: 0.78rem;
            font-weight: 600;
            border: 1px solid rgba(255, 255, 255, 0.08);
            margin-right: 0.4rem;
            margin-top: 0.35rem;
            color: #eef4ff;
            background: rgba(255, 255, 255, 0.06);
        }
        .ga-chip.active { background: rgba(34, 197, 94, 0.18); color: #b6f3cc; }
        .ga-chip.warn { background: rgba(245, 158, 11, 0.18); color: #fde3a7; }
        .ga-chip.error { background: rgba(239, 68, 68, 0.18); color: #fecaca; }
        .ga-chip.blue { background: rgba(96, 165, 250, 0.18); color: #cfe1ff; }
        .ga-panel-title {
            margin: 0 0 0.2rem 0;
            font-size: 0.88rem;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: var(--ga-muted);
        }
        .ga-summary-card {
            border: 1px solid var(--ga-line);
            background: linear-gradient(180deg, rgba(17, 24, 39, 0.95), rgba(15, 23, 42, 0.90));
            border-radius: 20px;
            padding: 0.9rem 1rem;
            margin-bottom: 0.8rem;
        }
        .ga-summary-title {
            font-size: 1.05rem;
            font-weight: 700;
            margin: 0;
        }
        .ga-summary-subtitle {
            color: var(--ga-muted);
            margin: 0.25rem 0 0 0;
            font-size: 0.86rem;
        }
        div[data-testid="stVerticalBlockBorderWrapper"] {
            border-radius: 18px;
            border-color: var(--ga-line);
            background: linear-gradient(180deg, rgba(17, 24, 39, 0.92), rgba(15, 23, 42, 0.86));
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.02);
        }
        div[data-testid="stButton"] > button,
        div[data-testid="stFormSubmitButton"] > button {
            border-radius: 14px;
            border: 1px solid rgba(148, 163, 184, 0.18);
            background: linear-gradient(180deg, rgba(30, 41, 59, 0.92), rgba(15, 23, 42, 0.98));
            color: #f8fbff;
        }
        div[data-testid="stButton"] > button[kind="primary"],
        div[data-testid="stFormSubmitButton"] > button[kind="primary"] {
            background: linear-gradient(180deg, #3b82f6, #2563eb);
            border-color: rgba(147, 197, 253, 0.34);
        }
        .stSelectbox [data-baseweb="select"] > div,
        .stTextInput input,
        .stTextArea textarea,
        .stNumberInput input {
            border-radius: 14px !important;
            background: rgba(15, 23, 42, 0.88) !important;
            color: #eef4ff !important;
            border-color: rgba(148, 163, 184, 0.2) !important;
        }
        .stDataFrame {
            border-radius: 18px;
            overflow: hidden;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _chip(text, tone=""):
    klass = f"ga-chip {tone}".strip()
    return f'<span class="{klass}">{text}</span>'


def _route_caption(route, runtime):
    if route["kind"] == "single":
        primary = (route["provider"] or {}).get("name") or "No provider"
    else:
        primary = " -> ".join(member["name"] for member in route["members"]) or "No members"
    runtime_bits = []
    if runtime:
        runtime_bits.append(runtime.get("backend_class") or "")
        runtime_bits.append(runtime.get("model") or "")
    runtime_text = " | ".join(bit for bit in runtime_bits if bit)
    return primary if not runtime_text else f"{primary} | {runtime_text}"


def _provider_caption(provider):
    bits = [
        provider.get("backend_kind"),
        provider.get("model"),
        provider.get("api_mode"),
        provider.get("health", {}).get("status"),
    ]
    return " | ".join(bit for bit in bits if bit)


def _ensure_state(snapshot):
    if "ga_admin_section" not in st.session_state:
        st.session_state.ga_admin_section = "routes"
    if snapshot["routes"] and st.session_state.get("ga_admin_selected_route") not in snapshot["routes_by_id"]:
        st.session_state.ga_admin_selected_route = snapshot["routes"][0]["id"]
    if snapshot["providers"] and st.session_state.get("ga_admin_selected_provider") not in snapshot["providers_by_id"]:
        st.session_state.ga_admin_selected_provider = snapshot["providers"][0]["id"]
    if snapshot["events"] and st.session_state.get("ga_admin_selected_event") not in {event["id"] for event in snapshot["events"]}:
        st.session_state.ga_admin_selected_event = snapshot["events"][0]["id"]


def _nav_button(section_key, label, icon):
    current = st.session_state.ga_admin_section == section_key
    if st.button(f"{icon}  {label}", key=f"ga_nav_{section_key}", use_container_width=True, type="primary" if current else "secondary"):
        st.session_state.ga_admin_section = section_key
        st.rerun()


def _render_left_nav(snapshot):
    with st.container(border=True):
        st.markdown("##### Workspace")
        for section_key, label, icon in NAV_ITEMS:
            _nav_button(section_key, label, icon)
        st.markdown("---")
        active = snapshot["active_route_summary"]
        st.markdown(
            f"""
            <div class="ga-summary-card">
              <p class="ga-panel-title">Current Route</p>
              <p class="ga-summary-title">{active.get("route_name") or "No active route"}</p>
              <p class="ga-summary-subtitle">{active.get("provider_name") or "No provider"} | {active.get("model") or "No model"}</p>
              {_chip(active.get("route_kind") or "unknown", "blue")}
              {_chip("native tools" if active.get("native_tools") else "text tools", "active" if active.get("native_tools") else "")}
            </div>
            """,
            unsafe_allow_html=True,
        )
        if hasattr(st, "page_link"):
            st.page_link("stapp.py", label="Open Chat", icon="💬")
        else:
            st.caption("Chat page lives in stapp.py")


def _render_routes_list(snapshot):
    runtime_by_route = snapshot["runtime_by_route_id"]
    for route in snapshot["routes"]:
        runtime = runtime_by_route.get(route["id"])
        with st.container(border=True):
            cols = st.columns([5, 1.2])
            cols[0].markdown(
                f"""
                <div class="ga-summary-card" style="margin-bottom:0;padding:0.75rem 0.9rem;">
                  <p class="ga-summary-title">{route['name']}</p>
                  <p class="ga-summary-subtitle">{_route_caption(route, runtime)}</p>
                  {_chip('active', 'active') if route['active'] else ''}
                  {_chip(route['kind'], 'blue')}
                  {_chip('default') if route['is_default'] else ''}
                  {_chip('disabled', 'warn') if not route['is_enabled'] else ''}
                </div>
                """,
                unsafe_allow_html=True,
            )
            if cols[1].button("Open", key=f"ga_route_open_{route['id']}", use_container_width=True, type="primary" if st.session_state.ga_admin_selected_route == route["id"] else "secondary"):
                st.session_state.ga_admin_selected_route = route["id"]
                st.session_state.ga_admin_section = "routes"
                st.rerun()


def _render_providers_list(snapshot):
    for provider in snapshot["providers"]:
        with st.container(border=True):
            cols = st.columns([5, 1.2])
            cols[0].markdown(
                f"""
                <div class="ga-summary-card" style="margin-bottom:0;padding:0.75rem 0.9rem;">
                  <p class="ga-summary-title">{provider['name']}</p>
                  <p class="ga-summary-subtitle">{_provider_caption(provider)}</p>
                  {_chip('native', 'active') if provider['is_native'] else _chip('text')}
                  {_chip(provider['health']['status'] or 'unknown', 'active' if provider['health']['status'] == 'healthy' else 'warn' if provider['health']['status'] == 'degraded' else 'error' if provider['health']['status'] == 'failed' else '')}
                </div>
                """,
                unsafe_allow_html=True,
            )
            if cols[1].button("Open", key=f"ga_provider_open_{provider['id']}", use_container_width=True, type="primary" if st.session_state.ga_admin_selected_provider == provider["id"] else "secondary"):
                st.session_state.ga_admin_selected_provider = provider["id"]
                st.session_state.ga_admin_section = "providers"
                st.rerun()


def _render_events_list(snapshot):
    for event in snapshot["recent_events"]:
        title = event.get("backend_name") or f"Event {event['id']}"
        tone = "error" if not event.get("ok") else "active"
        subtitle = f"{event['created_at']} | {event.get('error_kind') or 'ok'} | {event.get('message') or ''}"
        with st.container(border=True):
            cols = st.columns([5, 1.2])
            cols[0].markdown(
                f"""
                <div class="ga-summary-card" style="margin-bottom:0;padding:0.75rem 0.9rem;">
                  <p class="ga-summary-title">{title}</p>
                  <p class="ga-summary-subtitle">{subtitle[:160]}</p>
                  {_chip('ok', 'active') if event.get('ok') else _chip(event.get('error_kind') or 'error', tone)}
                </div>
                """,
                unsafe_allow_html=True,
            )
            if cols[1].button("Open", key=f"ga_event_open_{event['id']}", use_container_width=True, type="primary" if st.session_state.ga_admin_selected_event == event["id"] else "secondary"):
                st.session_state.ga_admin_selected_event = event["id"]
                st.session_state.ga_admin_section = "diagnostics"
                st.rerun()


def _render_runtime_list(snapshot):
    for item in snapshot["runtime"]:
        with st.container(border=True):
            cols = st.columns([5, 1.2])
            cols[0].markdown(
                f"""
                <div class="ga-summary-card" style="margin-bottom:0;padding:0.75rem 0.9rem;">
                  <p class="ga-summary-title">{item['name']}</p>
                  <p class="ga-summary-subtitle">{item.get('provider_name') or 'No provider'} | {item.get('model') or 'No model'} | {item.get('backend_class') or ''}</p>
                  {_chip('active', 'active') if item.get('active') else ''}
                  {_chip(item.get('route_kind') or 'single', 'blue')}
                  {_chip(item.get('active_member_name') or 'no active member')}
                </div>
                """,
                unsafe_allow_html=True,
            )
            if cols[1].button("Focus", key=f"ga_runtime_open_{item['idx']}", use_container_width=True):
                if item.get("route_id") is not None:
                    st.session_state.ga_admin_selected_route = item["route_id"]
                    st.session_state.ga_admin_section = "routes"
                st.rerun()


def _render_middle_panel(snapshot):
    section = st.session_state.ga_admin_section
    st.markdown(
        f"""
        <div class="ga-summary-card">
          <p class="ga-panel-title">Current Module</p>
          <p class="ga-summary-title">{section.title()}</p>
          <p class="ga-summary-subtitle">List on the left, details and actions on the right.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if section == "routes":
        _render_routes_list(snapshot)
    elif section == "providers":
        _render_providers_list(snapshot)
    elif section == "diagnostics":
        _render_events_list(snapshot)
    elif section == "tests":
        _render_providers_list(snapshot)
    else:
        _render_runtime_list(snapshot)


def _selected_route(snapshot):
    return snapshot["routes_by_id"].get(st.session_state.get("ga_admin_selected_route"))


def _selected_provider(snapshot):
    return snapshot["providers_by_id"].get(st.session_state.get("ga_admin_selected_provider"))


def _selected_event(snapshot):
    return next((event for event in snapshot["events"] if event["id"] == st.session_state.get("ga_admin_selected_event")), None)


def _render_route_detail(service, agent, snapshot):
    route = _selected_route(snapshot)
    if route is None:
        st.info("No route selected.")
        return
    runtime = snapshot["runtime_by_route_id"].get(route["id"])
    st.markdown(
        f"""
        <div class="ga-summary-card">
          <p class="ga-panel-title">Route Detail</p>
          <p class="ga-summary-title">{route['name']}</p>
          <p class="ga-summary-subtitle">{_route_caption(route, runtime)}</p>
          {_chip('active', 'active') if route['active'] else ''}
          {_chip(route['kind'], 'blue')}
          {_chip(runtime.get('backend_class') if runtime else 'not mounted')}
          {_chip(runtime.get('active_member_name') or 'no active member', 'warn' if route['kind'] == 'failover' else '') if runtime else ''}
        </div>
        """,
        unsafe_allow_html=True,
    )
    action_cols = st.columns([1, 1, 1])
    if action_cols[0].button("Activate route", key=f"ga_activate_route_{route['id']}", use_container_width=True, type="primary"):
        try:
            agent.set_active_route(route["id"])
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
    if action_cols[1].button("Soft reload", key=f"ga_reload_route_{route['id']}", use_container_width=True):
        try:
            agent.reload_llm_config(preserve_history=True)
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
    if action_cols[2].button("Delete route", key=f"ga_delete_route_{route['id']}", use_container_width=True):
        try:
            service.delete_route(route["id"])
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

    provider_options = {provider["id"]: provider["name"] for provider in snapshot["providers"]}
    with st.form("ga_route_form"):
        form_cols = st.columns(4)
        route_name = form_cols[0].text_input("Route name", value=route.get("name", ""))
        route_kind = form_cols[1].selectbox("Route kind", ROUTE_KINDS, index=ROUTE_KINDS.index(route.get("kind", "single")))
        is_default = form_cols[2].checkbox("Default route", value=bool(route.get("is_default", False)))
        is_enabled = form_cols[3].checkbox("Enabled", value=bool(route.get("is_enabled", True)))
        if route_kind == "single":
            provider_index = next((idx for idx, provider in enumerate(snapshot["providers"]) if provider["id"] == ((route.get("provider") or {}).get("id"))), 0) if snapshot["providers"] else 0
            provider_id = st.selectbox("Provider", options=[provider["id"] for provider in snapshot["providers"]] or [0], index=provider_index, format_func=lambda pid: provider_options.get(pid, "No providers"), disabled=not snapshot["providers"])
            member_provider_ids = []
        else:
            provider_id = None
            member_provider_ids = st.multiselect("Failover members", options=[provider["id"] for provider in snapshot["providers"]], default=route.get("member_provider_ids", []), format_func=lambda pid: provider_options.get(pid, str(pid)))
        form_cols = st.columns(3)
        mixin_retries = form_cols[0].number_input("Failover max retries", value=int((route.get("config") or {}).get("max_retries", 3)), min_value=0)
        mixin_delay = form_cols[1].number_input("Base delay", value=float((route.get("config") or {}).get("base_delay", 1.5)), min_value=0.0)
        spring_back = form_cols[2].number_input("Spring back seconds", value=int((route.get("config") or {}).get("spring_back", 300)), min_value=0)
        if st.form_submit_button("Save route", use_container_width=True, type="primary"):
            try:
                service.upsert_route({
                    "id": route["id"],
                    "name": route_name.strip(),
                    "kind": route_kind,
                    "provider_id": provider_id,
                    "member_provider_ids": member_provider_ids,
                    "is_default": is_default,
                    "is_enabled": is_enabled,
                    "config": {"max_retries": int(mixin_retries), "base_delay": float(mixin_delay), "spring_back": int(spring_back)},
                })
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    with st.form("ga_route_create_form"):
        st.markdown("##### Create Route")
        form_cols = st.columns(3)
        create_name = form_cols[0].text_input("New route name", value="")
        create_kind = form_cols[1].selectbox("New route kind", ROUTE_KINDS, index=0, key="ga_create_route_kind")
        create_default = form_cols[2].checkbox("Set as default", value=False, key="ga_create_route_default")
        if create_kind == "single":
            create_provider_id = st.selectbox("Provider for new route", options=[provider["id"] for provider in snapshot["providers"]] or [0], format_func=lambda pid: provider_options.get(pid, "No providers"), disabled=not snapshot["providers"], key="ga_create_route_provider")
            create_members = []
        else:
            create_provider_id = None
            create_members = st.multiselect("Members for new failover route", options=[provider["id"] for provider in snapshot["providers"]], format_func=lambda pid: provider_options.get(pid, str(pid)), key="ga_create_route_members")
        if st.form_submit_button("Create route", use_container_width=True):
            if create_name.strip():
                try:
                    service.upsert_route({
                        "name": create_name.strip(),
                        "kind": create_kind,
                        "provider_id": create_provider_id,
                        "member_provider_ids": create_members,
                        "is_default": create_default,
                        "is_enabled": True,
                        "config": {"max_retries": 3, "base_delay": 1.5, "spring_back": 300},
                    })
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))


def _render_provider_detail(service, snapshot):
    provider = _selected_provider(snapshot)
    if provider is None:
        st.info("No provider selected.")
        return
    health = provider["health"]
    st.markdown(
        f"""
        <div class="ga-summary-card">
          <p class="ga-panel-title">Provider Detail</p>
          <p class="ga-summary-title">{provider['name']}</p>
          <p class="ga-summary-subtitle">{_provider_caption(provider)}</p>
          {_chip(health.get('status') or 'unknown', 'active' if health.get('status') == 'healthy' else 'warn' if health.get('status') == 'degraded' else 'error' if health.get('status') == 'failed' else '')}
          {_chip('native', 'active') if provider['is_native'] else _chip('text')}
          {_chip(f"latency {health.get('latency_ms') or '-'} ms")}
        </div>
        """,
        unsafe_allow_html=True,
    )
    action_cols = st.columns([1, 1, 1])
    if action_cols[0].button("Run model test", key=f"ga_test_provider_{provider['id']}", use_container_width=True, type="primary"):
        try:
            st.session_state.ga_switch_last_test_result = service.run_model_test(provider["id"])
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
    if action_cols[1].button("Delete provider", key=f"ga_delete_provider_{provider['id']}", use_container_width=True):
        try:
            service.delete_provider(provider["id"])
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
    if action_cols[2].button("Copy as legacy JSON", key=f"ga_export_provider_{provider['id']}", use_container_width=True):
        st.session_state.ga_switch_export_preview = json.dumps(service.export_legacy_config(), ensure_ascii=False, indent=2)

    with st.form("ga_provider_form"):
        form_cols = st.columns(3)
        name = form_cols[0].text_input("Name", value=provider.get("name", ""))
        backend_kind = form_cols[1].selectbox("Backend kind", PROVIDER_BACKEND_KINDS, index=PROVIDER_BACKEND_KINDS.index(provider.get("backend_kind", "oai_text")))
        model = form_cols[2].text_input("Model", value=provider.get("model", ""))
        form_cols = st.columns(3)
        apikey = form_cols[0].text_input("API key", value=provider.get("apikey", ""), type="password")
        apibase = form_cols[1].text_input("API base", value=provider.get("apibase", ""))
        api_mode = form_cols[2].selectbox("API mode", ["chat_completions", "responses"], index=["chat_completions", "responses"].index(provider.get("api_mode", "chat_completions")))
        form_cols = st.columns(4)
        temperature = form_cols[0].number_input("Temperature", value=float(provider.get("temperature", 1.0)))
        max_tokens = form_cols[1].number_input("Max tokens", value=int(provider.get("max_tokens", 8192)), min_value=1)
        timeout = form_cols[2].number_input("Connect timeout", value=int(provider.get("timeout", 5)), min_value=1)
        read_timeout = form_cols[3].number_input("Read timeout", value=int(provider.get("read_timeout", 30)), min_value=1)
        proxy = st.text_input("Proxy", value=provider.get("proxy", "") or "")
        extra_json = st.text_area("Extra JSON", value=json.dumps(provider.get("extra", {}), ensure_ascii=False, indent=2), height=120)
        if st.form_submit_button("Save provider", use_container_width=True, type="primary"):
            try:
                service.upsert_provider({
                    "id": provider["id"],
                    "name": name.strip(),
                    "backend_kind": backend_kind,
                    "apikey": apikey.strip(),
                    "apibase": apibase.strip(),
                    "model": model.strip(),
                    "api_mode": api_mode,
                    "temperature": float(temperature),
                    "max_tokens": int(max_tokens),
                    "timeout": int(timeout),
                    "read_timeout": int(read_timeout),
                    "proxy": proxy.strip() or None,
                    "extra": json.loads(extra_json or "{}"),
                })
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    with st.form("ga_provider_create_form"):
        st.markdown("##### Create Provider")
        form_cols = st.columns(3)
        new_name = form_cols[0].text_input("New provider name", value="")
        new_kind = form_cols[1].selectbox("New backend kind", PROVIDER_BACKEND_KINDS, index=PROVIDER_BACKEND_KINDS.index("oai_text"), key="ga_new_provider_kind")
        new_model = form_cols[2].text_input("New model", value="", key="ga_new_provider_model")
        form_cols = st.columns(2)
        new_key = form_cols[0].text_input("API key", value="", type="password", key="ga_new_provider_key")
        new_base = form_cols[1].text_input("API base", value="", key="ga_new_provider_base")
        if st.form_submit_button("Create provider", use_container_width=True):
            if new_name.strip() and new_key.strip() and new_base.strip():
                try:
                    service.upsert_provider({
                        "name": new_name.strip(),
                        "backend_kind": new_kind,
                        "apikey": new_key.strip(),
                        "apibase": new_base.strip(),
                        "model": new_model.strip(),
                    })
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

    if st.session_state.get("ga_switch_last_test_result"):
        st.markdown("##### Last Test Result")
        st.json(st.session_state["ga_switch_last_test_result"])
    if st.session_state.get("ga_switch_export_preview"):
        st.markdown("##### Legacy Export Preview")
        st.code(st.session_state["ga_switch_export_preview"], language="json")


def _render_diagnostics_detail(snapshot):
    event = _selected_event(snapshot)
    if event is None:
        st.info("No diagnostic event selected.")
        return
    st.markdown(
        f"""
        <div class="ga-summary-card">
          <p class="ga-panel-title">Diagnostic Event</p>
          <p class="ga-summary-title">{event.get('backend_name') or ('Event ' + str(event['id']))}</p>
          <p class="ga-summary-subtitle">{event.get('message') or 'No message'}</p>
          {_chip('ok', 'active') if event.get('ok') else _chip(event.get('error_kind') or 'error', 'error')}
          {_chip(str(event.get('status_code') or '-'))}
          {_chip(event.get('created_at') or '')}
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.json(event)


def _render_runtime_detail(service, agent, snapshot):
    active = snapshot["active_route_summary"]
    st.markdown(
        f"""
        <div class="ga-summary-card">
          <p class="ga-panel-title">Runtime</p>
          <p class="ga-summary-title">{active.get('route_name') or 'No active route'}</p>
          <p class="ga-summary-subtitle">{active.get('provider_name') or 'No provider'} | {active.get('model') or 'No model'} | {active.get('backend_class') or 'No backend'}</p>
          {_chip(active.get('route_kind') or 'unknown', 'blue')}
          {_chip(active.get('active_member_name') or 'no active member')}
          {_chip(active.get('last_error_kind') or 'healthy', 'error' if active.get('last_error_kind') else 'active')}
        </div>
        """,
        unsafe_allow_html=True,
    )
    control_cols = st.columns([1, 1, 1, 1])
    structured_value = control_cols[0].checkbox("Use structured config", value=snapshot["use_structured_config"])
    import_path = control_cols[1].text_input("Import mykey path", value="")
    preserve_history = control_cols[2].checkbox("Preserve history on reload", value=True)
    activate_options = [route["id"] for route in snapshot["routes"]] or [0]
    activate_route_id = control_cols[3].selectbox("Activate route", options=activate_options, format_func=lambda rid: snapshot["routes_by_id"].get(rid, {}).get("name", "No routes"), disabled=not snapshot["routes"])

    action_cols = st.columns([1, 1, 1, 1])
    if action_cols[0].button("Apply mode", use_container_width=True):
        try:
            service.set_structured_config_enabled(structured_value)
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
    if action_cols[1].button("Import legacy mykey", use_container_width=True):
        try:
            service.import_legacy_mykey(import_path or None)
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
    if action_cols[2].button("Activate selected route", use_container_width=True):
        if snapshot["routes"]:
            try:
                agent.set_active_route(activate_route_id)
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    if action_cols[3].button("Soft reload runtime", use_container_width=True, type="primary"):
        try:
            agent.reload_llm_config(preserve_history=preserve_history)
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
    st.dataframe(snapshot["runtime"], use_container_width=True, hide_index=True)


def _render_right_panel(service, agent, snapshot):
    section = st.session_state.ga_admin_section
    if section == "routes":
        _render_route_detail(service, agent, snapshot)
    elif section == "providers":
        _render_provider_detail(service, snapshot)
    elif section == "diagnostics":
        _render_diagnostics_detail(snapshot)
    elif section == "tests":
        _render_provider_detail(service, snapshot)
    else:
        _render_runtime_detail(service, agent, snapshot)


def render_admin_page():
    service, agent = get_shared_runtime()
    if agent.llmclient is None:
        st.error("No LLM routes are available. Configure mykey.py or import structured routes first.")
        st.stop()
    snapshot = service.get_ui_snapshot(agent)
    viewmodel = build_ui_viewmodel(snapshot)
    _ensure_state(snapshot)
    st.markdown(
        f"""
        <div class="ga-hero">
          <p class="ga-hero-title">{viewmodel['summary']['headline'] or 'GA Switch'}</p>
          <p class="ga-hero-subtitle">Streamlit workbench shaped after cc-switch: route center, diagnostics, tests, and chat linkage in one place.</p>
          {_chip(str(viewmodel['stats']['provider_count']) + ' providers', 'blue')}
          {_chip(str(viewmodel['stats']['route_count']) + ' routes')}
          {_chip('structured config', 'active' if viewmodel['use_structured_config'] else 'warn')}
        </div>
        """,
        unsafe_allow_html=True,
    )
    left, middle, right = st.columns([0.9, 1.45, 2.05], gap="large")
    with left:
        _render_left_nav(snapshot)
    with middle:
        _render_middle_panel(snapshot)
    with right:
        _render_right_panel(service, agent, snapshot)
