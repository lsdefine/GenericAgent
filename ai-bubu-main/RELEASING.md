# 发布指南 | Release Guide

本文档面向项目维护者，描述如何发布 AIbubu 的新版本。

This guide is for project maintainers and describes how to release a new version of AIbubu.

## 前置条件 | Prerequisites

- 已安装 [git-cliff](https://git-cliff.org/)（用于自动生成 Changelog）
- 拥有仓库的 push 和 tag 权限

## 发布步骤 | Steps

### 1. 确认主分支状态

确保 `main` 分支的 CI 全部通过，且所有待发布的变更已合并。

```bash
git checkout main
git pull origin main
```

### 2. 更新版本号

使用 `bump` 脚本统一更新三个文件的版本号：

```bash
# 语义化版本递增
pnpm bump patch    # 修复版本  0.1.0 → 0.1.1
pnpm bump minor    # 功能版本  0.1.0 → 0.2.0
pnpm bump major    # 大版本    0.1.0 → 1.0.0

# 或直接指定版本号
pnpm bump 0.2.0
```

该脚本会同步更新以下文件：

| 文件                                     | 字段      |
| ---------------------------------------- | --------- |
| `packages/app/package.json`              | `version` |
| `packages/app/src-tauri/tauri.conf.json` | `version` |
| `packages/app/src-tauri/Cargo.toml`      | `version` |

### 3. 生成 Changelog

```bash
git-cliff -o CHANGELOG.md
```

生成后建议快速浏览，确认内容无误。Changelog 格式由 `cliff.toml` 配置，自动按 Conventional Commits 分组（Features、Bug Fixes、Performance 等）。

### 4. 提交并打 Tag

```bash
git add -A
git commit -m "chore(app): release v0.2.0"
git tag v0.2.0
```

### 5. 推送到远程

```bash
git push origin main --tags
```

### 6. 等待自动构建

推送 `v*` tag 后，GitHub Actions ([release.yml](.github/workflows/release.yml)) 自动触发多平台构建：

| 平台    | 产物                                  |
| ------- | ------------------------------------- |
| macOS   | `.dmg` (Apple Silicon + Intel 双架构) |
| Windows | `.msi`                                |
| Linux   | `.AppImage` / `.deb`                  |

构建完成后会自动创建一个 **Draft Release**。

### 7. 发布 Release

1. 前往 [GitHub Releases](https://github.com/funAgent/ai-bubu/releases) 页面
2. 找到刚创建的 Draft Release
3. 检查 Release Notes 和附件是否完整
4. 点击 **Publish release**

## 版本规范 | Versioning

本项目遵循 [Semantic Versioning](https://semver.org/)：

- **patch** (`0.1.x`) — Bug 修复、小幅调整
- **minor** (`0.x.0`) — 新功能、向后兼容的改进
- **major** (`x.0.0`) — 破坏性变更

## 紧急修复 | Hotfix

如果需要对已发布版本进行紧急修复：

1. 从对应 tag 创建修复分支：`git checkout -b hotfix/v0.1.1 v0.1.0`
2. 提交修复
3. 合并回 `main`
4. 按上述正常流程发布新的 patch 版本

## 故障排查 | Troubleshooting

- **CI 构建失败**：检查 [Actions](https://github.com/funAgent/ai-bubu/actions/workflows/release.yml) 页面的日志，常见原因为系统依赖缺失或 Rust 编译错误
- **版本号不一致**：确认使用了 `pnpm bump` 而非手动修改，避免三个文件版本不同步
- **Tag 已存在**：删除本地和远程 tag 后重新创建
  ```bash
  git tag -d v0.2.0
  git push origin :refs/tags/v0.2.0
  ```
