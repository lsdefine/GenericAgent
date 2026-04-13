# Provider Configuration Guide

AIbubu monitors AI coding tools through **TOML provider files**. Each `.toml` file in this directory defines how to detect and measure activity for one tool.

## Architecture

```
providers/
├── cursor.toml          # ✅ Verified — ships with the app
├── claude-code.toml     # ✅ Verified
├── codex-cli.toml       # ✅ Verified
├── trae.toml            # ✅ Verified
└── README.md            # ← You are here
```

- All `.toml` files in this directory are loaded at runtime and ship with the app.

## Adapter Types

Each provider uses an **adapter** to detect activity. Choose the one that best fits your tool:

### `sqlite` — Database polling

Best for: IDE-based tools that store state in a local SQLite database (e.g. Cursor, Windsurf).

```toml
[detect]
adapter = "sqlite"
[detect.paths]
macos = "${APP_SUPPORT}/ToolName/User/globalStorage/state.vscdb"
linux = "${HOME}/.config/ToolName/User/globalStorage/state.vscdb"
windows = "${APPDATA}/ToolName/User/globalStorage/state.vscdb"

[activity]
adapter = "sqlite"
[activity.sqlite]
latest_query = """
SELECT timestamp_col as ts, status_col as status
FROM tableName
ORDER BY timestamp_col DESC LIMIT 1
"""
timestamp_field = "ts"
status_field = "status"              # optional
metrics_fields = ["lines_added"]     # optional

[activity.status_map]                # optional: map status values → activity levels
generating = "active_high"
```

### `jsonl` — JSON Lines log parsing

Best for: CLI tools that write session logs as `.jsonl` files (e.g. Claude Code, Codex CLI).

```toml
[detect]
adapter = "jsonl"
[detect.paths]
macos = "${HOME}/.tool/sessions/"
linux = "${HOME}/.tool/sessions/"
windows = "${HOME}/.tool/sessions/"

[activity]
adapter = "jsonl"
[activity.jsonl]
file_pattern = "*.jsonl"
timestamp_field = "timestamp"
```

### `process` — Process CPU monitoring

Best for: Tools where only a running process can be detected (e.g. Trae).

```toml
[detect]
adapter = "process"

[activity]
adapter = "process"
[activity.process]
names = ["tool-name", "tool-helper"]
cpu_active_threshold = 5.0           # CPU% above which = active
```

### `file_mtime` — File modification time

Best for: Tools that write to local files but not in JSONL or SQLite format.

```toml
[detect]
adapter = "file_mtime"
[detect.paths]
macos = "${HOME}/.tool/"
linux = "${HOME}/.tool/"
windows = "${HOME}/.tool/"

[activity]
adapter = "file_mtime"
[activity.file_mtime]
watch_pattern = "sessions/**/*.json"
```

### `vscode_ext` — VS Code extension storage

Best for: VS Code extensions that store conversation data in `globalStorage/` (e.g. Cline family).

```toml
[[variants]]
id = "extension-name"
name = "Extension Name"
extension_id = "publisher.extension-id"

[detect]
adapter = "vscode_ext"
[detect.paths]
macos = "${APP_SUPPORT}/${IDE}/User/globalStorage/${EXT_ID}/tasks/"
linux = "${HOME}/.config/${IDE}/User/globalStorage/${EXT_ID}/tasks/"
windows = "${APPDATA}/${IDE}/User/globalStorage/${EXT_ID}/tasks/"

[activity]
adapter = "vscode_ext"
```

## Common Fields

### `[meta]` — Required

```toml
[meta]
id = "tool-id"           # Unique identifier (lowercase, kebab-case)
name = "Tool Name"        # Display name
category = "cli"          # One of: ide, cli, extension
priority = 8              # 1–10, higher = checked first (default: 5)
```

### `[process_fallback]` — Optional

Adds a secondary process-based check as fallback when the primary adapter finds nothing.

```toml
[process_fallback]
enabled = true
names = ["tool-process"]
parent_exclude = ["cursor", "code"]  # optional: skip if parent matches
```

### Path Variables

| Variable         | Expands to                                                                       |
| ---------------- | -------------------------------------------------------------------------------- |
| `${HOME}`        | User home directory                                                              |
| `${APP_SUPPORT}` | macOS: `~/Library/Application Support`, Linux: `~/.config`, Windows: `%APPDATA%` |
| `${APPDATA}`     | Windows `%APPDATA%`                                                              |

## Adding a New Provider

### Step 1: Identify the detection method

Find how the tool stores activity data:

- Check `~/Library/Application Support/` (macOS) or `~/.config/` (Linux) for database or log files
- Run `ps aux | grep tool-name` to find process names
- Look for JSONL logs, SQLite databases, or config files

### Step 2: Create the TOML file

Start from the template above that matches your adapter type. Save as `providers/your-tool.toml`.

### Step 3: Test locally

```bash
# Run the app in dev mode
pnpm dev

# Watch the terminal for monitor logs like:
# monitor: scan — cursor(ActiveHigh) your-tool(ActiveMedium)  score=85
```

### Step 4: Verify on all platforms

The provider should work on at least **one** platform, with correct paths for all three:

- macOS (`macos` path)
- Linux (`linux` path)
- Windows (`windows` path)

### Step 5: Submit

1. Run `node scripts/validate-providers.js` to check your TOML
2. Ensure the file is in the root `providers/` directory
3. Open a PR with evidence of successful detection (terminal logs or screenshots)

## Validation

Run the provider validator to check all TOML files:

```bash
node scripts/validate-providers.js
```

This checks:

- TOML syntax
- Required fields (`meta.id`, `meta.name`, `meta.category`, `detect.adapter`, `activity.adapter`)
- Adapter-specific config blocks match the declared adapter type
