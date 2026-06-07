---
version: 1.0
last_updated: "2026-05-30"
---

# Web 工具链初始化执行 SOP

若 web_scan 和 web_execute_js 已测试可用，无需执行此 SOP。
仅供初始安装时，code_run 可用但 web 工具尚未配置的场景。

## 目标
在仅具备系统级权限（code_run）时，建立 Web 交互能力（web_scan / web_execute_js）。

## 前置：检测浏览器

## 安装 tmwd_cdp_bridge 扩展
扩展路径: `../assets/tmwd_cdp_bridge/`（MV3 Chrome 扩展，含 CDP debugger + scripting + cookie 能力）

### 自动打开扩展管理页
`chrome://extensions` 无法通过命令行或 JS 打开，需用剪贴板+地址栏方案

### 安装步骤（chrome扩展页难以自动化）
1. 打开扩展管理页，开启「开发者模式」
2. 点击「加载已解压的扩展程序」，选择 `assets/tmwd_cdp_bridge/` 目录，或让用户直接拖入
3. 显示“错误”不用管，一般只是因为还没连上GA

## 验证
⚠ web_scan 显示「没有可用标签页」不一定是扩展没装好，可能是浏览器未打开或只有 blank 页。
此时禁止乱试，先用 `start "" "https://www.baidu.com"` 打开一个正常页面，再 `web_scan` 确认。
若仍不可用，无法自动探测默认浏览器是哪个、插件装在了哪个浏览器、或是否已安装——此时请求用户协助。