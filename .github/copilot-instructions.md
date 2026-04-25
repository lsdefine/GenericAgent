# Copilot Instructions for GenericAgent

This repository is an upstream GenericAgent checkout with local overlays.

## Main Rule

Do not modify upstream GenericAgent source files by default. Put local slash commands, nmem glue, bot launch wrappers, and personal workflow code in `local_ga/`, local `memory/`, or external wrappers.

`.omx/` is Codex/OmniCodex workspace state only. Do not make GenericAgent runtime depend on `.omx/`.

## Treat As Upstream Source

- `agentmain.py`
- `agent_loop.py`
- `ga.py`
- `llmcore.py`
- `assets/`
- `frontends/`
- `memory/`
- `reflect/`
- `tests/`

Ask before changing these unless the user explicitly requests a source change.

## Treat As Local Overlay

- `.omx/`
- `local_ga/`
- `RUNBOOK_LOCAL.md`
- `GENERIC_AGENT_HANDBOOK.md`
- `kb/`

## Local nmem Hook

nmem session auto-sync is a local overlay, not upstream GenericAgent behavior.

Use:

```bash
./.omx/ga_nmem_hook/run_cli.sh
./.omx/ga_nmem_hook/run_launch.sh
```

## Git Safety

Do not stage `.omx/`, secrets, cookies, or runtime state. Before suggesting a pull or merge, check `git status --short`.
