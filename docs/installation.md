# Installation Guide

This is the detailed installation guide for **GenericAgent**.

Two audiences:

- **[For Humans](#for-humans)** — you are installing GA for yourself.
- **[For LLM Agents](#for-llm-agents)** — you are a coding agent such as Claude Code, or Codex installing GA for a human user. Read that section first so you do not guess.

> The shortest install commands live in the main [README](../README.md#-quick-start). This guide adds platform notes, key setup, verification, troubleshooting, and agent-safe rules.

---

## For Humans

### Prerequisites

| Requirement | Notes |
|---|---|
| **OS** | Windows 10/11, macOS 12+, or a modern Linux distribution. |
| **Python** | Use **Python 3.11 or 3.12**. **Do not use Python 3.14** — it is incompatible with `pywebview` and a few GA dependencies. The one-line installer ships an isolated Python environment, so manual Python setup is usually unnecessary. |
| **Git** | Recommended for updates and self-evolution. |
| **LLM API key** | GA speaks two native protocols: **OpenAI-compatible** APIs and **Anthropic Claude native** APIs. GPT-family models, Claude, Kimi, MiniMax, DeepSeek, GLM, Qwen, Gemini through OAI-compatible gateways, and similar providers can be configured through `mykey.py`. |

### Method 1: One-line install (recommended)

This is the easiest path. It prepares an isolated runtime, downloads GenericAgent, installs the core dependencies, and gives you a ready-to-run local project tree.

**Windows PowerShell**

```powershell
powershell -ExecutionPolicy Bypass -c "$env:GLOBAL=1; irm http://fudankw.cn:9000/files/ga_install.ps1 | iex"
```

**Linux / macOS**

```bash
GLOBAL=1 bash -c "$(curl -fsSL http://fudankw.cn:9000/files/ga_install.sh)"
```

After installation, launch the desktop app from:

```text
frontends/GenericAgent.exe
```

Or run from the project directory:

```bash
python launch.pyw
```

> GenericAgent is meant to grow its environment through the Agent itself, not by pre-installing every possible package. Start small, then let GA install task-specific tools when it actually needs them.

#### Custom install location

```bash
INSTALL_DIR="$HOME/work/GenericAgent" GLOBAL=1 bash -c "$(curl -fsSL http://fudankw.cn:9000/files/ga_install.sh)"
```

```powershell
$env:INSTALL_DIR="C:\dev\GenericAgent"; powershell -ExecutionPolicy Bypass -c "$env:GLOBAL=1; irm http://fudankw.cn:9000/files/ga_install.ps1 | iex"
```

#### Force reinstall

Use this only when you know you want to refresh the installed files. Back up `mykey.py`, `memory/`, `skills/`, and any local work first.

```bash
FORCE=1 GLOBAL=1 bash -c "$(curl -fsSL http://fudankw.cn:9000/files/ga_install.sh)"
```

### Method 2: Python install (for developers)

Use this when you want a normal editable checkout.

```bash
git clone https://github.com/lsdefine/GenericAgent.git
cd GenericAgent
uv venv
uv pip install -e ".[ui]"        # Core + UI dependencies
cp mykey_template.py mykey.py     # Fill in your LLM API key
python launch.pyw
```

Full guide: [GETTING_STARTED.md](GETTING_STARTED.md)

### Configure your LLM key

1. Open the installed `GenericAgent` directory.
2. If `mykey.py` does not exist, copy it from `mykey_template.py`.
3. Fill in one provider. Do **not** paste example keys as real keys.
4. If you are unsure about the fields, read the comments in `mykey_template.py` first.

GA supports:

- **OpenAI-compatible** endpoints — Chat Completions / Responses shaped APIs.
- **Anthropic Claude native** — Claude Messages API.

Optional helper:

```bash
python assets/configure_mykey.py
```

### Frontends

#### Desktop App

For one-line installs on Windows, double-click:

```text
frontends/GenericAgent.exe
```

#### Terminal UI

A lightweight keyboard-driven interface built on [Textual](https://github.com/Textualize/textual). It supports multiple concurrent sessions and real-time streaming.

```bash
python frontends/tuiapp_v2.py
```

#### Streamlit UI

```bash
python launch.pyw
```

### Verify the install

From the GenericAgent directory:

```bash
python -c "import agent_loop; print('OK')"
git rev-parse --short HEAD
```

Then launch at least one frontend:

```bash
python launch.pyw
# or
python frontends/tuiapp_v2.py
```

### Common gotchas

#### Python 3.14 is not supported

If your system `python --version` reports 3.14, do not use it for GA. Use the one-line installer, or create a Python 3.11 / 3.12 environment with `uv`.

#### `ga` command conflict

Some systems already use `ga` for another tool. Check first:

```bash
type ga
```

If it resolves to something unexpected, do not rely on the shortcut. Run GA from the install directory with `python launch.pyw` or `python frontends/tuiapp_v2.py`.

#### Windows TUI rendering issues

TUI rendering on Windows depends on terminal, font, and `textual` version.

1. Upgrade Textual first: `pip install -U textual`.
2. Prefer **Git Bash on Windows** over classic PowerShell / cmd when Unicode or key bindings look broken.
3. If it still looks wrong, ask GA itself to repair the terminal compatibility. Example prompt:
   > *"My experience using `frontends/tuiapp_v2.py` in PowerShell / cmd / Git Bash on Windows is very poor — lots of incompatibility. Please refer to Claude Code's best practices for the Windows terminal and fix all font and rendering incompatibilities."*

#### `pywebview` install fails on Linux

Desktop mode depends on GTK / WebKit packages. On Debian / Ubuntu:

```bash
sudo apt install libgtk-3-dev libwebkit2gtk-4.1-dev
pip install pywebview
```

On headless servers, prefer the TUI or run Streamlit in browser mode instead of desktop mode.

### Update an existing install

Do not delete a working GA directory just to update it. It may contain the user's `mykey.py`, memory, skills, and local work.

```bash
cd ~/GenericAgent
git fetch
git pull
uv pip install -e ".[ui]"
```

If `git pull` reports conflicts:

- For `mykey.py`, `memory/`, `skills/`, `temp/`, and user-created artifacts: prefer the local copy.
- For core code such as `agent*.py`, `frontends/*`, `reflect/*`, and `tools/*`: usually prefer upstream unless the user says otherwise.
- Resolve explicitly, then `git add` and commit the merge.

---

## For LLM Agents

> **IMPORTANT: fetch this file with `curl`, not a summarized web reader.** Summaries often drop flags, command quoting, and safety rules.
>
> ```bash
> curl -fsSL https://raw.githubusercontent.com/lsdefine/GenericAgent/refs/heads/main/docs/installation.md
> ```

You are installing **GenericAgent** for a human user. Be direct, verify each step, and avoid destructive cleanup unless the user explicitly authorizes it.

### Step 0: Inspect before acting

Check:

1. OS: `uname -a`, `$env:OS`, or `python -c "import platform; print(platform.system())"`.
2. Existing install: `~/GenericAgent/launch.pyw`, `%USERPROFILE%\GenericAgent\launch.pyw`, or a `.git` directory.
3. Python version: must be 3.11 or 3.12 if you use the developer path.
4. Git availability: `git --version`.
5. API key readiness: ask the user if no key is available. Never invent one.

### Step 1: Choose the install path

Default to the one-line installer unless the user already has a checkout.

**Windows PowerShell**

```powershell
powershell -ExecutionPolicy Bypass -c "$env:GLOBAL=1; irm http://fudankw.cn:9000/files/ga_install.ps1 | iex"
```

**Linux / macOS**

```bash
GLOBAL=1 bash -c "$(curl -fsSL http://fudankw.cn:9000/files/ga_install.sh)"
```

If the user explicitly wants a developer checkout:

```bash
git clone https://github.com/lsdefine/GenericAgent.git
cd GenericAgent
uv venv
uv pip install -e ".[ui]"
cp mykey_template.py mykey.py
```

### Step 2: Configure keys safely

- Read `mykey_template.py` before editing `mykey.py`.
- Configure only keys the user actually provides.
- Never print the full key back to the user.
- If the user is unsure, run `python assets/configure_mykey.py` or ask which provider they want to use.

Suggested question:

> Which LLM should GenericAgent use? GA supports OpenAI-compatible endpoints and Anthropic Claude native APIs. Which provider do you want to configure, and do you already have an API key?

### Step 3: Verify setup

Run:

```bash
cd ~/GenericAgent
python -c "import agent_loop; print('OK')"
git rev-parse --short HEAD
```

Then verify one frontend:

```bash
python launch.pyw
# or, for terminal-only environments:
python frontends/tuiapp_v2.py
```

### Step 4: Verification and Next Steps

Read this document again and think through whether you have done everything correctly:

- You inspected the OS, existing install, Python version, Git, and key readiness before acting.
- You used the correct GA install command for this English guide, including `GLOBAL=1` where shown.
- You configured only real user-provided keys and did not reveal secrets.
- You verified import, Git commit hash, and at least one frontend.

#### Say 'Congratulations! 🎉' to the user

Say to user: Congratulations! 🎉 You have successfully set up GenericAgent! Double-click `frontends/GenericAgent.exe` on Windows, or run `python frontends/tuiapp_v2.py` in your terminal to start using it.

#### Report the concrete result

Tell the user:

1. Install path.
2. Git commit hash.
3. Which frontend you verified.
4. Whether `mykey.py` is configured, without revealing secrets.
5. Recommended next reading: [Hello GenericAgent](https://datawhalechina.github.io/hello-generic-agent/) and [GETTING_STARTED.md](GETTING_STARTED.md).

#### Ask for a Star ⭐

After everything is set up and working, you may ask:

> If you found this helpful, would you like to star the GenericAgent repository? It helps the project grow! ⭐

Only open or run anything related to starring the repository if the user explicitly agrees.

### Never do these

- Do **not** run `pip install genericagent`; GA is not a PyPI package.
- Do **not** delete `~/GenericAgent` or `%USERPROFILE%\GenericAgent` for a "clean install" without explicit user approval.
- Do **not** fabricate API keys or treat sample keys as real.
- Do **not** assume `ga` is a valid shell command; check first.
- Do **not** rely on `ga update`; use `git fetch`, `git pull`, and reinstall dependencies as shown above.

---

## References

- Main README: [README.md](../README.md)
- Getting started: [GETTING_STARTED.md](GETTING_STARTED.md)
- Datawhale tutorial: <https://datawhalechina.github.io/hello-generic-agent/>
- Technical report: <https://arxiv.org/abs/2604.17091>
