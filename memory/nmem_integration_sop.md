# nmem Integration SOP

Use this SOP when a task depends on prior context, user preferences, previous deployment decisions, or reusable procedures.

## Quick Checks

- Use `nmem(action="status")` before relying on memory during setup or debugging.
- Use `nmem(action="working_memory")` at the start of continuation-style work.
- Use `nmem(action="search", query="...", mode="normal")` for normal recall.
- Use `mode="deep"` only when normal search is weak or the topic is conceptual.

## Saving

Use `nmem(action="add", ...)` only for durable, verified facts, decisions, procedures, or user preferences.

Never save API keys, bot tokens, cookies, session secrets, private credentials, or raw secret-bearing config.

## GenericAgent Deployment Notes

- Current local deployment reads bot and model credentials from `mykey.py`, which should read environment variables rather than hard-code secrets.
- Telegram frontend: `frontends/tgapp.py`.
- Feishu frontend: `frontends/fsapp.py`.
- For bot access control, keep allowed-user lists configured before starting public adapters.
