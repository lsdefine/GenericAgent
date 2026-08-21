# packaging

桌面端发布相关材料。本目录的内容**不会**整体打进发布包——CI
（`.github/workflows/desktop-release-package.yml`）只从这里挑选 `scripts/` 下的
安装/卸载脚本拷进各平台的发布产物，其余文件对构建打包过程是只读参考。

## 目录结构

```
frontends/desktop/packaging/
├── README.md            # 本说明
├── CHECKLIST.md         # 发布前功能测试清单（测试协调用，不参与打包）
├── TODO.md              # 各平台测试分工与计划（测试协调用，不参与打包）
└── scripts/             # ← 唯一被 CI 消费的内容
    ├── windows/
    │   ├── install_windows.ps1     # 环境准备脚本
    │   ├── uninstall.bat           # 卸载入口（向用户确认后调用 ps1）
    │   └── uninstall_windows.ps1
    ├── linux/
    │   ├── install_linux.sh
    │   └── uninstall.sh
    └── macos/
        ├── install_macos.sh
        └── uninstall.command
```

## CI 如何使用这些脚本

`desktop-release-package.yml` 在打各平台 portable 包时，把对应平台的脚本
`cp` 进发布目录（例如 Windows 包里放 `install_windows.ps1` /
`uninstall.bat` / `uninstall_windows.ps1`）。**修改安装/卸载行为只需改
`scripts/` 下的文件，不需要动 workflow。**

> 说明：实际的桌面壳二进制（`GenericAgent.exe` / `.AppImage` / `.app`）由 CI
> 构建生成并发布到 GitHub Release，不在本仓库内提交，也不在本目录占位。

## 自动化测试体系

CI 会先运行零依赖的 `npm run test:ci-contract`，确认 workflow、npm 清单与锁文件、
Rust E2E feature、Tauri 配置、窗口权限、v1 static 边界与 v2 public/dist 边界没有发生
跨文件漂移。P2 使用 L0–L6 分层：

| 层 | 主要入口 | 证明范围 |
|---|---|---|
| L0 合并不变量 | `npm run test:ci-contract` + Git 边界检查 | 无冲突标记、static 零差异、本地资料不入库、workflow 范围、版本一致 |
| L1 单元/契约 | `npm run test`、`pytest frontends/tests`、Rust lib tests | React 状态、Python GA_ROOT/导入/降级、Rust 路径/迁移/回滚 |
| L2 服务集成 | Python bridge integration | 隔离目录中的 HTTP/WS、会话、上传、记忆、模型与 conductor |
| L3 浏览器 E2E | `npm run e2e:browser` | Vite UI + 真实 bridge 的关键用户旅程 |
| L4 原生 E2E | `npm run e2e:desktop` / `e2e:desktop:full` | Tauri IPC、bridge 生命周期、foreign port 与 retry |
| L5 发布包 E2E | `e2e/{windows,linux,macos}/` | 真实 ZIP/AppImage/DMG、首启、重启、移动、文件效果与系统集成 |
| L6 人工/canary | 真机短清单、`npm run e2e:canary` | 原生视觉/Gatekeeper/托盘/文件选择器；真实模型 canary 非阻塞 |

分层跑：

```bash
npm run test:ci-contract # 安装依赖前也可直接运行的契约预检
npm run test              # Layer 1 全部
npm run test:stress       # Layer 1 压力子集
npm run test:bridge       # Layer 2
npm run test:bundle       # Layer 3（需先 npm run build）
npm run test:packaging    # Layer 4
npm run test:all          # Layer 1-3 一键
```

## 发布候选证据

L5 三个平台必须来自同一 commit SHA。每个真包报告记录产物 SHA-256、OS/架构、
bootstrap phase、bridge identity、PID/端口、移动前后路径、截图、脱敏日志和清理结果。
自动旅程通过后仍需完成平台短人工清单，最后由
`e2e/package/verify_candidate_evidence.py` 合成候选证据清单。缺少任一平台、manual item、
macOS `.app` 不可变证明或最终进程清理时，P2 不完成。

真包脚本会临时备份并改写真实的 `~/.ga_desktop_settings.json`，结束时按字节恢复；请只在
专用 OS 测试账号中执行。macOS 失效 override 回退场景可能在 Application Support 创建
正常的版本化可写 runtime，这是产品数据而非 `.app` 内容。
