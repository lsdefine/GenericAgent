# Repository Agent Instructions

## Scope

- Follow `README.md`, `GETTING_STARTED.md`, and the existing Python entry points before adding new abstractions.
- Treat `mykey.py` and any local credential files as private local state; never print or commit real keys.
- Do not commit secrets, tokens, cookies, generated credentials, browser profiles, private logs, or local machine paths.

## Commands

- Launch app: `python launch.pyw`.
- CLI/helper entry: use `Start-GenericAgent-CLI.ps1` when the task is about the local CLI wrapper.
- Install dependencies only after checking the README and existing environment notes.

## Verification

For Python changes, run the narrowest import, smoke, or entry-point check that does not require real credentials or account actions. For docs-only changes, inspect the touched Markdown and referenced paths.

## Git

- Preserve unrelated dirty changes.
- Do not rewrite history, delete branches, push, publish, or open PRs without explicit confirmation.
