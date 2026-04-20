import ast
import inspect
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class GASwitchTestCase(unittest.TestCase):
    def make_service(self):
        from ga_switch.service import GASwitchService

        tmp_dir = tempfile.mkdtemp(prefix="ga-switch-test-")
        return GASwitchService(os.path.join(tmp_dir, "ga-switch.db"))

    def make_oai_provider(self, service, name="p1", backend_kind="oai_text", model="gpt-4.1-mini"):
        return service.upsert_provider({
            "name": name,
            "backend_kind": backend_kind,
            "apikey": "test-key",
            "apibase": "https://api.example.com/v1",
            "model": model,
            "proxy": "http://127.0.0.1:8080",
            "extra": {"token": "secret"},
        })

    def make_agent(self, service):
        with patch("agentmain.get_service", return_value=service):
            from agentmain import GeneraticAgent

            return GeneraticAgent()


class TestDependencyBoundaries(GASwitchTestCase):
    def test_llmcore_does_not_import_ga_switch(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "llmcore.py"), encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename="llmcore.py")

        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        self.assertFalse(any(name == "ga_switch" or name.startswith("ga_switch.") for name in imports))

    def test_service_does_not_import_agentmain(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "ga_switch", "service.py"), encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename="ga_switch/service.py")

        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        self.assertFalse(any(name == "agentmain" or name.startswith("agentmain.") for name in imports))

    def test_get_config_snapshot_does_not_accept_agent(self):
        from ga_switch.service import GASwitchService

        signature = inspect.signature(GASwitchService.get_config_snapshot)
        self.assertNotIn("agent", signature.parameters)


class TestGASwitchImport(GASwitchTestCase):
    def test_import_legacy_mykey_json_to_structured_routes(self):
        service = self.make_service()
        tmp_dir = tempfile.mkdtemp(prefix="ga-switch-import-")
        legacy_path = os.path.join(tmp_dir, "mykey.json")
        with open(legacy_path, "w", encoding="utf-8") as f:
            json.dump({
                "oai_config": {
                    "name": "kimi-primary",
                    "apikey": "k1",
                    "apibase": "https://api.example.com/v1",
                    "model": "kimi-k2.5",
                },
                "oai_config_backup": {
                    "name": "glm-backup",
                    "apikey": "k2",
                    "apibase": "https://api.example.com/v1",
                    "model": "glm-5.1",
                },
                "mixin_config": {
                    "name": "fallback-pair",
                    "llm_nos": ["kimi-primary", "glm-backup"],
                    "max_retries": 2,
                    "spring_back": 60,
                },
            }, f, ensure_ascii=False)

        result = service.import_legacy_mykey(legacy_path)

        self.assertEqual(len(result["providers"]), 2)
        self.assertEqual({route["kind"] for route in result["routes"]}, {"single", "failover"})
        failover = next(route for route in result["routes"] if route["kind"] == "failover")
        self.assertEqual([member["name"] for member in failover["members"]], ["kimi-primary", "glm-backup"])
        self.assertTrue(service.use_structured_config())


class TestGASwitchValidation(GASwitchTestCase):
    def test_provider_update_round_trips(self):
        service = self.make_service()
        provider = self.make_oai_provider(service, name="editable")

        updated = service.upsert_provider({
            "id": provider["id"],
            "name": "editable",
            "backend_kind": "oai_text",
            "apikey": "test-key-2",
            "apibase": "https://api.example.com/v1",
            "model": "updated-model",
            "timeout": 9,
        })

        self.assertEqual(updated["model"], "updated-model")
        self.assertEqual(updated["timeout"], 9)

    def test_failover_rejects_native_and_non_native_mix(self):
        service = self.make_service()
        native = self.make_oai_provider(service, name="native", backend_kind="native_oai")
        text = self.make_oai_provider(service, name="text", backend_kind="oai_text")

        with self.assertRaisesRegex(ValueError, "cannot mix native and non-native"):
            service.upsert_route({
                "name": "bad-route",
                "kind": "failover",
                "member_provider_ids": [native["id"], text["id"]],
            })

    def test_failover_member_order_is_persisted(self):
        service = self.make_service()
        p1 = self.make_oai_provider(service, name="alpha")
        p2 = self.make_oai_provider(service, name="beta")
        p3 = self.make_oai_provider(service, name="gamma")

        route = service.upsert_route({
            "name": "fallback-route",
            "kind": "failover",
            "member_provider_ids": [p3["id"], p1["id"], p2["id"]],
            "is_default": True,
        })

        self.assertEqual(route["member_provider_ids"], [p3["id"], p1["id"], p2["id"]])
        self.assertEqual([member["name"] for member in route["members"]], ["gamma", "alpha", "beta"])


class TestSnapshots(GASwitchTestCase):
    def test_config_snapshot_redacts_sensitive_fields(self):
        service = self.make_service()
        p1 = self.make_oai_provider(service, name="alpha", model="m1")
        p2 = self.make_oai_provider(service, name="beta", model="m2")
        service.upsert_route({
            "name": "fallback-route",
            "kind": "failover",
            "member_provider_ids": [p1["id"], p2["id"]],
            "is_default": True,
        })

        snapshot = service.get_config_snapshot()

        for provider in snapshot["providers"]:
            self.assertNotIn("apikey", provider)
            self.assertNotIn("apibase", provider)
            self.assertNotIn("proxy", provider)
            self.assertNotIn("extra", provider)
        for route in snapshot["routes"]:
            if route["provider"] is not None:
                self.assertNotIn("apikey", route["provider"])
                self.assertNotIn("apibase", route["provider"])
            for member in route["members"]:
                self.assertNotIn("apikey", member)
                self.assertNotIn("apibase", member)
                self.assertNotIn("proxy", member)
                self.assertNotIn("extra", member)

    def test_runtime_snapshot_uses_backend_safe_contract(self):
        from ga_switch.runtime_bridge import build_runtime_snapshot

        service = self.make_service()
        p1 = self.make_oai_provider(service, name="alpha", backend_kind="oai_text", model="m1")
        p2 = self.make_oai_provider(service, name="beta", backend_kind="oai_text", model="m2")
        service.upsert_route({"name": "alpha-route", "kind": "single", "provider_id": p1["id"], "is_default": True})
        service.upsert_route({"name": "fallback-route", "kind": "failover", "member_provider_ids": [p1["id"], p2["id"]]})

        agent = self.make_agent(service)
        snapshot = build_runtime_snapshot(service.get_config_snapshot(), agent.describe_llms())

        self.assertEqual(snapshot["active_route_summary"]["route_name"], "alpha-route")
        self.assertEqual(snapshot["active_route_summary"]["provider_name"], "alpha")
        self.assertEqual(snapshot["stats"]["route_count"], 2)
        self.assertNotIn("quick_actions", snapshot)
        self.assertNotIn("edit_groups", snapshot)
        self.assertNotIn("active_runtime", snapshot)
        for provider in snapshot["providers"]:
            self.assertNotIn("apikey", provider)
            self.assertNotIn("apibase", provider)


class TestDiagnostics(unittest.TestCase):
    def test_classify_error_common_cases(self):
        from ga_switch.diagnostics import classify_error

        self.assertEqual(classify_error(status_code=401, message="Unauthorized"), "auth")
        self.assertEqual(classify_error(status_code=429, body="insufficient_quota"), "quota")
        self.assertEqual(classify_error(status_code=429, body="rate limit exceeded"), "rate_limit")
        self.assertEqual(classify_error(status_code=404, body="model not found"), "model_not_found")
        self.assertEqual(classify_error(message="unsupported parameter reasoning_effort"), "unsupported_param")
        self.assertEqual(classify_error(exc_type="Timeout", message="timed out"), "timeout")
        self.assertEqual(classify_error(exc_type="ConnectionError", message="connection refused"), "network")


class TestAgentRuntime(GASwitchTestCase):
    def test_set_active_route_switches_future_runtime(self):
        from ga_switch.runtime_bridge import build_runtime_snapshot

        service = self.make_service()
        p1 = self.make_oai_provider(service, name="route-a", model="m1")
        p2 = self.make_oai_provider(service, name="route-b", model="m2")
        route_a = service.upsert_route({"name": "route-a", "kind": "single", "provider_id": p1["id"], "is_default": True})
        route_b = service.upsert_route({"name": "route-b", "kind": "single", "provider_id": p2["id"]})

        agent = self.make_agent(service)
        switched = agent.set_active_route(route_b["id"])
        snapshot = build_runtime_snapshot(service.get_config_snapshot(), agent.describe_llms())

        self.assertEqual(switched["route_id"], route_b["id"])
        self.assertEqual(agent.llmclient.ga_switch_route_name, "route-b")
        self.assertEqual(snapshot["active_route_id"], route_b["id"])
        self.assertEqual(snapshot["active_route_summary"]["route_name"], "route-b")
        self.assertNotEqual(route_a["id"], route_b["id"])

    def test_reload_llm_config_preserves_history_and_blocks_running(self):
        service = self.make_service()
        p1 = self.make_oai_provider(service, name="route-a", backend_kind="oai_text", model="m1")
        service.upsert_route({"name": "route-a", "kind": "single", "provider_id": p1["id"], "is_default": True})

        agent = self.make_agent(service)
        agent.llmclient.backend.history = [{"role": "user", "content": [{"type": "text", "text": "keep me"}]}]

        p2 = self.make_oai_provider(service, name="route-b", backend_kind="oai_text", model="m2")
        service.upsert_route({"name": "route-b", "kind": "single", "provider_id": p2["id"]})
        described = agent.reload_llm_config()

        self.assertEqual(agent.llmclient.backend.history[0]["content"][0]["text"], "keep me")
        self.assertEqual(agent.llmclient.ga_switch_route_name, "route-a")
        self.assertEqual(len(described), 2)

        agent.is_running = True
        with self.assertRaisesRegex(RuntimeError, "Cannot reload"):
            agent.reload_llm_config()

    def test_structured_mode_failure_does_not_fallback_to_legacy(self):
        import llmcore
        from ga_switch.diagnostics import utcnow_iso

        service = self.make_service()
        now = utcnow_iso()
        with service.store._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO routes (name, kind, provider_id, is_enabled, is_default, config_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("broken-route", "single", None, 1, 1, "{}", now, now),
            )
            route_id = int(cursor.lastrowid)
            conn.execute(
                """
                INSERT INTO app_settings (key, value) VALUES ('active_route_id', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (json.dumps(route_id),),
            )
            conn.execute(
                """
                INSERT INTO app_settings (key, value) VALUES ('use_structured_config', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (json.dumps(True),),
            )

        legacy_payload = {
            "oai_config": {
                "name": "legacy-ok",
                "apikey": "legacy-key",
                "apibase": "https://api.example.com/v1",
                "model": "legacy-model",
            }
        }
        llmcore.__dict__.pop("mykeys", None)
        llmcore.__dict__.pop("proxies", None)
        with patch.object(llmcore, "_load_mykeys", return_value=legacy_payload):
            with self.assertRaisesRegex(ValueError, "missing provider"):
                self.make_agent(service)

    def test_failover_runtime_keeps_member_order_and_diagnostics_fields(self):
        service = self.make_service()
        p1 = self.make_oai_provider(service, name="alpha", model="m1")
        p2 = self.make_oai_provider(service, name="beta", model="m2")
        p3 = self.make_oai_provider(service, name="gamma", model="m3")
        service.upsert_route({
            "name": "fallback-route",
            "kind": "failover",
            "member_provider_ids": [p3["id"], p1["id"], p2["id"]],
            "is_default": True,
            "config": {"spring_back": 60},
        })

        agent = self.make_agent(service)
        described = agent.describe_llms()

        self.assertEqual(len(described), 1)
        self.assertEqual(described[0]["member_names"], ["gamma", "alpha", "beta"])
        self.assertEqual(described[0]["active_member_name"], "gamma")
        self.assertIn("last_error_message", described[0])
        self.assertIn("last_status_code", described[0])
        self.assertIn("spring_back_seconds", described[0])


class TestModelTester(GASwitchTestCase):
    def test_model_test_uses_temporary_session(self):
        from ga_switch.runtime_bridge import build_test_client

        service = self.make_service()
        provider = self.make_oai_provider(service, name="tester", backend_kind="oai_text")
        fresh_client = build_test_client(service, provider)
        fresh_client.backend.history = [{"role": "user", "content": [{"type": "text", "text": "real history"}]}]

        def fake_post(url, headers=None, json=None, stream=None, timeout=None, proxies=None):
            resp = MagicMock()
            resp.status_code = 200
            resp.iter_lines.return_value = iter([b"data: [DONE]"])
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            return resp

        with patch("llmcore.requests.post", side_effect=fake_post):
            result = service.run_model_test(provider["id"])

        self.assertEqual(result["status"], "healthy")
        self.assertEqual(fresh_client.backend.history[0]["content"][0]["text"], "real history")


if __name__ == "__main__":
    unittest.main()
