
"""Unit test for do_file_write auto-resume on truncation.
Mocks Response object + truncation markers, exercises 3 scenarios:
1) Normal complete write
2) First truncation -> partial write + resume state set
3) Continuation with overlap -> dedup + finish
"""
import sys, os, tempfile, shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Stub heavy imports before loading ga
class _Stub:
    def __getattr__(self, k): return _Stub()
    def __call__(self, *a, **kw): return _Stub()
sys.modules.setdefault('simphtml', _Stub())

import ga
from agent_loop import StepOutcome

# --- Mock Response ---
class MockResponse:
    def __init__(self, content): self.content = content; self.thinking = ""

# --- Mock Handler (skip __init__, set only what do_file_write needs) ---
class FakeHandler(ga.GenericAgentHandler):
    def __init__(self, cwd):
        self.cwd = cwd
        self.working = {}
    def _get_abs_path(self, p):
        return p if os.path.isabs(p) else os.path.join(self.cwd, p)
    def _get_anchor_prompt(self, skip=False): return ""

def run_tool(handler, args, response):
    """Drain generator, capture yields and final StepOutcome."""
    gen = handler.do_file_write(args, response)
    yields = []
    try:
        while True: yields.append(next(gen))
    except StopIteration as e:
        return yields, e.value

def header(t): print(f"\n{'='*60}\n  {t}\n{'='*60}")

tmp = tempfile.mkdtemp()
try:
    h = FakeHandler(tmp)

    # ============ TEST 1: Normal complete write ============
    header("TEST 1: Normal complete write (closed tag)")
    resp = MockResponse("Sure, here's the file:\n<file_content>line1\nline2\nline3</file_content>\nDone.")
    yields, outcome = run_tool(h, {"path": "a.txt", "mode": "overwrite"}, resp)
    print("YIELDS:"); [print(" ", y.rstrip()) for y in yields]
    print("OUTCOME:", outcome.data)
    p = os.path.join(tmp, "a.txt")
    actual = open(p, encoding='utf-8').read()
    assert actual == "line1\nline2\nline3", f"got {actual!r}"
    assert outcome.data['status'] == 'success'
    assert h.working.get('_file_write_resume') is None
    print("✅ PASS: file written correctly, no resume state")

    # ============ TEST 2: First truncation ============
    header("TEST 2: First truncation (no closing tag + truncation marker)")
    h.working = {}
    truncated = (
        "Writing the file:\n<file_content>"
        "PART_A_LINE_1\nPART_A_LINE_2\nPART_A_LINE_3\nPART_A_LINE_4_TAIL_ANCHOR_HERE_XYZ"
        "\n\n[!!! max_tokens !!!]"
    )
    resp = MockResponse(truncated)
    yields, outcome = run_tool(h, {"path": "b.txt", "mode": "overwrite"}, resp)
    print("YIELDS:"); [print(" ", y.rstrip()) for y in yields]
    print("OUTCOME:", outcome.data)
    print("NEXT_PROMPT (head 200):", (outcome.next_prompt or "")[:200].replace("\n", " | "))
    p = os.path.join(tmp, "b.txt")
    written = open(p, encoding='utf-8').read()
    print("FILE CONTENT:", repr(written))
    assert "PART_A_LINE_1" in written
    assert "PART_A_LINE_4_TAIL_ANCHOR_HERE_XYZ" in written
    assert "max_tokens" not in written, "truncation marker leaked into file!"
    assert outcome.data['status'] == 'truncated_continuing'
    rs = h.working.get('_file_write_resume')
    assert rs is not None, "resume state not set"
    assert rs['path'] == p
    assert rs['round'] == 1
    assert rs['tail'].endswith("TAIL_ANCHOR_HERE_XYZ"), f"tail={rs['tail']!r}"
    assert "继续" in (outcome.next_prompt or "")
    print(f"✅ PASS: wrote {len(written)}B, resume state set (round=1, tail=...{rs['tail'][-30:]!r})")

    # ============ TEST 3: Continuation with overlap (dedup) ============
    header("TEST 3: Continuation with overlap dedup (final chunk)")
    # LLM resumes; intentionally repeats last ~25 chars as overlap anchor
    overlap = rs['tail'][-25:]  # repeat trailing 25 chars
    continuation_content = overlap + "PART_B_LINE_5\nPART_B_LINE_6\nFINAL"
    cont_resp = MockResponse(f"<file_content>{continuation_content}</file_content>")
    yields, outcome = run_tool(h, {"path": "b.txt", "mode": "overwrite"}, cont_resp)
    print("YIELDS:"); [print(" ", y.rstrip()) for y in yields]
    print("OUTCOME:", outcome.data)
    final = open(p, encoding='utf-8').read()
    print("FINAL FILE:", repr(final))
    # Must NOT contain the overlap twice
    assert final.count("TAIL_ANCHOR_HERE_XYZ") == 1, f"overlap not deduped, count={final.count('TAIL_ANCHOR_HERE_XYZ')}"
    assert final.endswith("PART_B_LINE_5\nPART_B_LINE_6\nFINAL")
    assert outcome.data['status'] == 'success'
    assert h.working.get('_file_write_resume') is None, "resume state should be cleared"
    print("✅ PASS: overlap deduped, file completed, resume state cleared")

    # ============ TEST 4: Continuation that ALSO gets truncated ============
    header("TEST 4: Continuation again truncated (multi-round)")
    h.working = {}
    # Round 1
    r1 = MockResponse("<file_content>AAAA_BBBB_CCCC_DDDD_EEEE_FFFF_GGGG_HHHH_IIII_JJJJ_KKKK_LLLL_MMMM_NNNN_OOOO_PPPP_QQQQ_RRRR_SSSS_TTTT\n[!!! max_tokens !!!]")
    _, oc1 = run_tool(h, {"path": "c.txt"}, r1)
    assert oc1.data['status'] == 'truncated_continuing'
    assert h.working['_file_write_resume']['round'] == 1
    # Round 2 (also truncated)
    tail1 = h.working['_file_write_resume']['tail']
    r2 = MockResponse(f"<file_content>{tail1[-20:]}_UUUU_VVVV_WWWW\n[!!! max_tokens !!!]")
    _, oc2 = run_tool(h, {"path": "c.txt"}, r2)
    assert oc2.data['status'] == 'truncated_continuing'
    assert h.working['_file_write_resume']['round'] == 2, f"round={h.working['_file_write_resume']['round']}"
    # Round 3 (complete)
    tail2 = h.working['_file_write_resume']['tail']
    r3 = MockResponse(f"<file_content>{tail2[-20:]}_END</file_content>")
    _, oc3 = run_tool(h, {"path": "c.txt"}, r3)
    assert oc3.data['status'] == 'success'
    assert h.working.get('_file_write_resume') is None
    final_c = open(os.path.join(tmp, "c.txt"), encoding='utf-8').read()
    print("FINAL c.txt:", final_c)
    assert final_c.startswith("AAAA_BBBB")
    assert final_c.endswith("_END")
    # Each tail should appear once (dedup worked)
    assert final_c.count("UUUU_VVVV_WWWW") == 1
    print("✅ PASS: 3-round continuation, all dedup correct")

    print("\n" + "="*60)
    print("  🎉 ALL 4 TESTS PASSED")
    print("="*60)
finally:
    shutil.rmtree(tmp, ignore_errors=True)
