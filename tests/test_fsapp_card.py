import importlib
import sys
import types

import pytest


class _DummyAgent:
    def run(self):
        return None


class _DummyBuilder:
    calls = []

    def __getattr__(self, name):
        def _call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return self

        return _call

    def build(self):
        return types.SimpleNamespace()


def _install_import_stubs(monkeypatch):
    _DummyBuilder.calls = []

    agentmain = types.ModuleType("agentmain")
    agentmain.GeneraticAgent = _DummyAgent
    monkeypatch.setitem(sys.modules, "agentmain", agentmain)

    common = types.ModuleType("frontends.chatapp_common")
    common.FILE_HINT = ""
    common.split_text = lambda text, _limit: [text]
    common.AgentChatMixin = type(
        "AgentChatMixin",
        (),
        {
            "__init__": lambda self, agent, user_tasks: (
                setattr(self, "agent", agent),
                setattr(self, "user_tasks", user_tasks),
                None,
            )[-1]
        },
    )
    monkeypatch.setitem(sys.modules, "frontends.chatapp_common", common)

    lark = types.ModuleType("lark_oapi")
    lark.LogLevel = types.SimpleNamespace(INFO="INFO")
    lark.Client = types.SimpleNamespace(builder=lambda: _DummyBuilder())
    lark.EventDispatcherHandler = types.SimpleNamespace(builder=lambda *_args: _DummyBuilder())
    monkeypatch.setitem(sys.modules, "lark_oapi", lark)
    monkeypatch.setitem(sys.modules, "lark_oapi.api", types.ModuleType("lark_oapi.api"))
    monkeypatch.setitem(sys.modules, "lark_oapi.api.im", types.ModuleType("lark_oapi.api.im"))

    im_v1 = types.ModuleType("lark_oapi.api.im.v1")
    for name in (
        "CreateMessageRequest",
        "CreateMessageRequestBody",
        "PatchMessageRequest",
        "PatchMessageRequestBody",
    ):
        setattr(im_v1, name, types.SimpleNamespace(builder=lambda: _DummyBuilder()))
    monkeypatch.setitem(sys.modules, "lark_oapi.api.im.v1", im_v1)


def _load_fsapp(monkeypatch):
    _install_import_stubs(monkeypatch)
    sys.modules.pop("frontends.fsapp", None)
    return importlib.import_module("frontends.fsapp")


def test_main_registers_message_read_noop_handler(monkeypatch):
    fsapp = _load_fsapp(monkeypatch)
    starts = []

    monkeypatch.setattr(
        fsapp,
        "_feishu_config",
        lambda: ("app_id", "app_secret", set(), True, "unit-test-config"),
    )
    monkeypatch.setattr(fsapp, "create_client", lambda: object())
    fsapp.lark.ws = types.SimpleNamespace(
        Client=lambda *args, **kwargs: types.SimpleNamespace(
            start=lambda: (starts.append((args, kwargs)), (_ for _ in ()).throw(KeyboardInterrupt()))
        )
    )

    with pytest.raises(KeyboardInterrupt):
        fsapp.main()

    methods = [name for name, _args, _kwargs in _DummyBuilder.calls]
    assert "register_p2_im_message_receive_v1" in methods
    assert "register_p2_im_message_message_read_v1" in methods
    assert starts
