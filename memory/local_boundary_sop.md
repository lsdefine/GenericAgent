# Local Boundary SOP

Use this when changing GenericAgent itself, adding local capabilities, or reviewing upstream updates.

## Ownership Boundary

- GA core source means tracked Python code, tool schemas, frontend adapters, assets, and upstream docs.
- Do not modify GA core source unless the user explicitly asks for a core patch.
- Local/user-specific behavior should live in ignored local memory/SOP notes, environment-backed config, `local_ga/` wrappers, or external tooling.
- `.omx/` is Codex/OmniCodex workspace state only. GenericAgent should not treat `.omx/` as its own capability source.

## Preferred Extension Path

1. First use existing GA tools, prompts, memory, and SOPs.
2. If a workflow becomes reusable, write a concise SOP under local ignored memory.
3. If code is needed, prefer an ignored `local_ga/` wrapper or external script outside GA core.
4. Only patch core when upstream has no supported extension point and the user approves.

## Slash Commands

- Slash commands such as `/think`, `/check`, `/read`, and `/hunt` are local wrapper features.
- Implement slash command expansion outside GA core, then pass the transformed prompt into normal GA execution.
- Do not patch `agentmain.py`, `ga.py`, tool schemas, or frontend adapters just to add local slash commands.

## Upstream Update Check

When GA is updated or upstream changes are reviewed:

1. Read upstream README, CONTRIBUTING, relevant source, and changelog/commit diff.
2. Compare upstream capabilities against local needs: nmem, bot entrypoints, local memory rules, and personal workflow commands.
3. If upstream now covers a local need, prefer upstream behavior and remove the local workaround.
4. If upstream does not cover it, keep the local extension outside core when possible.
5. If a core patch is unavoidable, summarize the exact files, conflict risk, and why memory/SOP/wrapper is insufficient before editing.
