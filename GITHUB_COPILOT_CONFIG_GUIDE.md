# GitHub Copilot Pro 配置指南

## 📖 目录

1. [概述](#概述)
2. [前置条件](#前置条件)
3. [获取 OAuth Token](#获取-oauth-token)
4. [配置方法（推荐）](#配置方法推荐)
5. [配置方法（直连模式）](#配置方法直连模式)
6. [常见问题](#常见问题)
7. [可用模型列表](#可用模型列表)

---

## 1. 概述

本文档详细介绍如何在 GenericAgent 项目中配置和使用 GitHub Copilot Pro 模型。GitHub Copilot Pro 提供了多种强大的 AI 模型，包括 GPT-4、GPT-5、Claude 和 Gemini 系列。

**关键点：**
- GitHub Copilot API 需要 OAuth Token（gho_开头），不支持传统 PAT（ghp_开头）
- 需要使用 litellm 代理进行模型名称转换
- 支持流式响应和工具调用

---

## 2. 前置条件

- 已订阅 GitHub Copilot Pro
- 已安装 Python 3.10+
- 已创建项目虚拟环境 `.venv`
- 已在 `.venv` 中安装 litellm 及其代理依赖

```bash
.venv\Scripts\python.exe -m pip install -U pip
.venv\Scripts\python.exe -m pip install "litellm[proxy]"
```

---

## 3. 获取 OAuth Token

### 方法一：使用 GitHub CLI（推荐）

```bash
# 安装 GitHub CLI（如果未安装）
# https://cli.github.com/

# 登录并获取 Copilot 权限
gh auth login --scopes copilot

# 获取 token
gh auth token
```

### 方法二：从 VS Code Copilot 插件提取

1. 打开 VS Code
2. 确保已登录 GitHub 并启用 Copilot
3. 在以下路径查找 token：
   - Windows: `%APPDATA%\GitHub Copilot\api_token`
   - macOS: `~/Library/Application Support/GitHub Copilot/api_token`
   - Linux: `~/.config/github-copilot/api_token`

---

## 4. 配置方法（推荐）

使用 litellm 代理模式，这是最稳定的配置方式。

### 步骤 1：创建 litellm 配置文件

在项目根目录创建 `litellm_config.yaml`：

```yaml
model_list:
  - model_name: gpt-4
    litellm_params:
      model: github_copilot/gpt-4
      api_key: YOUR_OAUTH_TOKEN_HERE
      extra_headers:
        Editor-Version: "vscode/1.85.1"
        Editor-Plugin-Version: "copilot/1.155.0"
        Copilot-Integration-Id: "vscode-chat"
        User-Agent: "GitHubCopilotChat/0.35.0"
  
  # 添加更多模型...
  - model_name: gpt-5
    litellm_params:
      model: github_copilot/gpt-5
      api_key: YOUR_OAUTH_TOKEN_HERE
      extra_headers:
        Editor-Version: "vscode/1.85.1"
        Editor-Plugin-Version: "copilot/1.155.0"
        Copilot-Integration-Id: "vscode-chat"
        User-Agent: "GitHubCopilotChat/0.35.0"
```

**注意**：将 `YOUR_OAUTH_TOKEN_HERE` 替换为你的 OAuth Token。

### 步骤 2：配置 mykey.py

```python
native_oai_config_copilot = {  
    'name': 'copilot-pro',
    'apikey': 'anything',  # litellm 代理不需要验证
    'apibase': 'http://localhost:8000/v1',
    'model': 'gpt-4',
    'api_mode': 'chat_completions',
    'stream': True,
}
```

### 步骤 3：启动 litellm 代理

```bash
.venv\Scripts\litellm.exe --config litellm_config.yaml --port 8000
# 或直接双击项目根目录下 start_litellm.bat
```

### 步骤 4：启动 GenericAgent

```bash
python launch.pyw
```

**其他可选前端：**
```bash
python frontends/qtapp.py                # 基于 Qt 的桌面应用
streamlit run frontends/stapp2.py        # 另一种 Streamlit 风格 UI
python frontends/wechatapp.py            # 微信 Bot 前端
```

---

## 5. 配置方法（直连模式）

**⚠️ 注意**：直连模式可能遇到模型名称不支持的问题，推荐使用代理模式。

### 配置示例

```python
native_oai_config_copilot = {  
    'name': 'copilot-pro',
    'apikey': 'gho_your_oauth_token',
    'apibase': 'https://api.githubcopilot.com/chat/completions',
    'model': 'gpt-4',
    'api_mode': 'chat_completions',
    'stream': True,
    'extra_headers': {
        "Editor-Version": "vscode/1.85.1",
        "Editor-Plugin-Version": "copilot/1.155.0",
        "Copilot-Integration-Id": "vscode-chat",
        "User-Agent": "GitHubCopilotChat/0.35.0"
    },
}
```

---

## 6. 常见问题

### Q1: 错误 "The requested model is not supported"

**原因**：GitHub Copilot API 需要使用 litellm 格式的模型名称（如 `github_copilot/gpt-4`），而不是标准模型名称。

**解决方案**：使用 litellm 代理模式。

### Q2: 错误 "Access to this endpoint is forbidden"

**原因**：使用了错误的端点或 token 类型。

**解决方案**：
- 使用 `https://api.githubcopilot.com` 而不是 `api.individual.githubcopilot.com`
- 确保使用 OAuth Token（gho_开头）而不是 PAT（ghp_开头）

### Q3: 错误 "MissingSchema: Invalid URL 'auto/v1/chat/completions'"

**原因**：`apibase: 'auto'` 在 GenericAgent 中无法正确解析。

**解决方案**：使用完整的 URL 地址或 litellm 代理模式。

### Q4: 网络连接超时

**解决方案**：设置代理环境变量：

```bash
set HTTP_PROXY=http://127.0.0.1:6789
set HTTPS_PROXY=http://127.0.0.1:6789
```

---

## 7. 可用模型列表

### OpenAI 模型
| 模型名称 | litellm 格式 | 说明 |
|----------|-------------|------|
| `gpt-4` | `github_copilot/gpt-4` | 标准 GPT-4 模型 |
| `gpt-5` | `github_copilot/gpt-5` | GPT-5 模型 |
| `gpt-5.1-codex` | `github_copilot/gpt-5.1-codex` | 代码专用模型 |
| `gpt-5.2-codex` | `github_copilot/gpt-5.2-codex` | 改进版代码模型 |
| `gpt-5.4` | `github_copilot/gpt-5.4` | 最新 GPT-5.4 模型 |
| `gpt-5.4-mini` | `github_copilot/gpt-5.4-mini` | 轻量版，响应更快 |

### Anthropic 模型
| 模型名称 | litellm 格式 | 说明 |
|----------|-------------|------|
| `claude-sonnet-4.5` | `github_copilot/claude-sonnet-4.5` | 长上下文支持 |
| `claude-opus-4.5` | `github_copilot/claude-opus-4.5` | 旗舰模型 |
| `claude-opus-4.6` | `github_copilot/claude-opus-4.6` | 更新版本 |
| `claude-opus-4.7` | `github_copilot/claude-opus-4.7` | 最新版本 |

### Google 模型
| 模型名称 | litellm 格式 | 说明 |
|----------|-------------|------|
| `gemini-2.5-pro` | `github_copilot/gemini-2.5-pro` | Gemini 旗舰模型 |
| `gemini-3-flash` | `github_copilot/gemini-3-flash` | 轻量快速版 |
| `gemini-3.1-pro` | `github_copilot/gemini-3.1-pro` | 最新版本 |

---

## 📝 配置模板

### litellm_config.yaml 完整模板

```yaml
model_list:
  - model_name: gpt-4
    litellm_params:
      model: github_copilot/gpt-4
      api_key: gho_your_token_here
      extra_headers:
        Editor-Version: "vscode/1.85.1"
        Editor-Plugin-Version: "copilot/1.155.0"
        Copilot-Integration-Id: "vscode-chat"
        User-Agent: "GitHubCopilotChat/0.35.0"
  
  - model_name: gpt-5
    litellm_params:
      model: github_copilot/gpt-5
      api_key: gho_your_token_here
      extra_headers:
        Editor-Version: "vscode/1.85.1"
        Editor-Plugin-Version: "copilot/1.155.0"
        Copilot-Integration-Id: "vscode-chat"
        User-Agent: "GitHubCopilotChat/0.35.0"
  
  - model_name: claude-sonnet
    litellm_params:
      model: github_copilot/claude-sonnet-4.5
      api_key: gho_your_token_here
      extra_headers:
        Editor-Version: "vscode/1.85.1"
        Editor-Plugin-Version: "copilot/1.155.0"
        Copilot-Integration-Id: "vscode-chat"
        User-Agent: "GitHubCopilotChat/0.35.0"
```

---

## 📌 总结

| 配置项 | 值 |
|--------|-----|
| 推荐方式 | litellm 代理模式 |
| 端点 | `http://localhost:8000/v1`（代理） |
| Token 类型 | OAuth Token（gho_开头） |
| 模型格式 | `github_copilot/{model_name}` |
| 必需头部 | Editor-Version, Editor-Plugin-Version, Copilot-Integration-Id, User-Agent |

---

**最后更新**: 2026年4月  
**版本**: v1.0