# Personal Agent Harness Design

## Goal

Build GenericAgent toward a personal assistant direction by adding a thin, reusable agent harness around the existing minimalist kernel.

The goal is not to turn GenericAgent into a large agent OS. The goal is to keep the GenericAgent core valuable:

- minimal loop
- skill crystallization
- layered memory
- token efficiency

And gradually add the reliability features usually found in heavier systems:

- session isolation
- recovery
- lightweight orchestration
- capability governance
- worktree isolation for development tasks
- memory promotion gates

## Source Influences

This design combines three families of ideas while keeping their boundaries separate.

### GenericAgent

GenericAgent remains the kernel model:

- a small ReAct-style agent loop
- a small atomic toolset
- L1-L4 layered memory
- trajectory-to-skill crystallization
- low context budget and high information density

The harness must not force large orchestration concepts into `agent_loop.py`.

### FuXi / Hermes Workflow Design

FuXi contributes boundary discipline, not a coupled implementation:

- a controller owns workflow state
- a worker executes a bounded brief
- worktrees isolate code-writing tasks
- policies define concurrency, locks, risk, verification, and cleanup
- skills and MCP are installed capabilities, not implicit core behavior
- run records are the recoverable truth of a task execution

FuXi's GitHub Issue / PR workflow is too heavy for the default personal assistant path. The useful part is the separation between control plane, execution worker, artifacts, and policy.

### Pi-Style Minimal Runtime

Pi contributes the preference for simple provider abstraction, small session runtime, and lightweight architecture. The harness should start with plain files, dataclasses, and narrow adapters before introducing databases, daemons, or distributed orchestration.

## Core Principle

Do not duplicate wheels, but do not let wheels decide the architecture.

Adoption order:

1. Reuse directly.
2. Wrap with an adapter.
3. Patch thinly.
4. Fork or vendor only when a stable boundary requires it.
5. Replace only when an existing wheel breaks core goals.

Unified design comes from contracts, not from rewriting all implementations.

## Layer Boundaries

### Agent Kernel

Owns:

- LLM turn loop
- tool call dispatch
- per-turn summaries
- minimal action/result cycle

Does not own:

- session lifecycle
- worktree allocation
- MCP installation
- skill installation
- global memory promotion policy
- concurrency governance

Existing anchor: `agent_loop.py`.

### Session Runtime

Owns one conversation or task thread:

- session id
- default cwd
- active agent instance
- session history
- checkpoint
- status
- local run records
- session-scoped memory

Does not own:

- global scheduling policy
- cross-session locks
- global memory write decisions
- capability installation

Existing anchors: `frontends/desktop_bridge.py`, `agentmain.GenericAgent`.

### Capability Layer

Owns installable and enableable capabilities:

- built-in atomic tools
- MCP servers
- skills
- local scripts
- provider adapters
- external workers such as Codex

Capabilities are not the workflow controller. They must declare:

- name
- type
- source
- version or commit when applicable
- install scope
- permissions
- enabled sessions
- verification command or dry run

MCP is an external tool interface. Skill is an external capability or reusable workflow fragment. Neither should become kernel logic.

### Workflow Layer

Owns task-level tool composition:

- development task workflow
- research task workflow
- scheduled task workflow
- review workflow
- delivery workflow

A workflow is a bounded recipe. It can call tools, skills, MCP, and workers, but it does not own process lifecycle or global policy.

### Harness Layer

Owns the control plane:

- session registry
- run ledger
- cancellation
- recovery
- worktree leases
- resource locks
- capability enablement
- policy gates
- memory promotion queue
- verification routing

The harness should remain thin. It manages lifecycle and boundaries; it does not reason through the user's task.

## Core Contracts

### TaskBrief

A bounded execution contract for one run.

Fields:

- `goal`
- `scope`
- `non_goals`
- `inputs`
- `acceptance`
- `risk_level`
- `verification`
- `handoff_rules`

For development tasks, FuXi's Agent Brief is the richer upstream pattern. The personal harness should start with a lighter TaskBrief that can later map to GitHub Issues or PRs when needed.

### SessionManifest

The durable identity of a session.

Fields:

- `session_id`
- `title`
- `kind`: `chat`, `development`, `research`, `scheduled`, `review`
- `created_at`
- `updated_at`
- `status`
- `root_cwd`
- `session_temp_dir`
- `session_memory_dir`
- `default_runtime`
- `capability_scope`
- `worktree`
- `active_run_id`

Session manifests make sessions recoverable without turning the system into a daemon-first OS.

### RunLedger

The durable execution record for one task run.

Fields:

- `run_id`
- `session_id`
- `brief_id`
- `runtime`
- `cwd`
- `status`
- `pid`
- `started_at`
- `updated_at`
- `ended_at`
- `log_path`
- `artifacts`
- `verification`
- `failure_reason`
- `next_action`

RunLedger is the source of recovery and debugging. It should be append-friendly and human-readable.

### CapabilityManifest

The inventory and policy for tools, MCP servers, skills, and workers.

Fields:

- `name`
- `type`
- `source`
- `install_scope`
- `enabled`
- `permissions`
- `verification`
- `owner`
- `notes`

No silent installation. New capabilities follow:

```text
Inventory -> Gap report -> Approval -> Install -> Verify -> Enable
```

### WorktreeLease

A bounded file-system lease for development tasks.

Fields:

- `lease_id`
- `session_id`
- `run_id`
- `kind`: `session` or `execution`
- `path`
- `branch`
- `base_ref`
- `mode`: `read` or `write`
- `lock_keys`
- `created_at`
- `status`

Two levels are supported:

- Session worktree: the main development workspace for a development session.
- Execution worktree: a temporary sandbox for parallel or high-risk attempts.

Harness owns worktree allocation. Agents and external workers request leases; they do not invent paths.

### MemoryPromotionRecord

A proposal to move session-local learning into global memory or a reusable skill.

Fields:

- `promotion_id`
- `session_id`
- `run_id`
- `source_artifact`
- `target_layer`: `L1`, `L2`, `L3`, `L4`, or `skill`
- `claim`
- `evidence`
- `risk`
- `status`: `proposed`, `accepted`, `rejected`, `needs_review`

Rule: no execution, no memory. Global memory is not written directly by ordinary runs.

## Session And Memory Model

Sessions are independent by default:

- independent history
- independent checkpoint
- independent working memory
- independent temp directory
- independent run logs
- optional independent worktree

Sessions may contribute to shared memory only through promotion:

```text
session memory -> promotion queue -> harness review -> global L1/L2/L3/L4 or skill
```

This preserves long-term learning without memory pollution.

## Concurrency Model

The current code can run multiple `GenericAgent` instances in one Python process using threads. This is acceptable for short IO-heavy sessions, but not enough for safe parallel development.

Default model:

- Thread runtime: short chat, small research, lightweight tasks.
- Process runtime: long tasks, development tasks, worker tasks, recoverable tasks.

Development model:

```text
one development session = one session worktree
parallel or high-risk execution = one execution worktree
```

Same session, serial development:

- use the session worktree

Same session, parallel attempts:

- create execution worktrees
- compare results
- merge or cherry-pick into the session worktree

Multiple development sessions:

- each has its own session worktree

Protected areas use lock keys:

- auth
- database-schema
- payments
- ci
- deployment
- data-deletion

This is intentionally lighter than Hermes, but borrows FuXi's lock discipline.

## Capability Governance

Capabilities are external and pluggable.

Rules:

- MCP servers are external tool providers.
- Skills are installable capability modules or workflow fragments.
- Workflows compose capabilities.
- Harness decides whether a capability is enabled for a session.
- Kernel only sees mounted tools.

When a wheel is insufficient:

1. Identify whether the missing part is interface, lifecycle, permission, state, recovery, or verification.
2. Prefer adapter for interface mismatch.
3. Prefer harness wrapper for lifecycle and recovery.
4. Prefer policy wrapper for permission gaps.
5. Prefer schema and ledger for output control.
6. Patch or replace only when the capability itself is unreliable.

## Non-Goals

This design does not aim to:

- build a full Hermes clone
- require GitHub Issue / PR for every personal task
- make MCP core to the kernel
- make skills globally enabled by default
- turn every run into a new worktree
- allow agents to silently install capabilities
- let sessions directly overwrite global memory
- add distributed orchestration before local recovery works

## First Milestone

The first milestone should establish durable boundaries without changing the agent loop:

1. Add plain-file contracts for sessions, runs, capabilities, worktrees, and memory promotions.
2. Persist session manifests and run ledgers.
3. Integrate the desktop bridge with the manifest store without changing user-facing behavior.
4. Add a process runtime for development sessions.
5. Add worktree leases for development sessions.
6. Add a memory promotion queue before global memory writes.

Each step must be independently testable and revertible.
