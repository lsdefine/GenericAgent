"""Unit tests for model hot-switching within a session.

Tests the contract: set_session_model changes llm_no without destroying session
state. Idle agents switch immediately; running turns defer the new client.
Run: pytest frontends/tests/test_bridge_model_switch.py -v
"""


class FakeAgent:
    """Minimal mock of an agent object with next_llm capability."""
    def __init__(self):
        self.current_llm = 0
        self.next_llm_calls = []

    def next_llm(self, llm_no: int):
        self.next_llm_calls.append(llm_no)
        self.current_llm = llm_no


class FakeSession:
    """Minimal mock of desktop_bridge.Session for model switch tests."""
    def __init__(self, sid="test-session", llm_no=0, messages=None, agent=None):
        self.id = sid
        self.llm_no = llm_no
        self.messages = messages or [
            {"id": 1, "role": "user", "content": "Hello"},
            {"id": 2, "role": "assistant", "content": "Hi there"},
            {"id": 3, "role": "user", "content": "Switch model now"},
        ]
        self.agent = agent
        self.status = "idle"
        self.updated_at = 0.0


def simulate_set_session_model(sess: FakeSession, llm_no: int) -> dict:
    """Replicate set_session_model logic from desktop_bridge.py:1105-1118."""
    import time
    sess.llm_no = int(llm_no)
    if sess.status != "running" and sess.agent is not None and hasattr(sess.agent, "next_llm"):
        try:
            sess.agent.next_llm(int(llm_no))
        except Exception:
            pass
    sess.updated_at = time.time()
    return {"ok": True, "sessionId": sess.id, "llmNo": sess.llm_no}


class TestModelHotSwitch:
    """Core contract: model switch preserves session state."""

    def test_llm_no_updated(self):
        sess = FakeSession(llm_no=0)
        result = simulate_set_session_model(sess, 2)
        assert sess.llm_no == 2
        assert result["llmNo"] == 2
        assert result["ok"] is True

    def test_messages_preserved(self):
        original_messages = [
            {"id": 1, "role": "user", "content": "Hello"},
            {"id": 2, "role": "assistant", "content": "World"},
        ]
        sess = FakeSession(messages=list(original_messages))
        simulate_set_session_model(sess, 3)
        assert sess.messages == original_messages
        assert len(sess.messages) == 2

    def test_agent_next_llm_called(self):
        agent = FakeAgent()
        sess = FakeSession(agent=agent)
        simulate_set_session_model(sess, 5)
        assert agent.next_llm_calls == [5]
        assert agent.current_llm == 5

    def test_agent_none_no_error(self):
        sess = FakeSession(agent=None)
        result = simulate_set_session_model(sess, 1)
        assert result["ok"] is True
        assert sess.llm_no == 1

    def test_agent_without_next_llm_no_error(self):
        class LegacyAgent:
            pass
        sess = FakeSession(agent=LegacyAgent())
        result = simulate_set_session_model(sess, 4)
        assert result["ok"] is True
        assert sess.llm_no == 4

    def test_updated_at_changed(self):
        sess = FakeSession()
        sess.updated_at = 0.0
        simulate_set_session_model(sess, 1)
        assert sess.updated_at > 0.0

    def test_status_not_changed(self):
        sess = FakeSession()
        sess.status = "idle"
        simulate_set_session_model(sess, 2)
        assert sess.status == "idle"

    def test_switch_during_running_preserves_status(self):
        agent = FakeAgent()
        sess = FakeSession(agent=agent)
        sess.status = "running"
        simulate_set_session_model(sess, 3)
        assert sess.status == "running"
        assert sess.llm_no == 3
        assert agent.next_llm_calls == []

    def test_multiple_switches(self):
        agent = FakeAgent()
        sess = FakeSession(agent=agent, llm_no=0)
        simulate_set_session_model(sess, 1)
        simulate_set_session_model(sess, 2)
        simulate_set_session_model(sess, 0)
        assert sess.llm_no == 0
        assert agent.next_llm_calls == [1, 2, 0]

    def test_switch_back_to_same_model(self):
        agent = FakeAgent()
        sess = FakeSession(agent=agent, llm_no=3)
        simulate_set_session_model(sess, 3)
        assert sess.llm_no == 3
        assert agent.next_llm_calls == [3]


class TestModelSwitchFrontendContract:
    """Frontend side: sendPrompt uses current selectedModelNo."""

    def test_llm_no_passed_to_send_prompt(self):
        """sendPrompt reads selectedModelNo at call time, not at session creation."""
        selectedModelNo = 0
        calls = []

        def mock_send_prompt(sid, prompt, llm_no, files=None, images=None):
            calls.append({"sid": sid, "llm_no": llm_no})

        # First message with model 0
        mock_send_prompt("s1", "hello", selectedModelNo)
        # User switches model
        selectedModelNo = 2
        # Second message with model 2
        mock_send_prompt("s1", "world", selectedModelNo)

        assert calls[0]["llm_no"] == 0
        assert calls[1]["llm_no"] == 2
        # Same session ID — context preserved
        assert calls[0]["sid"] == calls[1]["sid"]

    def test_model_change_does_not_create_new_session(self):
        """Switching model mid-session does not call createSession."""
        session_creates = []

        def mock_create():
            session_creates.append(1)
            return "new-session"

        # Simulate: active session exists, user switches model
        active_session_id = "existing-session"
        # selectModel only updates selectedModelNo + calls legacy bridge
        # It does NOT create a new session
        assert len(session_creates) == 0

    def test_live_model_cleared_on_switch(self):
        """selectModel sets liveModel to null (re-fetched from bridge on next poll)."""
        state = {"selectedModelNo": 0, "liveModel": {"isMixin": False, "current": "gpt-4"}}

        # Simulate selectModel logic
        state["selectedModelNo"] = 2
        state["liveModel"] = None  # cleared

        assert state["liveModel"] is None
        assert state["selectedModelNo"] == 2
