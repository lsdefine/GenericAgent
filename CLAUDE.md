# GenericAgent Project Instructions

This is the Claude Code project instruction file.

## Local Rule

Treat this checkout as upstream GenericAgent plus local overlays. Do not edit upstream source files by default. Put slash commands, nmem glue, bot launch wrappers, and other local behavior in `local_ga/`, local `memory/`, or external wrappers.

`.omx/` is Codex/OmniCodex workspace state, not a GenericAgent runtime capability source.

## Do Not Edit By Default

- `agentmain.py`
- `agent_loop.py`
- `ga.py`
- `llmcore.py`
- `assets/tools_schema*.json`
- `frontends/*.py`
- `memory/*.md`
- `reflect/*.py`

Only edit those files when the user explicitly asks or when an upstream-source fix is truly required.

## Local Extensions

- nmem session sync: `.omx/ga_nmem_hook/`
- local slash command wrapper: `local_ga/`
- local docs and rules: `.omx/local_docs/`
- local runbook: `RUNBOOK_LOCAL.md`
- local KB: `kb/`

## Verification

Before saying work is complete, run a relevant check and report whether GA source files were touched.
