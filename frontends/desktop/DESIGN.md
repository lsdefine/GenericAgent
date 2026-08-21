# GenericAgent Desktop — 产品设计规范

本文档记录 Desktop 客户端已确立的产品设计语言，供 PM、设计师、前端开发者和 AI agent 在实现新功能时参照。

---

## 0. v1 / v2 代码所有权

- `frontends/desktop/static/**` 是 upstream 的 Desktop v1，在 React 2.0 PR 中必须保持相对 upstream 零差异。
- React Desktop 2.0 只拥有 `src/**`、`public/**`、Vite 配置与生成的 `dist/**`。
- `public/**` 与 `static/**` 没有字节同步契约；两套入口、loading 和 fallback 分别验证。
- Tauri 默认桌面入口是 Vite `dist`，但 v1 static 仍由 upstream 独立维护。

---

## 1. 功能架构分区

### 1.1 四域模型

Desktop 围绕四个功能域组织，每个域拥有独立的信息密度和交互节奏：

| 域 | Page ID | 核心职责 | 信息密度 | 交互节奏 |
|----|---------|---------|---------|---------|
| 对话 | `chat` | 与 agent 的主交互界面 | 高（流式文本 + 代码 + 工具调用） | 实时 |
| 服务 | `services` | 后台服务进程的生命周期管理 | 中（状态卡片 + 日志） | 观察为主、偶尔操作 |
| 协作 | `collab` | Conductor 多代理编排 | 高（平行 worker 状态 + 对话） | 实时 |
| 用量 | `token` | Token 消耗统计与分析 | 低（表格 + 图表） | 回顾 |

**设计原则**：每个域有且只有一种主要交互模式。Chat 是"对话流"，Services 是"仪表盘"，Collab 是"分屏指挥"，Token 是"报表查阅"。新功能应归属到已有域，而非创造新域。

### 1.2 Shell 结构

```
┌─ Titlebar (macOS: 系统流量灯 + 控制按钮; Windows: 自绘标题栏) ──────────────┐
│ ┌─ Sidebar (260px, 可折叠 Cmd+B) ─┐ ┌─ MainArea (flex:1) ──────────────┐ │
│ │  Navigation Rail (垂直图标)       │ │                                   │ │
│ │  Search Input                     │ │  [ChatView / ServicesPage /       │ │
│ │  Session List (历史会话)          │ │   CollabPage / TokenPage]         │ │
│ │  ─── Footer ───                  │ │                                   │ │
│ │  Settings Gear                    │ │                                   │ │
│ └──────────────────────────────────┘ └───────────────────────────────────┘ │
├─ Statusbar (20px, 服务状态 + bridge 信息) ───────────────────────────────────┤
└───────────────────────────────────────────────────────────────────────────────┘
```

**Navigation Rail**：垂直排列的 Codicon 图标按钮，不带文字标签。当前激活项通过 `--ui-icon-nav-active` 颜色和左侧 2px accent 条指示。点击切换 MainArea 内容。

**Sidebar 与 MainArea 的关系**：Sidebar 是全局导航 + 对话历史的常驻通道，内容不随 page 切换改变。MainArea 独占具体功能域。两者通过 ResizeGroup 允许用户拖拽宽度（200–340px）。

### 1.3 产品层级决策

添加新功能时的路由规则：

1. **能归入现有域吗？** 如果新功能是对话的增强（附件、快捷指令），放在 Chat 域内。如果是进程管理类，放在 Services。
2. **需要全屏空间吗？** 如果是纯信息查看（日志、统计），考虑作为已有域的子视图而非新 page。
3. **只有确定需要并行的、不可叠加的独立交互模式**时，才增加新域。增加域 = 修改 `PageId` union + Nav Rail + 路由逻辑。

---

## 2. 渐进式披露 (Progressive Disclosure)

### 2.1 三层信息架构

所有用户面对的文本遵循三层结构：

| 层级 | 角色 | 可见条件 | 长度约束 |
|------|------|---------|---------|
| **L1 扫视** | 用户即刻可见，帮助快速定位 | 始终可见 | 2–4 字 / 1–3 词 |
| **L2 解释** | 回答"这是什么/为什么" | 悬浮或 focus | 4–8 字 / 一短句 |
| **L3 诊断** | 完整文档级信息 | 主动展开（drawer/modal/展开区） | 不限 |

**规则**：默认只展示 L1。用户不需要理解系统模型即可操作。L2 在好奇或犹豫时出现。L3 只在用户明确要求深入时出现。

### 2.2 各域的披露策略

#### Chat Thread

| 元素 | 默认状态 | 展开触发 | 展开形态 |
|------|---------|---------|---------|
| 用户消息 | 4 行 clamp + 渐变遮罩 | 点击展开按钮 | 最大 40dvh 内滚动 |
| Thinking | 67% 透明度 + 折叠 | hover → 100% 透明度；点击展开 | `<details>` 模式，最大 10rem |
| Tool Call | 67% 透明度 + 仅显示 header | hover → 100%；点击展开 body | 最大 7.5rem |
| Code Block | 完整显示，内部 scroll | — | — |
| 复制按钮 | 隐藏 (opacity: 0) | hover 消息气泡 | 渐入 |

**透明度规则**：非核心信息（thinking、tool call）初始 0.67 透明度，表示"可选关注"。用户 hover 时升至 1.0。这不是装饰，而是视觉权重管理——让用户的注意力默认流向 assistant 的文本回复。

#### Settings

- 顶层：堆叠 block（`.ga-set-block`），一眼可见所有配置类别
- 次层：Advanced toggle（展开/收起高级字段）
- 子视图：从 `main` 切到 `addModel` 等子 form 时，用 back-link 导航而非嵌套 modal

#### Services

- 默认：卡片列表显示服务名 + 状态指示
- hover：显露操作按钮（start/stop/logs）
- 展开：日志模态窗（全高 modal）

#### Statusbar

- 默认：20px 高度，显示关键指标的 inline 摘要
- 展开：点击 statusbar item → 向上弹出 popover panel（`.ga-bridge-panel`）
- Panel 内含多 tab（日志尾 + 操作按钮）

### 2.3 容器选择决策树

```
需要传达的信息 →
├─ 1-2 词补充说明 → Tooltip (L2)
├─ 一段描述但不打断当前 flow → Inline expand (details/toggle)
├─ 需要独立空间但不离开上下文 → Drawer (侧滑，有 backdrop)
├─ 需要全屏焦点、强制决策 → Modal (居中，阻塞)
└─ 一次性状态通知 → Toast (自动消失)
```

**不要为可逆操作弹 confirm modal。** Toast + 撤销 > 确认对话框。

---

## 3. Microcopy 设计原则

### 3.1 核心规则

1. **不泄露抽象**：用户面对的文字永远不包含内部文件名、变量名或技术概念。用户说"密钥配置"而非"mykey.py"，说"本地仓库"而非"GA 目录"。
2. **动词优先**：操作按钮用动词（导入 / 导出 / 连接 / 断开），不用名词。
3. **错误消息说后果，不说原因**：用户关心"能不能继续"而非"哪行代码报错"。技术细节属于 L3（日志/开发者工具），不上 Toast。

### 3.2 错误消息分类学

| 类型 | 用户体验 | 消息风格 | 实现方式 |
|------|---------|---------|---------|
| 验证失败 | 即时反馈，秒级 | 告诉用户哪里不对 + 怎么修 | Toast error |
| 操作超时 | 等待后失败 | 告诉用户"环境可能不完整" | Toast error |
| 静默回退 | 启动时发现问题 | 告诉用户"已自动处理" | Toast info（一次性） |
| 网络断开 | 持续状态 | 状态指示器变灰 + 重连中动画 | UI 状态变更 |

### 3.3 Toast vs Modal vs Inline

| 条件 | 选择 |
|------|------|
| 操作成功/失败通知，不需要用户做选择 | Toast |
| 不可逆破坏性操作（删除数据、断开连接后数据丢失） | Confirm Modal |
| 可逆操作的失败 | Toast error（不带 retry 按钮，用户自然会重试） |
| 持续性状态（连接中 / 离线） | Statusbar 指示器或 inline badge |
| 表单校验错误 | Inline（字段下方红字） |

### 3.4 i18n Key 命名

格式：`domain.camelCaseKey`

| 类型 | 命名模式 | 示例 |
|------|---------|------|
| 标签 | `domain.nounPhrase` | `data.importKey`, `nav.chat` |
| 按钮 | `domain.verbBtn` 或直接动词 | `data.importKeyBtn` |
| Tooltip | `domain.keyTip` | `data.importKeyTip` |
| 成功 | `domain.keySuccess` | `data.importKeySuccess` |
| 错误 | `domain.keyError` 或 `err.specificCase` | `data.localRepoErrTimeout` |

详细 microcopy 对照表见 `spec/microcopy.md`。

---

## 4. 视觉语言

### 4.1 颜色系统

双层 token 架构：

**语义层**（Desktop 自定义语义 token）：
- `--foreground` / `--background` — 全局前景/背景
- `--ui-text-secondary` / `tertiary` / `quaternary` — 文本权重递减
- `--ui-icon-nav` / `--ui-icon-nav-active` — 导航图标
- `--ui-row-hover-background` / `--ui-control-hover-background` — 交互反馈
- `--ui-accent` / `--theme-primary` — 强调色 (hsl 220)
- `--ui-chat-surface-background` / `--ui-chat-bubble-background` — 对话区域
- `--ui-stroke-tertiary` / `secondary` — 边框

**组件层**（Semi UI 框架提供）：
- `--semi-color-text-0/1/2/3` — 正文层级
- `--semi-color-fill-0/1/2` — 填充层级
- `--semi-color-primary` / `danger` / `warning` — 语义色
- `--semi-color-border` — 默认边框

**规则**：自定义 token 用于 shell（nav、sidebar、statusbar、thread）；Semi token 用于 Semi 组件内部和通用 UI 元素。两套体系通过主题切换同步。

### 4.2 暗色/亮色模式

- 切换机制：`<html data-appearance="dark">` + `<body theme-mode="dark">`
- 不跟随系统——用户手动选择
- 所有自定义 token 在 `[data-appearance="dark"]` 下重新定义
- 设计新组件时必须在两种模式下验证

### 4.3 排版

| 用途 | 字体 | 变量 |
|------|------|------|
| 正文/UI | 系统 sans-serif（SF Pro → PingFang → Microsoft YaHei） | `--font-sans` |
| 代码/模型名 | JetBrains Mono → 系统 monospace | `--font-mono` |
| 对话文本 | 同正文，但尺寸用户可调（10–20px） | `--chat-font` |
| 工具调用/标注 | `--conversation-tool-font-size: 0.6875rem` | — |

**规则**：模型名称、profile 名称、技术标识符永远使用 `--font-mono`。

### 4.4 图标

| 来源 | 用途 | 加载方式 |
|------|------|---------|
| VS Code Codicons | 导航、通用操作（展开/收起/复制/搜索） | `@font-face` 字体 |
| Semi Icons | 表单元素、Semi 组件内置图标 | React 组件 |

不引入第三方图标库。Codicon 覆盖不到的场景优先用 Semi Icons，其次用 inline SVG。

### 4.5 动效原则

1. **过渡优先**：所有状态变化用 `transition`（100–150ms ease-out），不用 `@keyframes` 动画
2. **唯一例外**：thinking shimmer（呼吸灯效果）和 loading spinner
3. **透明度渐变 = "可选关注"**：非核心信息默认 0.67 opacity，hover → 1.0
4. **禁止弹跳/overshoot**：Desktop 应用追求稳定感，不是 playful

### 4.6 布局适配

- 无 media query breakpoint（这是桌面应用，不是响应式网页）
- 宽度约束用 `min()` + CSS 变量上限（`--composer-width: 780px`）
- 高度填充用 `flex: 1; min-height: 0`，每一层都声明
- 溢出统一处理：`min-width: 0` on flex children + `text-overflow: ellipsis`
- 平台几何差异通过 `data-platform="macos|windows"` 选择器处理

---

## 5. 组件使用规范

### 5.1 Semi UI

直接使用，不做封装层：
```tsx
import { Button, Modal, Tooltip } from '@douyinfe/semi-ui';
```

不创建 `<MyButton>` 之类的 wrapper。如果需要统一样式，用 CSS class override（`.ga-` 前缀）。

### 5.2 自定义组件的 CSS 命名

- Class 命名：`ga-{domain}-{element}` BEM 风格（如 `.ga-nav-btn`、`.ga-data-row-label`）
- Thread 系统：使用 `data-slot` 属性选择器（如 `[data-slot="user-bubble"]`）——slot-based 选择器模型，保证组件可组合而不依赖 DOM 层级
- 状态表示：`data-*` 属性（`data-clamped`、`data-expanded`、`data-following`）

### 5.3 通知系统

使用自定义 store + portal（`NotificationStack`），不使用 Semi 的 `Notification` 组件：
- Error/Warning → 顶部居中，有关闭按钮，不自动消失
- Info/Success → 右下角，自动消失（3s）

Semi `Toast` 仍用于简单的一次性操作反馈（import/export 结果）。

### 5.4 表单

不使用表单库。手动构建：
- 行级容器：`.ga-form-field`
- 标签：`.ga-form-label`
- 高级折叠：`.ga-form-advanced-toggle`
- 输入组件直接使用 Semi 的 `Input` / `InputNumber` / `RadioGroup`

### 5.5 平台适配

```css
:root[data-platform="macos"] { --ga-titlebar-height: 38px; }
:root[data-platform="windows"] .ga-titlebar-controls { left: 8px; }
```

- macOS：系统流量灯占据左上角 72px 宽度，控制按钮放在流量灯右侧
- Windows：自绘标题栏，控制按钮放在左侧顶部
- 拖拽区域通过事件委托实现（`useDragWindow()` 检查 `y < 38px`）

---

## 附录：相关文档索引

| 文档 | 位置 | 内容 |
|------|------|------|
| Microcopy 对照表 | `spec/microcopy.md` | 数据维护区域的完整三层文案 + 错误路由 |
| 本地仓库连接契约 | `spec/local-repo-connection.md` | 连接流程状态机 + Rust 命令签名 + 验证规则 |
| 记忆导入设计 | `spec/memory-import.md` | 导入流程 + 后端 API 契约 |
| 模型选择契约 | `spec/model-selection.md` | Model Pill 行为 + 前后端分离协议 + Conductor 解耦 |
