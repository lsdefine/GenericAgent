# learn_skill_from_cases — English-only Skill Learning CLI

A streamlined skill learning tool. **English input only** — provide skill names in pure English.

## Usage

```bash
# Learn a skill
python -m tools.learn_skill_from_cases "docker_compose_production"

# List learned skills
python -m tools.learn_skill_from_cases --list

# Show skill details
python -m tools.learn_skill_from_cases --show docker_compose_production

# Dry run (preview without creating files)
python -m tools.learn_skill_from_cases "python_async" --dry-run

# Force refresh (skip inheriting previous patterns)
python -m tools.learn_skill_from_cases "neo4j_modeling" --force

# Show version
python -m tools.learn_skill_from_cases --version
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `SKILL_LLM_ENABLE` | `0` | Set to `1` to enable LLM enhancement |
| `LLM_API_BASE` | `http://localhost:11434/v1` | OpenAI-compatible API endpoint |
| `LLM_API_KEY` | — | API key if required |
| `LLM_MODEL` | `qwen2.5:7b` | Model name |
| `LLM_TIMEOUT` | `30` | HTTP timeout in seconds |

## Output Structure

```
GA_ROOT/skills_learning/
  └── {skill_name}/
      ├── rev{N}/
      │   ├── meta.json
      │   ├── cases/all_cases.json
      │   ├── patterns/knowledge_patterns.json
      │   ├── tools/assess.py
      │   ├── reports/learning_report.md
      │   ├── reports/skill_definition.json
      │   └── practice/
      └── ...
```

## Phase Flow

The tool runs a 5-phase pipeline:

1. **Bootstrap** — create version directory
2. **Define** — fetch skill definition
3. **Search** — collect web cases
4. **Extract** — derive knowledge patterns
5. **Validate** — run assessment and score
