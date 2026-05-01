# Auto Route Long-term Maintenance

## Goal
Keep cross-frontend auto-routing integration stable across frequent upstream updates.

## Scope
- This document is the source of truth for auto-routing maintenance.
- Do not force-write global memory from automation.
- Use manual reminders to let GA follow its own memory governance and classify knowledge into proper memory layers.

## Restore Principle (Hard Rule)
- Recovery only restores auto-routing related wiring.
- Recovery must not override normal upstream feature updates.
- If exact wiring anchors are not found, self-heal fails fast instead of force-writing.
- Any ambiguous change requires manual review rather than broad replacement.

## Already Enforced in Code
- Startup self-heal: `scripts/auto_route_self_heal.py`
- Startup guard test: `tests/test_frontend_agent_factory_guard.py`
- Unified agent entry: `agent_factory.py`
- Default global switch at startup: `GA_AUTO_ROUTE_ALL_FRONTENDS=1`

## Daily Startup Behavior
Every startup now runs:
1. self-heal for frontend wiring
2. guard test verification
3. normal app startup only if checks pass

Self-heal uses minimal, scoped edits:
- import rewrite only for `from agentmain import GeneraticAgent` -> `from agent_factory import create_agent`
- constructor rewrite only for known `agent = GeneraticAgent()` statements
- unmatched `GeneraticAgent(...)` occurrences are reported and block startup

## Manual Reminder Playbook (Recommended)
When you want GA to actively remember and classify this topic through its own memory system, use one of the reminders below.

### Reminder A: Post-update verification
"请按项目既有记忆管理体系执行：先阅读 AUTO_ROUTE_MAINTENANCE.md，再检查自动路由接入是否被更新覆盖；如发现问题，仅做自动路由相关最小修复，并把结论按既有流程归档到合适记忆层。"

### Reminder B: Incident handling
"自动路由疑似失效。请先依据 AUTO_ROUTE_MAINTENANCE.md 排查并修复，遵守最小变更原则，不覆盖正常更新；最后输出你依据了哪些规则与证据。"

### Reminder C: Periodic health check
"请做一次自动路由健康检查：执行自检、护栏测试、差异说明，并根据项目记忆治理规则决定是否需要写入记忆。"

## Incident Triage Checklist
Use this order to reduce false fixes:
1. Run self-heal check-only.
2. Run guard test.
3. If failed, inspect only affected frontend wiring lines.
4. Apply minimal routing-related recovery only.
5. Re-run guard test and startup path.
6. Summarize root cause and evidence.

Commands:
- `python scripts/auto_route_self_heal.py --check-only`
- `python -m unittest discover -s tests -p "test_frontend_agent_factory_guard.py"`
- `python scripts/auto_route_self_heal.py`

## Recommended Git Workflow (Patch Replay)
Use a dedicated integration branch to keep your local hardening easy to replay:

1. Create a long-lived branch once
   - `git switch -c auto-route-hardening`
2. Commit your hardening changes on this branch
   - `git add .`
   - `git commit -m "hardening: frontend auto-route self-heal + startup guard"`
3. When upstream updates arrive
   - `git switch main`
   - `git pull`
   - `git switch auto-route-hardening`
   - `git rebase main`
4. Resolve conflicts if needed, then verify
   - `python scripts/auto_route_self_heal.py --check-only`
   - `python -m unittest discover -s tests -p "test_frontend_agent_factory_guard.py"`

## Recovery
If a frontend file is overwritten by upstream:
1. Run `python scripts/auto_route_self_heal.py`
2. Run `python -m unittest discover -s tests -p "test_frontend_agent_factory_guard.py"`
3. Restart with `start.bat`
4. If recovery fails, do manual review on wiring anchors only (import + agent constructor lines).
5. Do not perform broad overwrite of frontend files.

## Environment Toggle
- `GA_AUTO_ROUTE_ALL_FRONTENDS=1`: enable auto-routing for non-stapp frontends
- `GA_AUTO_ROUTE_ALL_FRONTENDS=0`: disable and keep base agent behavior

## Change Safety Notes
- Self-heal is allowed to modify only auto-routing wiring related lines.
- Any unmatched pattern is treated as an intentional upstream evolution candidate, requiring human review.
- Successful startup requires both self-heal validation and guard test pass.
