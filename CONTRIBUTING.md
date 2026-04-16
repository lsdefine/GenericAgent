# Contributing to GenericAgent

Thanks for your interest in contributing! GenericAgent is a minimal, self-evolving autonomous agent framework. Here are some guidelines to help you get started.

## Code Style

- **Python**: Follow [PEP 8](https://pep8.org/) with 4-space indentation.
- **Type hints**: Use `typing` annotations where practical for function signatures.
- **Dataclasses**: Use `@dataclass` for structured data objects (see `agent_loop.py`).
- **Generators**: Use `yield from` for nested generators; wrap with `try_call_generator` helper.
- **No heavy dependencies**: Keep the core lightweight. If a new dependency is needed, open an issue first.

## Project Structure

```
GenericAgent/
├── agent_loop.py      # Core agent loop (~100 lines)
├── llmcore.py         # LLM provider abstraction
├── agentmain.py       # Main entry point
├── memory/            # Layered memory system
├── reflect/           # Reflection and crystallization
├── frontends/         # UI frontends (Streamlit, Qt, Telegram)
├── tests/             # Unit and integration tests
└── launch.pyw         # Desktop launcher
```

## Branch Strategy

- `main` — stable release
- Work on feature branches: `feature/your-feature-name`
- Submit PRs against `main`

## PR Checklist

- [ ] Run existing tests: `python -m pytest tests/`
- [ ] Add tests for new functionality
- [ ] Keep core files focused (avoid bloating `llmcore.py` / `simphtml.py`)
- [ ] Update relevant docs if behavior changes
- [ ] PR title: short summary (< 72 chars)

## Testing

```bash
# Unit tests
python -m pytest tests/test_minimax.py -v

# Integration tests (requires API key)
python -m pytest tests/test_minimax_integration.py -v
```

## Reporting Issues

- Use issue templates (Bug Report / Feature Request / Question)
- Search existing issues before opening a new one
- For bugs: include Python version, OS, and minimal reproduction steps

## Questions?

Open a Discussion or ask in the issues. Welcome aboard!
