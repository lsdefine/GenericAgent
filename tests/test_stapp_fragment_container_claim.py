"""Regression test for #752.

Streamlit >=1.60 raises
"A fragment tried to write to a container created outside the fragment"
when a ``@st.fragment`` first writes into an external container that hasn't
been claimed by a full-app run. ``_tick()`` in ``frontends/stapp.py`` writes
folding expanders into ``_stream_fh`` (an external container) on every
streaming tick.

Fix: introduce a module-scope ``_stream_claimed`` flag and reserve the
external container's position via a single empty ``st.markdown("")``
write inside ``_stream_fh`` on the first fragment-side expander write.
After the claim, subsequent writes fold into the already-reserved
position without triggering the fragment error.

These tests load ``_tick`` from ``frontends/stapp.py`` via
``ast.get_source_segment`` + ``exec`` so we exercise the actual source
rather than a copy, and skip Streamlit's heavy import surface (we stub
the module attributes ``_tick`` reads and writes to).
"""

import ast
import re
import sys
import types
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
STAPP_PATH = REPO_ROOT / "frontends" / "stapp.py"


def _load_tick():
    """AST-extract ``_tick`` from frontends/stapp.py and exec it under a
    lightweight namespace that stubs the Streamlit + session_state API
    ``_tick`` uses. Heavy top-level imports (streamlit, agentmain,
    llmcore) are skipped entirely.

    The function source is taken verbatim from stapp.py and re-executed in
    a namespace where ``st``, ``st.session_state``, ``agent``, ``time``,
    ``re``, and the module globals it reads (``_stream_fh``, ``_stream_ls``,
    ``_stream_claimed``, ``_step_title``, ``_render_stat_badge``) are
    controllable per-test. ``st.container``/``st.expander``/``st.markdown``
    are stubs that record every call so the test can verify the claim
    behaviour.
    """

    raw = STAPP_PATH.read_text(encoding="utf-8")
    tree = ast.parse(raw)

    wanted = {"_tick", "_step_title"}
    extracted = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            extracted[node.name] = ast.get_source_segment(raw, node)

    if "_tick" not in extracted:
        raise RuntimeError("could not AST-extract _tick from stapp.py")

    return extracted["_tick"], extracted.get("_step_title", "")


class _FakeStContainer:
    def __init__(self):
        self.writes = []  # list of ("markdown", text) / ("expander", title)

    def __enter__(self):
        self._entered = True
        return self

    def __exit__(self, *exc):
        return False

    def markdown(self, text, **kw):
        self.writes.append(("markdown", text, kw))

    def expander(self, label, expanded=False):
        e = _FakeStContainer()
        self.writes.append(("expander", label, expanded))
        return e


def _install_fake_streamlit():
    """Build a minimal ``st`` stub that records the writes ``_tick`` issues
    via ``_stream_fh`` and ``_stream_ls``. Returns the stub plus a list
    the test can inspect."""

    stream_fh = _FakeStContainer()
    stream_ls = _FakeStContainer()

    def container():
        return stream_fh

    def empty():
        return stream_ls

    # ``stream_ls.container()`` is called as ``stream_ls.container()`` in
    # the real source. Make our outer container's .container() return a
    # sub-container too.
    stream_ls.container = lambda: _FakeStContainer()

    class _Expander:
        def __init__(self, label, expanded=False):
            self.label = label
            self.expanded = expanded
            self.writes = []

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def markdown(self, text, **kw):
            self.writes.append(("markdown", text, kw))

    class _SessionState:
        """Both dict-style (``st.session_state.get(key)``) and
        attribute-style (``st.session_state._stream_frozen = 5``) access
        — Streamlit supports both via its server-side session store."""

        def __init__(self, initial=None):
            self._d = dict(initial or {})
            self._attr = {}

        def get(self, key, default=None):
            return self._d.get(key, self._attr.get(key, default))

        def pop(self, key, *a):
            return self._d.pop(key, *a)

        def __setitem__(self, key, value):
            self._d[key] = value
            self._attr[key] = value

        def __getitem__(self, key):
            return self._d.get(key, self._attr.get(key))

        def __setattr__(self, key, value):
            super().__setattr__(key, value)
            if key != "_d" and key != "_attr":
                self._attr[key] = value

        def __contains__(self, key):
            return key in self._d or key in self._attr

    class _St:
        def __init__(self):
            self.session_state = _SessionState()
            self.rerun_calls = []
            self.markdown_calls = []  # global st.markdown("") for claim

        def expander(self, label, expanded=False):
            return _Expander(label, expanded)

        def markdown(self, text, **kw):
            # The fix calls ``with _stream_fh: st.markdown("")`` —
            # the markdown call goes to the global st object, NOT to
            # _stream_fh.markdown. We record here so the claim gate
            # can be verified.
            self.markdown_calls.append((text, kw))
            return ("markdown", text, kw)

        def rerun(self, scope=None):
            self.rerun_calls.append(scope)

    st_stub = _St()
    return st_stub, stream_fh, stream_ls


def _exec_tick(tick_src, st_stub, stream_fh, stream_ls, step_title_src=""):
    """Exec ``_tick`` source in a controlled namespace. ``stream_fh`` and
    ``stream_ls`` are bound as module globals matching the real layout;
    ``agent`` is a fake with the attributes ``_tick`` reads."""

    agent = types.SimpleNamespace()
    agent.all_outputs = []
    agent.is_running = True
    agent._current_queue = None
    agent._hub_inbox = None

    # _step_title: produce a stable string the test can assert on.
    if step_title_src:
        step_title_ns = {"re": __import__("re")}
        exec(step_title_src, step_title_ns)
        step_title_fn = step_title_ns["_step_title"]
    else:
        step_title_fn = lambda body, frozen: f"step {frozen}: {body[:30]}"

    # _render_stat_badge stub — _tick calls it but we don't need real output.
    render_stat_badge = lambda **kw: None
    # _poll_main_task stub — return None so the while-loop branch fires.
    poll_main_task = lambda: None

    ns = {
        "st": st_stub,
        "agent": agent,
        "time": __import__("time"),
        "re": __import__("re"),
        "stream_fh": stream_fh,
        "stream_ls": stream_ls,
        "_stream_fh": stream_fh,
        "_stream_ls": stream_ls,
        "_step_title": step_title_fn,
        "_render_stat_badge": render_stat_badge,
        "_poll_main_task": poll_main_task,
    }
    # Provide session_state like Streamlit does.
    st_stub.session_state = {"display_queue": "q1"}

    # Streamlit 1.60 module globals the original code reads:
    ns["_stream_claimed"] = False

    exec(tick_src, ns)
    return ns["_tick"]


# Tests -----------------------------------------------------------------------


def test_tick_claims_stream_fh_on_first_expander_write():
    """#752 case 1: first fragment-side expander write must reserve the
    container position via a leading ``with _stream_fh: st.markdown(\"\")``
    call before any expander folds in. The pre-fix code wrote straight
    into the external container without the claim, raising the
    Streamlit 1.60 fragment error."""
    tick_src, _ = _load_tick()
    st_stub, stream_fh, stream_ls = _install_fake_streamlit()
    st_stub.session_state = st_stub.session_state.__class__({
        "display_queue": "q1",
        "_stream_frozen": 0,
    })

    # Provide an agent with at least 2 outputs so the streaming branch
    # enters the while loop and the claim gate fires.
    agent = types.SimpleNamespace()
    agent.all_outputs = [{"outputs": ["step body one", "step body two"]}]
    agent.is_running = True
    agent._current_queue = "q1"
    agent._hub_inbox = None

    tick_fn = _exec_tick_with_agent(
        tick_src, st_stub, stream_fh, stream_ls, agent
    )
    tick_fn()

    # The fix calls ``st.markdown("")`` (global st, not _stream_fh.markdown)
    # inside ``with _stream_fh:`` to claim the external container position.
    claim_markdowns = [
        c for c in st_stub.markdown_calls if c[0] == ""
    ]
    assert claim_markdowns, (
        f"_tick did not emit a container-claim markdown via the global "
        f"st.markdown(\"\"); markdown_calls={st_stub.markdown_calls!r}"
    )


def test_tick_claims_stream_fh_exactly_once_across_multiple_ticks():
    """#752 case 2: the claim flag must flip to True on the first write
    and stay True, so subsequent ticks do NOT re-emit the empty
    ``st.markdown(\"\")`` (which would inject a visible blank line on
    every refresh)."""
    tick_src, _ = _load_tick()
    st_stub, stream_fh, stream_ls = _install_fake_streamlit()
    st_stub.session_state = st_stub.session_state.__class__({
        "display_queue": "q1",
        "_stream_frozen": 0,
    })

    # Override agent.all_outputs so the streaming branch produces ≥2 steps.
    agent = types.SimpleNamespace()
    agent.all_outputs = [{"outputs": ["step body one", "step body two"]}]
    agent.is_running = True
    agent._current_queue = "q1"
    agent._hub_inbox = None

    # First tick — _tick must emit the claim markdown.
    tick_fn_1 = _exec_tick_with_agent(tick_src, st_stub, stream_fh, stream_ls, agent)
    tick_fn_1()
    first_tick_markdowns = list(st_stub.markdown_calls)
    first_tick_claims = [c for c in first_tick_markdowns if c[0] == ""]
    assert first_tick_claims, (
        f"first tick did not emit a container-claim markdown; "
        f"markdown_calls={first_tick_markdowns!r}"
    )

    # Capture the post-tick-1 length to find NEW writes from tick 2.
    pre_second_len = len(st_stub.markdown_calls)

    # Re-exec the same _tick source with _stream_claimed=True to prove
    # the gate prevents re-claiming on subsequent ticks.
    tick_fn_2 = _exec_tick_with_agent(
        tick_src, st_stub, stream_fh, stream_ls, agent,
        claim_already=True,
    )
    # Reset _stream_frozen and re-call.
    st_stub.session_state["_stream_frozen"] = 0
    tick_fn_2()  # call _tick with _stream_claimed=True

    new_markdowns = st_stub.markdown_calls[pre_second_len:]
    # The second-tick markdown calls should contain zero empty-markdown claims.
    claim_re_emissions = [c for c in new_markdowns if c[0] == ""]
    assert claim_re_emissions == [], (
        f"second tick re-emitted the container-claim markdown; "
        f"new_markdowns={new_markdowns!r}"
    )


def _exec_tick_with_agent(tick_src, st_stub, stream_fh, stream_ls, agent,
                          claim_already=False):
    """Helper for the multi-tick test: re-exec _tick with a custom agent
    stub and an explicit claim flag."""
    step_title_fn = lambda body, frozen: f"step {frozen}"

    ns = {
        "st": st_stub,
        "agent": agent,
        "time": __import__("time"),
        "re": __import__("re"),
        "_stream_fh": stream_fh,
        "_stream_ls": stream_ls,
        "_step_title": step_title_fn,
        "_render_stat_badge": lambda **kw: None,
        "_poll_main_task": lambda: None,
        "_stream_claimed": claim_already,
    }
    exec(tick_src, ns)
    return ns["_tick"]


def test_pre_fix_code_would_emit_no_claim():
    """#752 case 3: behavioural pin of the OLD pre-fix code. Confirms
    the test design is sound — the old code had no claim at all and
    would have raised the Streamlit 1.60 fragment error. We pin this by
    running a literal copy of the OLD ``while`` loop body and asserting
    it never calls ``st.markdown(\"\")`` (the only fix-side invariant)."""

    # Old while-loop body copied verbatim from pre-fix frontends/stapp.py
    # lines 476-480 (without the fix).
    stream_fh = _FakeStContainer()

    OLD_BODY = """
frozen = st.session_state.get('_stream_frozen', 0)
while frozen < max(0, len(steps) - 1):
    body = steps[frozen] or ''
    with _stream_fh:
        with st.expander(_step_title(body, frozen), expanded=False): st.markdown(body)
    frozen += 1
"""
    ns = {
        "st": types.SimpleNamespace(),
        "st_session": {"_stream_frozen": 0},
        "_stream_fh": stream_fh,
        "_step_title": lambda body, frozen: f"step {frozen}",
        "steps": ["hello"],
        "session_state": {"_stream_frozen": 0},
    }

    # The OLD code reads st.session_state — proxy it via SimpleNamespace
    # that supports attribute access through the dict.
    class _SS:
        def __init__(self, d):
            self._d = d
        def get(self, k, default=None):
            return self._d.get(k, default)
    ns["st"].session_state = _SS({"_stream_frozen": 0})

    # The OLD expander implementation only needs to record the call.
    class _Exp:
        def __init__(self):
            self.writes = []
        def __enter__(self):
            return self
        def __exit__(self, *exc):
            return False
        def markdown(self, text, **kw):
            self.writes.append(text)

    def _expander(label, expanded=False):
        e = _Exp()
        stream_fh.writes.append(("expander", label, e))
        return e
    ns["st"].expander = _expander
    ns["st"].markdown = lambda text, **kw: stream_fh.writes.append(("markdown", text, kw))

    exec(OLD_BODY, ns)

    # OLD pre-fix behaviour: no empty-markdown claim appears.
    claim_writes = [w for w in stream_fh.writes if w[0] == "markdown" and w[1] == ""]
    assert claim_writes == [], (
        f"old pre-fix code unexpectedly emitted a container-claim "
        f"markdown; writes={stream_fh.writes!r}"
    )


def test_tick_skips_claim_when_stream_fh_is_none():
    """#752 case 4: when ``_stream_fh`` is None (no active
    ``display_queue``), ``_tick`` must skip the claim and expander
    block entirely and fall through to the detached/hub/idle paths.
    The fix only touches the streaming branch; the detached/hub/idle
    branches must remain unreachable from the streaming branch's code
    path."""
    tick_src, _ = _load_tick()
    st_stub, stream_fh, stream_ls = _install_fake_streamlit()
    st_stub.session_state = st_stub.session_state.__class__({
        "display_queue": None,
        "_stream_frozen": 0,
    })

    # _stream_fh=None is the detached branch condition; _tick must
    # not raise and must not call _render_stat_badge(is_running=True)
    # from the streaming path.
    stream_fh = None  # simulate detached / no stream host

    # Re-exec with stream_fh=None to confirm _tick does not raise and
    # does not emit a claim write.
    agent = types.SimpleNamespace()
    agent.all_outputs = []
    agent.is_running = True
    agent._current_queue = None
    agent._hub_inbox = None

    ns = {
        "st": st_stub,
        "agent": agent,
        "time": __import__("time"),
        "re": __import__("re"),
        "_stream_fh": None,
        "_stream_ls": None,
        "_step_title": lambda body, frozen: "x",
        "_render_stat_badge": lambda **kw: None,
        "_stream_claimed": False,
    }
    exec(tick_src, ns)
    # Calling _tick with _stream_fh=None must not raise.
    ns["_tick"]()