import json
import os
import sqlite3

from .diagnostics import utcnow_iso
from .models import PROVIDER_BACKEND_KINDS, ROUTE_KINDS, backend_family, is_native_backend_kind


class GASwitchStore:
    def __init__(self, db_path):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._init_db()
        self._ensure_default_test_configs()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @staticmethod
    def _loads(payload, default):
        if not payload:
            return default
        try:
            return json.loads(payload)
        except Exception:
            return default

    @staticmethod
    def _dumps(payload):
        return json.dumps(payload or {}, ensure_ascii=False, separators=(",", ":"))

    def _row_to_provider(self, row, health_by_id):
        if row is None:
            return None
        provider = dict(row)
        provider["extra"] = self._loads(provider.pop("extra_json", None), {})
        provider["stream"] = bool(provider.get("stream", 1))
        provider["is_enabled"] = bool(provider.get("is_enabled", 1))
        provider["is_native"] = is_native_backend_kind(provider["backend_kind"])
        provider["backend_family"] = backend_family(provider["backend_kind"])
        provider["health"] = health_by_id.get(provider["id"], {
            "provider_id": provider["id"],
            "status": "unknown",
            "latency_ms": None,
            "ttfb_ms": None,
            "last_checked_at": None,
            "last_error": "",
        })
        return provider

    def _health_map(self, conn):
        rows = conn.execute("SELECT * FROM provider_health").fetchall()
        return {row["provider_id"]: dict(row) for row in rows}

    def _init_db(self):
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS providers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    backend_kind TEXT NOT NULL,
                    apikey TEXT NOT NULL,
                    apibase TEXT NOT NULL,
                    model TEXT,
                    api_mode TEXT DEFAULT 'chat_completions',
                    temperature REAL DEFAULT 1.0,
                    max_tokens INTEGER DEFAULT 8192,
                    context_win INTEGER DEFAULT 24000,
                    proxy TEXT,
                    timeout INTEGER DEFAULT 5,
                    read_timeout INTEGER DEFAULT 30,
                    max_retries INTEGER DEFAULT 1,
                    reasoning_effort TEXT,
                    thinking_type TEXT,
                    thinking_budget_tokens INTEGER,
                    stream INTEGER DEFAULT 1,
                    is_enabled INTEGER DEFAULT 1,
                    extra_json TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS routes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    kind TEXT NOT NULL,
                    provider_id INTEGER,
                    is_enabled INTEGER DEFAULT 1,
                    is_default INTEGER DEFAULT 0,
                    config_json TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(provider_id) REFERENCES providers(id)
                );
                CREATE TABLE IF NOT EXISTS route_members (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    route_id INTEGER NOT NULL,
                    provider_id INTEGER NOT NULL,
                    position INTEGER NOT NULL,
                    FOREIGN KEY(route_id) REFERENCES routes(id) ON DELETE CASCADE,
                    FOREIGN KEY(provider_id) REFERENCES providers(id),
                    UNIQUE(route_id, position)
                );
                CREATE TABLE IF NOT EXISTS provider_health (
                    provider_id INTEGER PRIMARY KEY,
                    status TEXT NOT NULL,
                    latency_ms INTEGER,
                    ttfb_ms INTEGER,
                    last_checked_at TEXT,
                    last_error TEXT,
                    FOREIGN KEY(provider_id) REFERENCES providers(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS model_test_config (
                    backend_family TEXT PRIMARY KEY,
                    test_model TEXT,
                    api_mode TEXT,
                    reasoning_effort TEXT,
                    prompt TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS diagnostic_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider_id INTEGER,
                    route_id INTEGER,
                    backend_name TEXT,
                    ok INTEGER NOT NULL DEFAULT 0,
                    error_kind TEXT,
                    message TEXT,
                    status_code INTEGER,
                    created_at TEXT NOT NULL,
                    extra_json TEXT DEFAULT '{}',
                    FOREIGN KEY(provider_id) REFERENCES providers(id) ON DELETE SET NULL,
                    FOREIGN KEY(route_id) REFERENCES routes(id) ON DELETE SET NULL
                );
                """
            )

    def _ensure_default_test_configs(self):
        defaults = {
            "claude": {
                "test_model": "claude-3-5-haiku-latest",
                "api_mode": "chat_completions",
                "reasoning_effort": None,
                "prompt": "Reply with exactly: pong",
            },
            "oai": {
                "test_model": "gpt-4.1-mini",
                "api_mode": "chat_completions",
                "reasoning_effort": "low",
                "prompt": "Reply with exactly: pong",
            },
        }
        with self._connect() as conn:
            for family, payload in defaults.items():
                conn.execute(
                    """
                    INSERT INTO model_test_config (backend_family, test_model, api_mode, reasoning_effort, prompt)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(backend_family) DO NOTHING
                    """,
                    (family, payload["test_model"], payload["api_mode"], payload["reasoning_effort"], payload["prompt"]),
                )

    def get_setting(self, key, default=None):
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except Exception:
            return row["value"]

    def set_setting(self, key, value):
        payload = json.dumps(value, ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO app_settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, payload),
            )

    def list_providers(self, enabled_only=False):
        sql = "SELECT * FROM providers"
        if enabled_only:
            sql += " WHERE is_enabled = 1"
        sql += " ORDER BY name COLLATE NOCASE"
        with self._connect() as conn:
            health_by_id = self._health_map(conn)
            rows = conn.execute(sql).fetchall()
        return [self._row_to_provider(row, health_by_id) for row in rows]

    def get_provider(self, provider_id):
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM providers WHERE id = ?", (provider_id,)).fetchone()
            return self._row_to_provider(row, self._health_map(conn))

    def get_provider_by_name(self, name):
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM providers WHERE name = ?", (name,)).fetchone()
            return self._row_to_provider(row, self._health_map(conn))

    def upsert_provider(self, provider):
        backend_kind = str(provider.get("backend_kind") or "").strip()
        if backend_kind not in PROVIDER_BACKEND_KINDS:
            raise ValueError(f"Unsupported backend_kind: {backend_kind}")
        name = str(provider.get("name") or "").strip()
        apikey = str(provider.get("apikey") or "").strip()
        apibase = str(provider.get("apibase") or "").strip()
        if not name or not apikey or not apibase:
            raise ValueError("Provider requires name, apikey and apibase.")
        now = utcnow_iso()
        payload = (
            name,
            backend_kind,
            apikey,
            apibase.rstrip("/"),
            provider.get("model") or "",
            provider.get("api_mode") or "chat_completions",
            float(provider.get("temperature", 1.0)),
            int(provider.get("max_tokens", 8192)),
            int(provider.get("context_win", 24000)),
            provider.get("proxy"),
            int(provider.get("timeout", 5)),
            int(provider.get("read_timeout", 30)),
            int(provider.get("max_retries", 1)),
            provider.get("reasoning_effort"),
            provider.get("thinking_type"),
            provider.get("thinking_budget_tokens"),
            1 if provider.get("stream", True) else 0,
            1 if provider.get("is_enabled", True) else 0,
            self._dumps(provider.get("extra")),
            now,
            now,
        )
        with self._connect() as conn:
            if provider.get("id"):
                conn.execute(
                    """
                    UPDATE providers
                    SET name=?, backend_kind=?, apikey=?, apibase=?, model=?, api_mode=?, temperature=?, max_tokens=?,
                        context_win=?, proxy=?, timeout=?, read_timeout=?, max_retries=?, reasoning_effort=?,
                        thinking_type=?, thinking_budget_tokens=?, stream=?, is_enabled=?, extra_json=?, updated_at=?
                    WHERE id = ?
                    """,
                    payload[:19] + (now, int(provider["id"])),
                )
                provider_id = int(provider["id"])
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO providers
                    (name, backend_kind, apikey, apibase, model, api_mode, temperature, max_tokens, context_win,
                     proxy, timeout, read_timeout, max_retries, reasoning_effort, thinking_type, thinking_budget_tokens,
                     stream, is_enabled, extra_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    payload,
                )
                provider_id = int(cursor.lastrowid)
            conn.execute(
                """
                INSERT INTO provider_health (provider_id, status, latency_ms, ttfb_ms, last_checked_at, last_error)
                VALUES (?, 'unknown', NULL, NULL, NULL, '')
                ON CONFLICT(provider_id) DO NOTHING
                """,
                (provider_id,),
            )
        return self.get_provider(provider_id)

    def delete_provider(self, provider_id):
        with self._connect() as conn:
            ref = conn.execute(
                """
                SELECT routes.name FROM routes
                LEFT JOIN route_members ON route_members.route_id = routes.id
                WHERE routes.provider_id = ? OR route_members.provider_id = ?
                LIMIT 1
                """,
                (provider_id, provider_id),
            ).fetchone()
            if ref:
                raise ValueError(f"Provider is still used by route {ref['name']}.")
            conn.execute("DELETE FROM providers WHERE id = ?", (provider_id,))

    def list_routes(self, enabled_only=False):
        sql = "SELECT * FROM routes"
        if enabled_only:
            sql += " WHERE is_enabled = 1"
        sql += " ORDER BY is_default DESC, id ASC"
        with self._connect() as conn:
            routes = [dict(row) for row in conn.execute(sql).fetchall()]
            providers = {provider["id"]: provider for provider in self.list_providers(enabled_only=False)}
            member_rows = conn.execute(
                """
                SELECT route_id, provider_id, position
                FROM route_members
                ORDER BY route_id ASC, position ASC
                """
            ).fetchall()
            active_route_id = self.get_setting("active_route_id")
        members_by_route = {}
        for row in member_rows:
            members_by_route.setdefault(row["route_id"], []).append(providers.get(row["provider_id"]))
        result = []
        for route in routes:
            route["config"] = self._loads(route.pop("config_json", None), {})
            route["is_enabled"] = bool(route.get("is_enabled", 1))
            route["is_default"] = bool(route.get("is_default", 0))
            route["provider"] = providers.get(route.get("provider_id"))
            route["members"] = [member for member in members_by_route.get(route["id"], []) if member]
            route["member_provider_ids"] = [member["id"] for member in route["members"]]
            route["active"] = active_route_id == route["id"]
            result.append(route)
        return result

    def get_route(self, route_id):
        return next((route for route in self.list_routes(enabled_only=False) if route["id"] == route_id), None)

    def _ensure_route_defaults(self, conn, route_id=None, make_default=False):
        any_default = conn.execute("SELECT id FROM routes WHERE is_default = 1 LIMIT 1").fetchone()
        if make_default or not any_default:
            conn.execute("UPDATE routes SET is_default = 0")
            if route_id:
                conn.execute("UPDATE routes SET is_default = 1 WHERE id = ?", (route_id,))

    def _validate_failover_members(self, providers):
        if len(providers) < 2:
            raise ValueError("Failover route requires at least two providers.")
        native_groups = {is_native_backend_kind(provider["backend_kind"]) for provider in providers}
        if len(native_groups) != 1:
            kinds = [provider["backend_kind"] for provider in providers]
            raise ValueError(f"Failover route cannot mix native and non-native providers: {kinds}")

    def upsert_route(self, route):
        kind = str(route.get("kind") or "").strip()
        if kind not in ROUTE_KINDS:
            raise ValueError(f"Unsupported route kind: {kind}")
        name = str(route.get("name") or "").strip()
        if not name:
            raise ValueError("Route requires a name.")
        now = utcnow_iso()
        with self._connect() as conn:
            if kind == "single":
                provider_id = int(route.get("provider_id") or 0)
                provider = self.get_provider(provider_id)
                if not provider:
                    raise ValueError(f"Single route provider not found: {provider_id}")
                member_provider_ids = []
            else:
                provider_id = None
                member_provider_ids = [int(pid) for pid in (route.get("member_provider_ids") or [])]
                providers = [self.get_provider(pid) for pid in member_provider_ids]
                if not all(providers):
                    raise ValueError("Failover route references missing providers.")
                self._validate_failover_members(providers)
            is_enabled = 1 if route.get("is_enabled", True) else 0
            is_default = 1 if route.get("is_default", False) else 0
            config_json = self._dumps(route.get("config"))
            if route.get("id"):
                conn.execute(
                    """
                    UPDATE routes
                    SET name = ?, kind = ?, provider_id = ?, is_enabled = ?, config_json = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (name, kind, provider_id, is_enabled, config_json, now, int(route["id"])),
                )
                route_id = int(route["id"])
                conn.execute("DELETE FROM route_members WHERE route_id = ?", (route_id,))
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO routes (name, kind, provider_id, is_enabled, is_default, config_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 0, ?, ?, ?)
                    """,
                    (name, kind, provider_id, is_enabled, config_json, now, now),
                )
                route_id = int(cursor.lastrowid)
            for position, member_provider_id in enumerate(member_provider_ids):
                conn.execute(
                    "INSERT INTO route_members (route_id, provider_id, position) VALUES (?, ?, ?)",
                    (route_id, member_provider_id, position),
                )
            self._ensure_route_defaults(conn, route_id=route_id, make_default=bool(is_default))
            active_row = conn.execute("SELECT value FROM app_settings WHERE key = 'active_route_id'").fetchone()
            if active_row is None:
                conn.execute(
                    """
                    INSERT INTO app_settings (key, value) VALUES ('active_route_id', ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                    """,
                    (json.dumps(route_id, ensure_ascii=False),),
                )
            conn.execute(
                """
                INSERT INTO app_settings (key, value) VALUES ('use_structured_config', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (json.dumps(True, ensure_ascii=False),),
            )
        return self.get_route(route_id)

    def delete_route(self, route_id):
        with self._connect() as conn:
            conn.execute("DELETE FROM routes WHERE id = ?", (route_id,))
            next_route = conn.execute("SELECT id FROM routes ORDER BY is_default DESC, id ASC LIMIT 1").fetchone()
        self.set_setting("active_route_id", next_route["id"] if next_route else None)

    def set_active_route(self, route_id):
        route = self.get_route(route_id)
        if route is None:
            raise ValueError(f"Route not found: {route_id}")
        if not route["is_enabled"]:
            raise ValueError(f"Route is disabled: {route['name']}")
        self.set_setting("active_route_id", route["id"])
        self.set_setting("use_structured_config", True)
        return route

    def get_test_config(self, family):
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM model_test_config WHERE backend_family = ?", (family,)).fetchone()
        return dict(row) if row else None

    def set_test_config(self, family, payload):
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO model_test_config (backend_family, test_model, api_mode, reasoning_effort, prompt)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(backend_family) DO UPDATE SET
                    test_model = excluded.test_model,
                    api_mode = excluded.api_mode,
                    reasoning_effort = excluded.reasoning_effort,
                    prompt = excluded.prompt
                """,
                (
                    family,
                    payload.get("test_model"),
                    payload.get("api_mode"),
                    payload.get("reasoning_effort"),
                    payload.get("prompt") or "Reply with exactly: pong",
                ),
            )
        return self.get_test_config(family)

    def update_provider_health(self, provider_id, *, status, latency_ms=None, ttfb_ms=None, last_error="", checked_at=None):
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO provider_health (provider_id, status, latency_ms, ttfb_ms, last_checked_at, last_error)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider_id) DO UPDATE SET
                    status = excluded.status,
                    latency_ms = excluded.latency_ms,
                    ttfb_ms = excluded.ttfb_ms,
                    last_checked_at = excluded.last_checked_at,
                    last_error = excluded.last_error
                """,
                (provider_id, status, latency_ms, ttfb_ms, checked_at or utcnow_iso(), last_error or ""),
            )

    def append_diagnostic_event(self, *, provider_id=None, route_id=None, backend_name="", ok=False, error_kind=None, message="", status_code=None, extra=None):
        created_at = utcnow_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO diagnostic_events
                (provider_id, route_id, backend_name, ok, error_kind, message, status_code, created_at, extra_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    provider_id,
                    route_id,
                    backend_name or "",
                    1 if ok else 0,
                    error_kind,
                    message or "",
                    status_code,
                    created_at,
                    self._dumps(extra),
                ),
            )

    def list_diagnostic_events(self, limit=50):
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM diagnostic_events
                ORDER BY id DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        events = []
        for row in rows:
            event = dict(row)
            event["ok"] = bool(event["ok"])
            event["extra"] = self._loads(event.pop("extra_json", None), {})
            events.append(event)
        return events
