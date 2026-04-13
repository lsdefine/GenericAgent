# AI 步步 (AIbubu) — Claude Code 项目指令

## 项目概述

AI 步步是一款 Tauri 2 桌面宠物应用，监测 AI 编码工具（Cursor、Claude Code、Codex、OpenCode、Trae）的使用活跃度，将其量化为步数并驱动像素风桌面宠物。

## 技术栈

- **桌面框架**: Tauri 2 (Rust)
- **前端**: Vue 3 + Pinia + Vite 6
- **官网**: Astro 6
- **测试**: Vitest + happy-dom
- **工程化**: pnpm workspace, ESLint, Prettier, Husky, commitlint

## Monorepo 结构

```
packages/
├── app/               # Tauri 桌面应用（主包）
│   ├── src/            # Vue 3 前端源码
│   ├── src-tauri/      # Rust 后端源码
│   ├── providers/      # AI 工具监测配置 (TOML)
│   └── public/skins/  # 皮肤资源
└── site/              # Astro 官网
scripts/               # 工具脚本
```

## 开发命令

| 命令                              | 说明                                          |
| --------------------------------- | --------------------------------------------- |
| `pnpm dev`                        | 前端开发服务器（Tauri beforeDevCommand 依赖） |
| `pnpm tauri dev`                  | Tauri 开发模式                                |
| `pnpm dev:mock`                   | Tauri 开发模式（带模拟同事数据）              |
| `pnpm test`                       | 运行前端测试                                  |
| `pnpm lint`                       | ESLint 检查                                   |
| `pnpm format`                     | Prettier 格式化                               |
| `pnpm validate:skins`             | 校验皮肤资源                                  |
| `pnpm dev:site`                   | 官网开发服务器                                |
| `pnpm build:site`                 | 构建官网                                      |
| `pnpm bump <patch\|minor\|major>` | 同步更新版本号                                |

## Commit 规范

使用 Conventional Commits，由 commitlint 强制执行。

格式: `type(scope): description`

**允许的 scope**: `app`, `site`, `skin`, `monitor`, `social`, `i18n`, `ci`, `deps`

提交代码时请使用 **panda-git-commit** skill 来生成规范的 commit message。

## 编码规范

### TypeScript / Vue

- 使用 `type` 关键字进行类型导入: `import type { Foo } from './foo'`
- 不使用 `console.log`，用 `console.warn` 或 `console.error`
- 组件命名使用 PascalCase
- composable 以 `use` 前缀命名
- 路径别名: `@/` → `packages/app/src/`

### Rust

- 运行 `cargo fmt` 和 `cargo clippy -- -D warnings` 确保通过
- Tauri 命令放在 `packages/app/src-tauri/src/lib.rs` 中注册
- 监测适配器配置使用 TOML 格式，放在 `packages/app/providers/`

### 官网

- Astro 组件在 `packages/site/src/` 中
- 支持中英文 i18n，使用 `data-i18n` 属性切换
- 图片资源区分中英文版本：`*_en.jpg` / `*.jpg`

## 皮肤系统

- 皮肤目录: `packages/app/public/skins/<skin-id>/`
- 每个皮肤必须有 `skin.json` 和 `pet.png`
- 放入目录即自动发现，无需手动注册
- 修改皮肤后运行 `pnpm validate:skins`

## 版本管理

版本号在三处保持同步:

1. `packages/app/package.json`
2. `packages/app/src-tauri/Cargo.toml`
3. `packages/app/src-tauri/tauri.conf.json`

使用 `pnpm bump` 命令一键更新。

## 网络

- 局域网社交使用 UDP 广播，端口 23456
- 协议版本: `0.1.0`

## 注意事项

- 不要修改 `.husky/` 下的 hook 文件，除非明确要求
- 不要直接 `git commit`，使用 panda-git-commit
- 修改 providers/ 下的 TOML 文件后需在多平台测试路径兼容性
- Tauri CSP 策略在 `tauri.conf.json` 中配置，添加新的外部资源需更新 CSP
