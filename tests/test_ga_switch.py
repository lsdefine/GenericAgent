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
        })


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


class TestGASwitchBuild(GASwitchTestCase):
    def test_build_clients_from_store_maps_backend_classes(self):
        service = self.make_service()
        p1 = self.make_oai_provider(service, name="alpha", backend_kind="oai_text")
        p2 = self.make_oai_provider(service, name="beta", backend_kind="oai_text")
        service.upsert_route({"name": "alpha-route", "kind": "single", "provider_id": p1["id"], "is_default": True})
        service.upsert_route({"name": "fallback-route", "kind": "failover", "member_provider_ids": [p1["id"], p2["id"]]})

        clients, meta = service.build_clients_from_store()

        self.assertEqual([type(client.backend).__name__ for client in clients], ["LLMSession", "MixinSession"])
        self.assertEqual(meta["active_index"], 0)
        self.assertEqual(clients[1].ga_switch_route_kind, "failover")

    def test_runtime_snapshot_includes_active_summary_without_ui_fields(self):
        service = self.make_service()
        p1 = self.make_oai_provider(service, name="alpha", backend_kind="oai_text", model="m1")
        service.upsert_route({"name": "alpha-route", "kind": "single", "provider_id": p1["id"], "is_default": True})

        with patch("agentmain.get_service", return_value=service):
            from agentmain import GeneraticAgent

            agent = GeneraticAgent()
            snapshot = service.get_runtime_snapshot(agent)

        self.assertEqual(snapshot["active_route_summary"]["route_name"], "alpha-route")
        self.assertEqual(snapshot["active_route_summary"]["provider_name"], "alpha")
        self.assertEqual(snapshot["stats"]["route_count"], 1)
        self.assertNotIn("quick_actions", snapshot)
        self.assertNotIn("edit_groups", snapshot)
        self.assertNotIn("active_runtime", snapshot)

    def test_get_ui_snapshot_alias_matches_runtime_snapshot(self):
        service = self.make_service()
        p1 = self.make_oai_provider(service, name="alpha")
        service.upsert_route({"name": "alpha-route", "kind": "single", "provider_id": p1["id"], "is_default": True})

        with patch("agentmain.get_service", return_value=service):
            from agentmain import GeneraticAgent

            agent = GeneraticAgent()
            runtime_snapshot = service.get_runtime_snapshot(agent)
            alias_snapshot = service.get_ui_snapshot(agent)

        self.assertEqual(alias_snapshot, runtime_snapshot)


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
        service = self.make_service()
        p1 = self.make_oai_provider(service, name="route-a", model="m1")
        p2 = self.make_oai_provider(service, name="route-b", model="m2")
        route_a = service.upsert_route({"name": "route-a", "kind": "single", "provider_id": p1["id"], "is_default": True})
        route_b = service.upsert_route({"name": "route-b", "kind": "single", "provider_id": p2["id"]})

        with patch("agentmain.get_service", return_value=service):
            from agentmain import GeneraticAgent

            agent = GeneraticAgent()
            switched = agent.set_active_route(route_b["id"])
            snapshot = service.get_runtime_snapshot(agent)

        self.assertEqual(switched["route_id"], route_b["id"])
        self.assertEqual(agent.llmclient.ga_switch_route_name, "route-b")
        self.assertEqual(snapshot["active_route_id"], route_b["id"])
        self.assertEqual(snapshot["active_route_summary"]["route_name"], "route-b")
        self.assertNotEqual(route_a["id"], route_b["id"])

    def test_reload_llm_config_preserves_history_and_blocks_running(self):
        service = self.make_service()
        p1 = self.make_oai_provider(service, name="route-a", backend_kind="oai_text", model="m1")
        service.upsert_route({"name": "route-a", "kind": "single", "provider_id": p1["id"], "is_default": True})

        with patch("agentmain.get_service", return_value=service):
            from agentmain import GeneraticAgent

            agent = GeneraticAgent()
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


class TestModelTester(GASwitchTestCase):
    def test_model_test_uses_temporary_session_and_keeps_real_history(self):
        service = self.make_service()
        provider = self.make_oai_provider(service, name="tester", backend_kind="oai_text")
        real_client = service.build_client_from_provider(provider, route_id=123, route_name="real-route")
        real_client.backend.history = [{"role": "user", "content": [{"type": "text", "text": "real history"}]}]

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
        self.assertEqual(real_client.backend.history[0]["content"][0]["text"], "real history")


if __name__ == "__main__":
    unittest.main()
