# Personal Agent Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a thin Personal Agent Harness around GenericAgent so sessions, runs, worktrees, capabilities, and memory promotion are durable and isolated without changing the minimalist agent loop.

**Architecture:** Keep `agent_loop.py` and the core tool loop unchanged. Add focused harness modules for contracts, file-backed stores, worktree leases, capability manifests, and memory promotion gates, then integrate them gradually into `frontends/desktop_bridge.py` and later `frontends/conductor.py`.

**Tech Stack:** Python standard library, JSON files, dataclasses, `unittest`, existing GenericAgent modules, Git CLI for worktree operations.

---

## File Map

- Create `harness/__init__.py`: marks the harness package and exports stable public symbols later.
- Create `harness/contracts.py`: dataclasses and JSON serialization for `SessionManifest`, `RunLedger`, `CapabilityManifest`, `WorktreeLease`, `MemoryPromotionRecord`, and `TaskBrief`.
- Create `harness/store.py`: atomic-ish JSON file store for sessions, runs, and promotion records.
- Create `harness/worktrees.py`: Git worktree lease allocation and cleanup helpers.
- Create `harness/capabilities.py`: read and validate capability manifest files.
- Create `harness/memory_promotion.py`: queue and approve/reject memory promotion records.
- Modify `frontends/desktop_bridge.py`: attach session manifests and run ledgers while preserving existing API behavior.
- Modify `frontends/conductor.py`: later reuse run ledger and subagent run status.
- Create `tests/harness/test_contracts.py`: serialization and default tests.
- Create `tests/harness/test_store.py`: file store behavior.
- Create `tests/harness/test_worktrees.py`: Git worktree command construction and dry-run behavior.
- Create `tests/harness/test_memory_promotion.py`: promotion gate behavior.
- Create `docs/personal-agent-harness.md`: user-facing summary once the first milestone is implemented.

## Global Constraints

- Do not modify `agent_loop.py` in the first milestone.
- Do not install dependencies.
- Do not require a daemon.
- Do not make GitHub Issues mandatory.
- Do not enable MCP or skills implicitly.
- Do not let normal runs write global memory directly.
- Do not commit unless the user explicitly authorizes a commit.

## Task 1: Add Harness Contract Dataclasses

**Files:**

- Create: `harness/__init__.py`
- Create: `harness/contracts.py`
- Test: `tests/harness/test_contracts.py`

- [ ] **Step 1: Write tests for contract round trips**

Create `tests/harness/test_contracts.py` with `unittest` cases that instantiate each contract, convert it to dict, convert it back, and verify stable fields.

Expected contracts:

- `TaskBrief`
- `SessionManifest`
- `RunLedger`
- `CapabilityManifest`
- `WorktreeLease`
- `MemoryPromotionRecord`

- [ ] **Step 2: Run tests and verify they fail because the package does not exist**

Run:

```bash
python3 -m unittest tests.harness.test_contracts -v
```

Expected: import failure for `harness.contracts`.

- [ ] **Step 3: Implement `harness/contracts.py`**

Use only dataclasses, `asdict`, and explicit `from_dict` constructors. Store timestamps as ISO-like strings supplied by callers or helper functions. Keep contract code pure and independent from GenericAgent.

- [ ] **Step 4: Run contract tests**

Run:

```bash
python3 -m unittest tests.harness.test_contracts -v
```

Expected: all contract tests pass.

- [ ] **Step 5: Run syntax check**

Run:

```bash
python3 -m compileall -q harness tests
```

Expected: no output and exit code 0.

## Task 2: Add File-Backed Harness Store

**Files:**

- Modify: `harness/contracts.py`
- Create: `harness/store.py`
- Test: `tests/harness/test_store.py`

- [ ] **Step 1: Write store tests**

Cover:

- creating a store at a temporary root
- saving and loading a `SessionManifest`
- appending and loading `RunLedger` records
- listing sessions
- rejecting path traversal session ids

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
python3 -m unittest tests.harness.test_store -v
```

Expected: import failure or missing methods.

- [ ] **Step 3: Implement `HarnessStore`**

Design:

```text
<root>/
  sessions/<session_id>/manifest.json
  sessions/<session_id>/runs/<run_id>.json
  memory_promotions/<promotion_id>.json
```

Use `tempfile.NamedTemporaryFile` plus `os.replace` for writes. Reject ids containing path separators, `..`, or empty strings.

- [ ] **Step 4: Run store tests**

Run:

```bash
python3 -m unittest tests.harness.test_store -v
```

Expected: all store tests pass.

## Task 3: Persist Desktop Session Manifests Without Behavior Change

**Files:**

- Modify: `frontends/desktop_bridge.py`
- Modify: `harness/store.py`
- Test: `tests/harness/test_desktop_bridge_store.py`

- [ ] **Step 1: Write tests for session manifest creation**

Use `AgentManager` with a temporary harness root. Call `create_session(cwd=tmpdir)` and assert:

- existing HTTP snapshot fields still exist
- a matching `manifest.json` is saved
- `status` starts as `idle`
- `root_cwd` equals the session cwd

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python3 -m unittest tests.harness.test_desktop_bridge_store -v
```

Expected: missing harness integration.

- [ ] **Step 3: Add optional `harness_root` to `AgentManager`**

Keep default behavior if no harness root is provided:

```text
<ga_root>/temp/harness
```

Do not change public HTTP routes.

- [ ] **Step 4: Save manifests in `create_session` and status updates**

When session status changes, update the manifest. Keep the existing in-memory `Session` object as the UI source for now.

- [ ] **Step 5: Run regression tests**

Run:

```bash
python3 -m unittest tests.harness.test_desktop_bridge_store -v
python3 -m compileall -q harness frontends/desktop_bridge.py
```

Expected: pass.

## Task 4: Add Run Ledger For Prompt Execution

**Files:**

- Modify: `frontends/desktop_bridge.py`
- Modify: `harness/store.py`
- Test: `tests/harness/test_run_ledger.py`

- [ ] **Step 1: Write run ledger tests**

Cover:

- submitting a prompt creates a run record
- run status becomes `running`
- successful completion becomes `done`
- exceptions become `failed` with a failure reason
- cancellation becomes `cancelled`

- [ ] **Step 2: Add run id to session execution**

Generate `run_id` before starting `run_agent_turn`. Store it on the session and pass it into the worker thread.

- [ ] **Step 3: Append run status changes**

Persist a `RunLedger` at:

```text
sessions/<session_id>/runs/<run_id>.json
```

Keep the log path compatible with existing `temp/model_responses`.

- [ ] **Step 4: Run ledger tests**

Run:

```bash
python3 -m unittest tests.harness.test_run_ledger -v
```

Expected: pass.

## Task 5: Add Process Runtime For Development Sessions

**Files:**

- Create: `harness/runtime.py`
- Modify: `frontends/desktop_bridge.py`
- Test: `tests/harness/test_runtime.py`

- [ ] **Step 1: Write runtime tests**

Cover:

- `ThreadRuntime` preserves current behavior.
- `ProcessRuntime` can launch a harmless Python command.
- `ProcessRuntime.cancel()` terminates a running process.
- stdout/stderr paths are recorded in the run ledger.

- [ ] **Step 2: Implement runtime adapters**

Create:

- `ThreadRuntime`
- `ProcessRuntime`

Both expose:

```python
start(run_context) -> RuntimeHandle
cancel(handle) -> None
status(handle) -> str
```

The first integration should still default to `ThreadRuntime`.

- [ ] **Step 3: Add session kind based runtime selection**

For `kind == "development"`, allow `ProcessRuntime`. Keep normal chat sessions on `ThreadRuntime`.

- [ ] **Step 4: Run runtime tests**

Run:

```bash
python3 -m unittest tests.harness.test_runtime -v
python3 -m compileall -q harness frontends/desktop_bridge.py
```

Expected: pass.

## Task 6: Add Worktree Lease Manager

**Files:**

- Create: `harness/worktrees.py`
- Test: `tests/harness/test_worktrees.py`

- [ ] **Step 1: Write dry-run worktree tests**

Cover:

- session worktree branch/path calculation
- execution worktree branch/path calculation
- invalid branch names are rejected
- dry-run mode returns commands without executing Git

- [ ] **Step 2: Implement `WorktreeManager`**

Inputs:

- repo root
- worktree root
- branch template
- path template

Methods:

- `allocate_session_worktree(session_id, slug, base_ref)`
- `allocate_execution_worktree(session_id, run_id, slug, base_ref)`
- `release_lease(lease_id, cleanup=False)`

- [ ] **Step 3: Add real Git smoke test guarded by temp repo**

Use a temporary Git repo inside the test and run:

```bash
git init
git config user.email test@example.com
git config user.name Test
```

Create one commit, allocate one worktree, and assert the path exists.

- [ ] **Step 4: Run worktree tests**

Run:

```bash
python3 -m unittest tests.harness.test_worktrees -v
```

Expected: pass.

## Task 7: Add Capability Manifest Reader

**Files:**

- Create: `harness/capabilities.py`
- Test: `tests/harness/test_capabilities.py`
- Optional later: create `.ai/capabilities.example.yml`

- [ ] **Step 1: Write manifest tests**

Cover capability types:

- `tool`
- `mcp`
- `skill`
- `worker`
- `provider`

Assert silent installation defaults to false and unverified capabilities are not enabled.

- [ ] **Step 2: Implement manifest loading**

Support YAML only if PyYAML is already installed. If not installed, support JSON first and keep YAML support behind a clear error. Do not add dependencies.

- [ ] **Step 3: Add validation errors**

Return structured validation errors for:

- missing name
- missing type
- enabled without verification
- unknown permission

- [ ] **Step 4: Run capability tests**

Run:

```bash
python3 -m unittest tests.harness.test_capabilities -v
```

Expected: pass.

## Task 8: Add Memory Promotion Queue

**Files:**

- Create: `harness/memory_promotion.py`
- Modify: `harness/store.py`
- Test: `tests/harness/test_memory_promotion.py`

- [ ] **Step 1: Write promotion tests**

Cover:

- proposed records are saved to the queue
- accepted records can be listed
- rejected records keep rejection reason
- records without evidence cannot be accepted
- global memory files are not modified by proposing a promotion

- [ ] **Step 2: Implement queue operations**

Methods:

- `propose(record)`
- `accept(promotion_id, reviewer)`
- `reject(promotion_id, reviewer, reason)`
- `list_pending()`

- [ ] **Step 3: Add a narrow adapter for existing memory writes**

Do not change existing agent memory behavior yet. Add an adapter that can later replace direct global writes.

- [ ] **Step 4: Run promotion tests**

Run:

```bash
python3 -m unittest tests.harness.test_memory_promotion -v
```

Expected: pass.

## Task 9: Integrate Development Session Worktree Allocation

**Files:**

- Modify: `frontends/desktop_bridge.py`
- Modify: `harness/worktrees.py`
- Test: `tests/harness/test_development_session.py`

- [ ] **Step 1: Write development session tests**

Cover:

- creating a `development` session allocates a session worktree
- ordinary chat sessions do not allocate worktrees
- existing main checkout is not written when worktree allocation is enabled
- worktree lease is persisted in the session manifest

- [ ] **Step 2: Add optional session kind parameter**

Extend session creation internals first. Public UI can keep default `chat`.

- [ ] **Step 3: Add worktree allocation behind config**

Default disabled until explicitly configured:

```json
{
  "worktrees": {
    "enabled": false,
    "root": "temp/worktrees"
  }
}
```

- [ ] **Step 4: Run development session tests**

Run:

```bash
python3 -m unittest tests.harness.test_development_session -v
```

Expected: pass.

## Task 10: Add Lightweight Workflow Templates

**Files:**

- Create: `docs/workflows/personal-development-task.md`
- Create: `docs/workflows/memory-promotion.md`
- Create: `docs/workflows/capability-install.md`

- [ ] **Step 1: Write development task workflow**

Include:

- task brief
- session worktree
- run ledger
- validation
- memory promotion proposal

- [ ] **Step 2: Write memory promotion workflow**

Include:

- evidence requirement
- target layer decision
- acceptance/rejection
- no direct global write rule

- [ ] **Step 3: Write capability install workflow**

Include:

```text
Inventory -> Gap report -> Approval -> Install -> Verify -> Enable
```

- [ ] **Step 4: Review docs for contradictions**

Run:

```bash
python3 - <<'PY'
from pathlib import Path

patterns = [
    "TO" + "DO",
    "TB" + "D",
    "silent install " + "allowed",
    "direct global memory write " + "allowed",
    "build a full agent " + "os",
]
for path in [*Path("docs/superpowers").rglob("*.md"), *Path("docs/workflows").rglob("*.md")]:
    text = path.read_text(encoding="utf-8", errors="replace")
    lower = text.lower()
    for pattern in patterns:
        if pattern.lower() in lower:
            print(f"{path}: contains {pattern}")
PY
```

Expected: no output.

## Task 11: Add Conductor Run Ledger Integration

**Files:**

- Modify: `frontends/conductor.py`
- Test: `tests/harness/test_conductor_runs.py`

- [ ] **Step 1: Write conductor run tests**

Cover:

- starting a subagent creates a run ledger
- subagent done updates status
- abort updates status
- chat history remains in conductor memory as before

- [ ] **Step 2: Inject optional HarnessStore into conductor helpers**

Keep current global behavior when store is absent.

- [ ] **Step 3: Persist subagent lifecycle events**

Map:

- `running`
- `stopped`
- `failed`
- `aborted`

to run ledger statuses.

- [ ] **Step 4: Run conductor tests**

Run:

```bash
python3 -m unittest tests.harness.test_conductor_runs -v
```

Expected: pass.

## Task 12: End-To-End Smoke Verification

**Files:**

- No new files required unless failures reveal missing tests.

- [ ] **Step 1: Run unit tests**

Run:

```bash
python3 -m unittest discover -s tests -v
```

Expected: pass.

- [ ] **Step 2: Run syntax check**

Run:

```bash
python3 -m compileall -q agent_loop.py agentmain.py ga.py hub.pyw launch.pyw llmcore.py simphtml.py TMWebDriver.py assets frontends ga_cli memory plugins reflect harness tests
```

Expected: pass.

- [ ] **Step 3: Review diff**

Run:

```bash
git diff --stat
git diff -- docs/superpowers docs/workflows harness tests frontends/desktop_bridge.py frontends/conductor.py
```

Expected: changes match this plan and do not touch unrelated files.

- [ ] **Step 4: Manual behavior check**

Start the existing UI or bridge exactly as before and create a normal chat session. Confirm existing session creation and prompt submission still work.

Record what was verified in the final implementation summary.

## Milestone Order

1. Tasks 1-2: contracts and store.
2. Tasks 3-4: desktop session manifest and run ledger.
3. Tasks 5-6: process runtime and worktree leases.
4. Tasks 7-8: capability and memory promotion gates.
5. Tasks 9-10: development session workflow.
6. Tasks 11-12: conductor integration and smoke verification.

## Stop Conditions

Stop and ask before proceeding if implementation requires:

- changing `agent_loop.py`
- changing tool schemas
- installing new dependencies
- changing public API response structures
- writing to global memory automatically
- enabling MCP by default
- deleting worktrees or branches
- changing authentication, token, or credential behavior

## Execution Choice

This plan is ready for review. Implementation should start only after choosing one mode:

1. Subagent-driven execution: one fresh worker per task, with review between tasks.
2. Inline execution: complete tasks in this session with checkpoints.

No commit should be made unless explicitly authorized.
