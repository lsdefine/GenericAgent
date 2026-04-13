# 贡献指南 | Contributing Guide

感谢你对 AI 步步 (AIbubu) 的关注！以下是参与贡献的指引。

Thanks for your interest in AI 步步 (AIbubu)! Here's how to contribute.

## 开发环境 | Development Setup

### 前置条件 | Prerequisites

- [Node.js](https://nodejs.org/) 22+
- [pnpm](https://pnpm.io/) 9+
- [Rust](https://www.rust-lang.org/tools/install) (stable)
- Tauri 2 系统依赖 | Tauri 2 system dependencies: [Tauri docs](https://v2.tauri.app/start/prerequisites/)

### 启动开发 | Start Development

```bash
git clone https://github.com/funAgent/ai-bubu.git
cd ai-bubu
pnpm install
pnpm tauri dev
```

### 常用命令 | Common Commands

| 命令                  | 说明                |
| --------------------- | ------------------- |
| `pnpm dev`            | 启动前端开发服务器  |
| `pnpm tauri dev`      | 启动 Tauri 开发模式 |
| `pnpm test`           | 运行测试            |
| `pnpm lint`           | 代码检查            |
| `pnpm format`         | 代码格式化          |
| `pnpm validate:skins` | 校验皮肤资源一致性  |
| `pnpm dev:site`       | 启动官网开发服务器  |

## 提交规范 | Commit Convention

本项目使用 [Conventional Commits](https://www.conventionalcommits.org/) 规范，配合 commitlint 强制执行。

格式：`type(scope): message`

### Type

| Type       | 说明                   |
| ---------- | ---------------------- |
| `feat`     | 新功能                 |
| `fix`      | Bug 修复               |
| `docs`     | 文档变更               |
| `style`    | 代码格式（不影响逻辑） |
| `refactor` | 重构                   |
| `perf`     | 性能优化               |
| `test`     | 测试                   |
| `chore`    | 构建/工具链变更        |
| `ci`       | CI/CD 变更             |

### Scope

| Scope     | 说明       |
| --------- | ---------- |
| `app`     | 桌面应用   |
| `site`    | 官网       |
| `skin`    | 皮肤系统   |
| `monitor` | 活跃度监测 |
| `social`  | 社交功能   |
| `i18n`    | 国际化     |
| `ci`      | CI/CD      |
| `deps`    | 依赖更新   |

### 示例 | Examples

```
feat(skin): add pixel cat skin
fix(monitor): handle cursor SQLite lock on Windows
docs(site): update download links for v0.2.0
chore(deps): upgrade tauri to 2.11
```

## 贡献皮肤 | Contributing Skins

为 AI 步步添加新皮肤是最简单的贡献方式之一。

### 步骤 | Steps

1. Fork 并克隆本仓库
2. 在 `packages/app/public/skins/` 下创建新目录（如 `my-skin/`）
3. 添加 `skin.json`（必填字段：`name`, `author`, `animations`）
4. 添加 `pet.png`（精灵图）
5. 运行 `pnpm validate:skins` 确认通过
6. 提交 PR，commit 格式：`feat(skin): add xxx skin`

### skin.json 示例 | skin.json Example

```json
{
  "name": "My Skin",
  "version": "1.0.0",
  "author": "Your Name",
  "description": "A cool custom skin",
  "style": "pixel",
  "format": "sprite",
  "size": { "width": 24, "height": 24 },
  "animations": {
    "idle": {
      "file": "pet.png",
      "loop": true,
      "sprite": {
        "frameWidth": 24,
        "frameHeight": 24,
        "frameCount": 4,
        "columns": 4,
        "fps": 4,
        "startFrame": 0
      }
    },
    "walk": { ... },
    "run": { ... },
    "sprint": { ... }
  }
}
```

### 要求 | Requirements

- 至少包含 `idle` 动画
- 有效的动画状态：`idle`, `walk`, `run`, `sprint`
- 精灵图格式为 PNG
- 每个动画的 `file` 必须指向实际存在的文件

## 贡献 Provider 监测 | Contributing Providers

为 AIbubu 添加新的 AI 工具监测支持。每个 Provider 是一个 TOML 配置文件。

Adding monitoring support for a new AI coding tool. Each provider is a TOML config file.

### 快速开始 | Quick Start

1. 阅读 [Provider 配置指南](./packages/app/providers/README.md) 了解架构和适配器类型
2. 在 `packages/app/providers/` 下创建 `your-tool.toml`
3. 以 `pnpm tauri dev` 启动开发模式，观察终端中的 monitor 日志验证检测
4. 运行 `node scripts/validate-providers.js` 确认配置通过校验
5. 验证通过后将文件移到 `packages/app/providers/` 根目录
6. 提交 PR，commit 格式：`feat(monitor): add xxx provider`，附上检测成功的终端日志截图

### 适配器类型 | Adapter Types

| Adapter      | 适用场景                             | 示例                  |
| ------------ | ------------------------------------ | --------------------- |
| `sqlite`     | IDE 类工具，本地 SQLite 数据库       | Cursor                |
| `jsonl`      | CLI 工具，会话日志为 JSONL 格式      | Claude Code、OpenCode |
| `process`    | 仅能通过进程检测活跃度               | Trae                  |
| `file_mtime` | 工具会写入本地文件但非 JSONL/SQLite  | —                     |
| `vscode_ext` | VS Code 扩展，数据存于 globalStorage | —                     |

详细配置模板和字段说明请参阅 [Provider 配置指南](./packages/app/providers/README.md)。

## 提交 PR | Submitting a PR

1. Fork 本仓库
2. 创建特性分支：`git checkout -b feat/your-feature`
3. 提交变更（遵循 commit 规范）
4. 推送到你的 fork：`git push origin feat/your-feature`
5. 创建 Pull Request

### PR 要求 | PR Requirements

- 通过所有 CI 检查（lint、test、skin validation、provider validation）
- 如果添加了新功能，请同步更新文档
- 如果涉及 UI 变更，请附上截图

## 报告 Bug | Reporting Bugs

请使用 [GitHub Issues](https://github.com/funAgent/ai-bubu/issues) 提交 Bug 报告，并尽量提供：

- 操作系统及版本
- AIbubu 版本
- 复现步骤
- 期望行为 vs 实际行为
- 相关日志或截图

## 发布流程 | Releasing

如果你是项目维护者，请参阅 [RELEASING.md](./RELEASING.md) 了解版本发布流程。

## 许可证 | License

参与贡献即表示你同意你的贡献将在 [MIT License](./LICENSE) 下发布。
