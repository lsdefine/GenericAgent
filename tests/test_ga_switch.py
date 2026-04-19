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

    def test_get_ui_snapshot_includes_active_summary(self):
        service = self.make_service()
        p1 = self.make_oai_provider(service, name="alpha", backend_kind="oai_text", model="m1")
        service.upsert_route({"name": "alpha-route", "kind": "single", "provider_id": p1["id"], "is_default": True})

        with patch("agentmain.get_service", return_value=service):
            from agentmain import GeneraticAgent

            agent = GeneraticAgent()
            snapshot = service.get_ui_snapshot(agent)

        self.assertEqual(snapshot["active_route_summary"]["route_name"], "alpha-route")
        self.assertEqual(snapshot["active_route_summary"]["provider_name"], "alpha")
        self.assertEqual(snapshot["stats"]["route_count"], 1)


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


class TestAgentReload(GASwitchTestCase):
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


class TestUIViewModel(unittest.TestCase):
    def test_build_ui_viewmodel_maps_summary_and_lists(self):
        from ga_switch.viewmodel import build_ui_viewmodel

        snapshot = {
            "use_structured_config": True,
            "active_route_id": 10,
            "active_runtime": {
                "route_id": 10,
                "name": "primary-route",
                "provider_name": "kimi",
                "model": "kimi-k2.5",
                "backend_class": "LLMSession",
                "route_kind": "single",
                "active": True,
            },
            "active_route_summary": {
                "route_id": 10,
                "route_name": "primary-route",
                "route_kind": "single",
                "provider_name": "kimi",
                "model": "kimi-k2.5",
                "backend_class": "LLMSession",
                "backend_kind": "oai_text",
                "api_mode": "chat_completions",
                "native_tools": False,
                "member_names": [],
                "active_member_name": "kimi",
                "last_error_kind": "quota",
                "last_error_message": "429 insufficient_quota",
                "last_status_code": 429,
                "last_switch_reason": "fallback_success:kimi",
            },
            "providers": [{
                "id": 1,
                "name": "kimi",
                "backend_kind": "oai_text",
                "model": "kimi-k2.5",
                "api_mode": "chat_completions",
                "health": {"status": "healthy", "latency_ms": 250, "ttfb_ms": 80, "last_error": ""},
            }],
            "routes": [{
                "id": 10,
                "name": "primary-route",
                "kind": "single",
                "is_enabled": True,
                "is_default": True,
                "provider": {"id": 1, "name": "kimi"},
                "members": [],
                "config": {"max_retries": 3, "base_delay": 1.5, "spring_back": 300},
            }],
            "runtime": [{
                "idx": 0,
                "route_id": 10,
                "name": "primary-route",
                "display_name": "primary-route [LLMSession/kimi]",
                "route_kind": "single",
                "backend_class": "LLMSession",
                "backend_kind": "oai_text",
                "provider_name": "kimi",
                "model": "kimi-k2.5",
                "api_mode": "chat_completions",
                "active": True,
                "native_tools": False,
                "member_names": [],
                "active_member_name": "kimi",
                "last_error_kind": "quota",
                "last_error_message": "429 insufficient_quota",
            }],
            "runtime_by_route_id": {
                10: {
                    "idx": 0,
                    "route_id": 10,
                    "name": "primary-route",
                    "backend_class": "LLMSession",
                    "backend_kind": "oai_text",
                    "provider_name": "kimi",
                    "model": "kimi-k2.5",
                    "api_mode": "chat_completions",
                    "native_tools": False,
                    "active_member_name": "kimi",
                    "last_error_kind": "quota",
                    "last_error_message": "429 insufficient_quota",
                    "last_switch_reason": "fallback_success:kimi",
                },
            },
            "events": [{
                "id": 99,
                "route_id": 10,
                "provider_id": 1,
                "backend_name": "kimi",
                "ok": False,
                "error_kind": "quota",
                "message": "429 insufficient_quota",
                "status_code": 429,
                "created_at": "2026-04-19T00:00:00Z",
            }],
        }

        vm = build_ui_viewmodel(snapshot)

        self.assertEqual(
            [section["label"] for section in vm["sections"]],
            ["总览", "全部路由", "模型服务", "诊断记录"],
        )
        self.assertEqual(vm["summary"]["headline"], "primary-route")
        self.assertEqual(vm["summary"]["route_kind_label"], "单路由")
        self.assertEqual(vm["summary"]["provider_name"], "kimi")
        self.assertEqual(vm["overview"]["current_route_card"]["title"], "当前路由")
        self.assertEqual(vm["routes"][0]["last_error_kind"], "quota")
        self.assertEqual(vm["routes"][0]["edit_groups"][1]["label"], "高级设置")
        self.assertIn("member_order", vm["routes"][0]["edit_groups"][1]["fields"])
        self.assertEqual(vm["providers"][0]["health_status"], "healthy")
        self.assertEqual(vm["providers"][0]["edit_groups"][1]["label"], "高级设置")
        self.assertIn("apikey", vm["providers"][0]["edit_groups"][1]["fields"])
        self.assertIn("extra", vm["providers"][0]["edit_groups"][1]["fields"])
        self.assertEqual(vm["events"][0]["tone"], "error")
        self.assertEqual(vm["events"][0]["raw_label"], "查看原始详情")
        self.assertTrue(vm["runtime"][0]["active"])

    def test_build_ui_viewmodel_empty_state_uses_chinese_actions(self):
        from ga_switch.viewmodel import build_ui_viewmodel

        vm = build_ui_viewmodel({
            "use_structured_config": False,
            "providers": [],
            "routes": [],
            "runtime": [],
            "runtime_by_route_id": {},
            "events": [],
            "active_route_summary": {},
            "active_runtime": {},
        })

        self.assertIsNotNone(vm["empty_state"])
        self.assertEqual(vm["empty_state"]["title"], "还没有结构化路由")
        self.assertEqual(
            [action["label"] for action in vm["empty_state"]["actions"]],
            ["导入 mykey", "新建模型服务", "继续使用当前模型"],
        )
        self.assertEqual(vm["summary"]["headline"], "当前模型")
        self.assertEqual(vm["summary"]["meta"], "继续使用当前模型")

    def test_build_provider_payload_parses_json_extra(self):
        from ga_switch.viewmodel import build_provider_payload

        payload = build_provider_payload({
            "name": "glm",
            "backend_kind": "oai_text",
            "apikey": "test-key",
            "apibase": "https://api.example.com/v1",
            "model": "glm-5.1",
            "api_mode": "responses",
            "temperature": 0.7,
            "max_tokens": 4096,
            "timeout": 8,
            "read_timeout": 45,
            "proxy": "",
            "extra": "{\"reasoning_effort\": \"low\"}",
        }, provider_id=7)

        self.assertEqual(payload["id"], 7)
        self.assertEqual(payload["api_mode"], "responses")
        self.assertIsNone(payload["proxy"])
        self.assertEqual(payload["extra"]["reasoning_effort"], "low")

    def test_build_route_payload_preserves_failover_member_order(self):
        from ga_switch.viewmodel import build_route_payload

        payload = build_route_payload({
            "name": "fallback",
            "kind": "failover",
            "is_default": True,
            "is_enabled": True,
            "member_provider_ids": [3, 1, 2],
            "max_retries": 2,
            "base_delay": 2.5,
            "spring_back": 120,
        }, route_id=15)

        self.assertEqual(payload["id"], 15)
        self.assertEqual(payload["kind"], "failover")
        self.assertEqual(payload["member_provider_ids"], [3, 1, 2])
        self.assertIsNone(payload["provider_id"])
        self.assertEqual(payload["config"]["spring_back"], 120)


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
