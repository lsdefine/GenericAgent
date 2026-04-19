# CC Switch UI Audit For GA Switch

本地参考基线：

- Clone 路径：`D:\DEV\harness\cc-switch`
- 主截图：`cc-switch/assets/screenshots/main-en.png`
- 添加 Provider 截图：`cc-switch/assets/screenshots/add-en.png`
- 关键源码：
  - `cc-switch/src/App.tsx`
  - `cc-switch/src/components/providers/ProviderList.tsx`
  - `cc-switch/src/components/providers/ProviderCard.tsx`
  - `cc-switch/src/components/providers/ProviderHealthBadge.tsx`

## Keep

- 顶部主状态区：品牌、当前主视图、明显的控制入口，信息层级很清楚。
- 大圆角 provider 卡片：名称、URL、当前使用状态、余额/配额等摘要信息都在一层完成扫描。
- 状态 chip：`current / health / failover priority` 这类信息直接贴在卡片上，不藏在详情页。
- “列表为主，编辑单独展开”的节奏是对的，能降低误操作和视线跳跃。

## Change

- 模块数量太多，不适合 GA 第一环照搬。GA 第一环只保留 `Routes / Providers / Diagnostics / Tests / Runtime`。
- `cc-switch` 的壳偏“多产品总控台”，而 GA 的主价值还是“路由 + 聊天联动”，所以不能让聊天入口退到次要位置。
- 它的 provider 体系过宽，包含多产品、多协议、多 OAuth 流程；GA 第一环只应该围绕现有 `provider / route / failover / diagnostics` 收口。

## GA-Specific Additions

- 必须显式显示当前 active route，而不只是 active provider。
- failover 路由必须显示成员顺序、当前 active member、最近切换原因。
- 最近一次错误要在聊天页和管理页都可见，而不是只在诊断列表里。
- 主聊天页需要显式切路由和跳转到管理页，避免“配置页”和“使用页”割裂。

## Implementation Direction

- 管理台参考 `cc-switch` 的信息架构和卡片节奏，但不照搬它的全量模块。
- 第一环以 Streamlit 为宿主，先保证可运行、可查验、可联动。
- 后续如果要独立壳，再评估把当前三段式工作台迁移到更桌面化的宿主。
