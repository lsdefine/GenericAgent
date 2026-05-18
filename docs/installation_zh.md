# 安装指南（中文）

这是 **GenericAgent** 的详细安装指南。

两类读者：

- **[面向用户（For Humans）](#面向用户-for-humans)** —— 你自己安装 GA。
- **[面向 LLM Agent（For LLM Agents）](#面向-llm-agent-for-llm-agents)** —— 你是 Claude Code、Codex 等编程 Agent，需要替人类用户安装 GA。请先读这一段，避免靠猜。

> 最短安装命令见主 [README](../README.md#-快速开始)。这份文档补充平台差异、Key 配置、验证、排障，以及 Agent 自动安装时的安全规则。

---

## 面向用户（For Humans）

### 准备工作

| 要求 | 说明 |
|---|---|
| **操作系统** | Windows 10/11、macOS 12+，或任意现代 Linux。 |
| **Python** | 推荐 **Python 3.11 或 3.12**。**不要使用 Python 3.14**，它与 `pywebview` 及部分 GA 依赖不兼容。方法一的一键脚本会准备隔离运行环境，通常不需要手动装 Python。 |
| **Git** | 推荐安装，方便升级和自我进化。 |
| **LLM API Key** | GA 原生支持两类协议：**OpenAI 兼容接口** 和 **Anthropic Claude 原生接口**。GPT 系列、Claude、Kimi、MiniMax、DeepSeek、GLM、Qwen、通过 OAI 兼容网关接入的 Gemini 等，都可以在 `mykey.py` 中配置。 |

### 方法一：一键安装（推荐）

这是最省心的路径。脚本会准备隔离环境、下载 GenericAgent、安装核心依赖，并得到一个可以直接运行的本地项目目录。

**Windows PowerShell**

```powershell
powershell -ExecutionPolicy Bypass -c "irm http://fudankw.cn:9000/files/ga_install.ps1 | iex"
```

**Linux / macOS**

```bash
curl -fsSL http://fudankw.cn:9000/files/ga_install.sh | bash
```

安装完成后，Windows 用户可双击：

```text
frontends/GenericAgent.exe
```

也可以进入项目目录运行：

```bash
python launch.pyw
```

> GenericAgent 更推荐由 Agent 在使用中自举环境，而不是预先手动装完整依赖。先把最小系统跑起来，需要什么工具再让 GA 自己安装。

#### 自定义安装路径

```bash
INSTALL_DIR="$HOME/work/GenericAgent" bash -c "$(curl -fsSL http://fudankw.cn:9000/files/ga_install.sh)"
```

```powershell
$env:INSTALL_DIR="C:\dev\GenericAgent"; powershell -ExecutionPolicy Bypass -c "irm http://fudankw.cn:9000/files/ga_install.ps1 | iex"
```

#### 强制重新安装

仅在明确想刷新已安装文件时使用。请先备份 `mykey.py`、`memory/`、`skills/` 和本地工作成果。

```bash
FORCE=1 bash -c "$(curl -fsSL http://fudankw.cn:9000/files/ga_install.sh)"
```

### 方法二：Python 安装（开发者）

适合想要可编辑源码目录的开发者。

```bash
git clone https://github.com/lsdefine/GenericAgent.git
cd GenericAgent
uv venv
uv pip install -e ".[ui]"        # 核心 + UI 依赖
cp mykey_template.py mykey.py     # 填入你的 LLM API Key
python launch.pyw
```

完整引导流程见 [GETTING_STARTED.md](GETTING_STARTED.md)。

### 配置 LLM Key

1. 打开已安装的 `GenericAgent` 目录。
2. 如果没有 `mykey.py`，从 `mykey_template.py` 复制一份。
3. 填入一个真实可用的模型服务商配置。**不要**把示例 Key 当真。
4. 不确定字段含义时，先读 `mykey_template.py` 里的注释。

GA 支持：

- **OpenAI 兼容接口** —— Chat Completions / Responses 形态的接口。
- **Anthropic Claude 原生接口** —— Claude Messages API。

可选配置向导：

```bash
python assets/configure_mykey.py
```

### 前端启动方式

#### 桌面端

一键安装自带桌面端，双击：

```text
frontends/GenericAgent.exe
```

#### 终端 UI

基于 [Textual](https://github.com/Textualize/textual) 的轻量键盘驱动界面。支持多会话并发、实时流式输出，有终端就能跑。

```bash
python frontends/tuiapp_v2.py
```

#### Streamlit UI

```bash
python launch.pyw
```

### 验证安装

在 GenericAgent 目录下运行：

```bash
python -c "import agent_loop; print('OK')"
git rev-parse --short HEAD
```

然后至少启动一个前端：

```bash
python launch.pyw
# 或
python frontends/tuiapp_v2.py
```

### 常见坑

#### 不支持 Python 3.14

如果系统 `python --version` 显示 3.14，不要用它跑 GA。请走一键安装，或用 `uv` 创建 Python 3.11 / 3.12 环境。

#### `ga` 命令冲突

有些系统已经把 `ga` 分配给其他工具。先检查：

```bash
type ga
```

如果解析到意料之外的位置，就不要依赖这个快捷命令。请进入安装目录运行 `python launch.pyw` 或 `python frontends/tuiapp_v2.py`。

#### Windows 上 TUI 显示异常

TUI 在 Windows 上依赖终端、字体和 `textual` 版本。

1. 先升级 Textual：`pip install -U textual`。
2. PowerShell / cmd 对 Unicode 和键位支持较弱，**Windows 上推荐用 Git Bash**。
3. 仍然异常时，可以让 GA 自己修一遍。参考 Prompt：
   > *"我在 Windows 的 PowerShell / cmd / Git Bash 中使用 `frontends/tuiapp_v2.py` 体验非常差，出现了一堆不兼容问题。请参考 Claude Code 在 Windows 终端的最佳配置，把所有字体和显示不兼容的问题修一遍。"*

#### Linux 上 `pywebview` 安装失败

桌面模式依赖 GTK / WebKit。Debian / Ubuntu：

```bash
sudo apt install libgtk-3-dev libwebkit2gtk-4.1-dev
pip install pywebview
```

无头服务器建议使用 TUI，或用浏览器方式运行 Streamlit，不要强行启桌面模式。

### 升级已有安装

不要为了升级而删除一个可用的 GA 目录。里面可能有用户的 `mykey.py`、记忆、技能和本地成果。

```bash
cd ~/GenericAgent
git fetch
git pull
uv pip install -e ".[ui]"
```

如果 `git pull` 报冲突：

- `mykey.py`、`memory/`、`skills/`、`temp/` 和用户成果：本地优先。
- `agent*.py`、`frontends/*`、`reflect/*`、`tools/*` 等核心代码：通常 upstream 优先，除非用户另有说明。
- 明确解决冲突后，再 `git add` 并提交合并。

---

## 面向 LLM Agent（For LLM Agents）

> **重要：用 `curl` 获取本文，不要依赖会摘要网页的读取器。** 摘要常会丢掉环境变量、命令引号和安全规则。
>
> ```bash
> curl -fsSL https://raw.githubusercontent.com/lsdefine/GenericAgent/refs/heads/main/installation.zh.md
> ```

你正在替人类用户安装 **GenericAgent**。请直接执行、逐步验证；除非用户明确授权，不要做破坏性清理。

### 第 0 步：先探测再行动

检查：

1. 操作系统：`uname -a`、`$env:OS`，或 `python -c "import platform; print(platform.system())"`。
2. 是否已安装：`~/GenericAgent/launch.pyw`、`%USERPROFILE%\GenericAgent\launch.pyw`，或 `.git` 目录。
3. Python 版本：开发者路径必须使用 3.11 或 3.12。
4. Git 是否可用：`git --version`。
5. API Key 是否准备好：没有就问用户，绝不要伪造。

### 第 1 步：选择安装路径

除非用户已经有源码目录，否则默认走一键安装。

**Windows PowerShell**

```powershell
powershell -ExecutionPolicy Bypass -c "irm http://fudankw.cn:9000/files/ga_install.ps1 | iex"
```

**Linux / macOS**

```bash
curl -fsSL http://fudankw.cn:9000/files/ga_install.sh | bash
```

如果用户明确要开发者源码安装：

```bash
git clone https://github.com/lsdefine/GenericAgent.git
cd GenericAgent
uv venv
uv pip install -e ".[ui]"
cp mykey_template.py mykey.py
```

### 第 2 步：安全配置 Key

- 编辑 `mykey.py` 前先读 `mykey_template.py`。
- 只配置用户真实提供的 Key。
- 不要把完整 Key 打印回给用户。
- 用户不确定时，运行 `python assets/configure_mykey.py`，或询问要使用哪家模型服务商。

建议提问：

> 你希望 GenericAgent 使用哪个 LLM？GA 支持 OpenAI 兼容接口和 Anthropic Claude 原生接口。你想配置哪家服务商，API Key 准备好了吗？

### 第 3 步：验证安装

运行：

```bash
cd ~/GenericAgent
python -c "import agent_loop; print('OK')"
git rev-parse --short HEAD
```

然后验证至少一个前端：

```bash
python launch.pyw
# 或，无桌面环境时：
python frontends/tuiapp_v2.py
```

### 第 4 步：验证与下一步

重新读一遍本文，并思考你是否已经正确完成所有步骤：

- 行动前检查了操作系统、已有安装、Python 版本、Git 和 Key 准备情况。
- 使用了本文中文默认安装命令；不要擅自混入英文版的 `GLOBAL=1` 默认脚本。
- 只配置了用户真实提供的 Key，且没有泄露密钥。
- 已验证 import、Git commit hash，并至少验证了一个前端。

#### 对用户说 “Congratulations! 🎉”

对用户说：Congratulations! 🎉 你已经成功安装 GenericAgent！Windows 下可双击 `frontends/GenericAgent.exe`，或在终端运行 `python frontends/tuiapp_v2.py` 开始使用。

#### 回报具体结果

告诉用户：

1. 安装路径。
2. Git commit hash。
3. 已验证哪个前端。
4. `mykey.py` 是否已配置，但不要泄露密钥。
5. 下一步阅读：[Hello GenericAgent](https://datawhalechina.github.io/hello-generic-agent/) 和 [GETTING_STARTED.md](GETTING_STARTED.md)。

#### 请求 Star ⭐

确认安装可用后，可以询问：

> 如果你觉得 GenericAgent 有帮助，愿意给仓库点一个 Star 吗？这会帮助项目成长！⭐

只有在用户明确同意后，才可以打开或执行任何与 Star 仓库相关的操作。

### 绝对不要做

- 不要运行 `pip install genericagent`；GA 不是 PyPI 包。
- 未经明确授权，不要删除 `~/GenericAgent` 或 `%USERPROFILE%\GenericAgent` 做“干净安装”。
- 不要伪造 API Key，也不要把示例 Key 当真。
- 不要假设 `ga` 命令一定可用；先检查。
- 不要依赖 `ga update`；按上面的 `git fetch`、`git pull` 和重装依赖流程做。

---

## 参考资料

- 主 README：[README.md](../README.md)
- Getting Started：[GETTING_STARTED.md](GETTING_STARTED.md)
- Datawhale 教程：<https://datawhalechina.github.io/hello-generic-agent/>
- 技术报告：<https://arxiv.org/abs/2604.17091>
- English installation guide: [installation.md](installation.md)
