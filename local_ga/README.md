# Local GA Slash Commands

This directory is a local wrapper layer. It is not GA core source.

## CLI

```bash
python local_ga/run_cli_with_slash.py --commands
python local_ga/run_cli_with_slash.py --input "/think 规划一个资料整理流程"
```

Supported commands:

- `/think`
- `/design`
- `/check`
- `/hunt`
- `/write`
- `/learn`
- `/read`
- `/health`

Skills are loaded from `GA_SLASH_SKILL_ROOTS`, `~/.claude/skills`, `~/.agents/skills`, and `~/.codex/skills`.
