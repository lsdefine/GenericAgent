# GA Switch Frontend Handoff

## 1. 文档目的

这份文档面向下一位接手 `GA Switch` 前端工作的工程师，目标是把当前工程状态、可运行环境、实现边界、近期收敛方向和后续独立视图方向一次性交代清楚，避免重复踩坑。

当前工作将分成两条线并行推进：

1. `GA 仓库内 PR 线`
   继续优化现有 `Qt` 前端，把 `GA Switch` 收口成一个可合入 GenericAgent 主仓库的正式工作台。
2. `独立仓库探索线`
   后续单独起一个仓库，做更完整、风格更成熟的独立视图，追求更好的视觉品质和交互体验。

这两条线共享同一套后端语义，不应该各自发明一套路由系统。

---

## 2. 项目上下文

### 2.1 当前目标

`GA Switch` 的核心目标不是“再加一个模型切换按钮”，而是把 GenericAgent 现有的多路由能力产品化：

- 显式路由
- 备用链路 / failover
- 健康状态
- 最近错误
- 手动测试
- 软重载
- 与聊天页联动

当前已经证明：

- 多路由本身可用
- `failover` 底层可用
- `mykey.py` 可导入到结构化配置
- `Qt` 前端已经能吃结构化快照并驱动切换/测试/诊断

因此下一阶段的主要问题已经不是“能不能做”，而是“如何把现有能力做成产品级前端”。

### 2.2 当前前端策略

当前主策略是：

- `Qt 优先`
- `Streamlit 回退`
- 不在 GA 主仓库里引入 `Tauri / Rust / Electron`
- 不把本地 `pixi` 变成仓库默认前提

也就是说：

- GenericAgent 内部的正式桌面前端方向是 `PySide6 / Qt`
- `Streamlit` 只保留兼容和回退价值
- 更激进、更独立的技术选型留给未来单独仓库

---

## 3. 当前工程状态

### 3.1 关键模块

#### 后端与运行时

- [agentmain.py](</D:/DEV/harness/generic-agent/agentmain.py>)
  - `GeneraticAgent` 持有 `ga_switch`
  - 支持 `set_active_route(...)`
  - 支持 `reload_llm_config(...)`
  - 支持 `describe_llms()`
- [ga_switch/service.py](</D:/DEV/harness/generic-agent/ga_switch/service.py>)
  - 对外服务层
  - 提供 `get_ui_snapshot(agent)`
  - 提供 `upsert_provider / upsert_route / run_model_test / import_legacy_mykey`
- [ga_switch/viewmodel.py](</D:/DEV/harness/generic-agent/ga_switch/viewmodel.py>)
  - 纯 Python 视图模型层
  - 将 `get_ui_snapshot()` 转成前端可直接消费的结构
  - 当前已经输出中文化的 section、summary、overview、empty_state、edit_groups
- [llmcore.py](</D:/DEV/harness/generic-agent/llmcore.py>)
  - 底层 session 和诊断
  - 已记录 `last_error_kind / last_error_message / last_ok_at / last_status_code`

#### Qt 前端

- [frontends/qtapp.py](</D:/DEV/harness/generic-agent/frontends/qtapp.py>)
  - GenericAgent 原生桌面壳
  - 聊天页、历史页、手册页、路由页、设置页
  - 聊天页顶部已经有路由状态条
  - `launch.pyw` 成功进入 Qt 时会落到这里
- [frontends/qt_switch.py](</D:/DEV/harness/generic-agent/frontends/qt_switch.py>)
  - `RouteCenterPage`
  - 当前已经完成第二轮信息架构收口：
    - `总览`
    - `全部路由`
    - `模型服务`
    - `诊断记录`
  - 已做全中文和渐进式披露的第一版

#### Streamlit 保留前端

- [frontends/stapp.py](</D:/DEV/harness/generic-agent/frontends/stapp.py>)
  - 旧主 UI，保留 fallback 价值
- [frontends/ga_switch_admin.py](</D:/DEV/harness/generic-agent/frontends/ga_switch_admin.py>)
  - 工程管理台
  - 不再是正式体验主方向

### 3.2 启动逻辑

- [launch.pyw](</D:/DEV/harness/generic-agent/launch.pyw>)
  - 优先探测 `PySide6`
  - 能用则进入 `Qt`
  - 否则回退到 `Streamlit + pywebview`

### 3.3 当前已有参考资料

- [docs/CC_SWITCH_UI_AUDIT.md](</D:/DEV/harness/generic-agent/docs/CC_SWITCH_UI_AUDIT.md>)
  - 已对 `cc-switch` 做过一轮 UI 审核
  - 本地 clone 路径：`D:\DEV\harness\cc-switch`

---

## 4. 本机环境说明

### 4.1 当前机器

- OS：Windows
- Shell：PowerShell 5.1
- 工作区：`D:\DEV\harness`
- GenericAgent 仓库：`D:\DEV\harness\generic-agent`

### 4.2 Python / 运行时现状

当前这台机器有两套现实：

1. 仓库常规 Python 路径
   - `python` 解析到：`C:\Users\苏祎成\AppData\Local\Microsoft\WindowsApps\python.exe`
2. 本地可用的 `pixi`
   - `where.exe pixi` -> `D:\EnvironmentCache\pixi_home\bin\pixi.exe`
   - `pixi --version` -> `pixi 0.66.0`

### 4.3 Qt 的本机特殊问题

这台机器上，GenericAgent 现有 `.venv` 里的 `PySide6` 不是可靠状态。

实际开发时，`Qt` 前端目前是通过下面这条命令稳定启动的：

```powershell
pixi exec --spec "python=3.11" --spec pyside6 --spec requests python frontends\qtapp.py
```

这只是**本机开发 workaround**，不是仓库交付约束。

### 4.4 这条 workaround 的工程含义

必须明确：

- 可以在本机继续用 `pixi` 调试 Qt
- 不能把 `pixi.toml`、锁文件、repo 级强依赖写进 GenericAgent PR
- 不能让“仓库默认可运行”依赖 `pixi`

换句话说：

- `pixi` 是本机开发环境
- 不是 GenericAgent 主仓库的产品依赖

---

## 5. 当前工作约束

### 5.1 PR 线约束

下面这些约束已经明确，不建议在 GA 主仓库里打破：

1. 不引入 `Tauri / Rust / Electron`
2. 不把 `pixi` 变成 repo 基础配置
3. `PySide6` 仍然按“可选桌面依赖”处理
4. `launch.pyw` 继续保持 `Qt 优先，Streamlit 回退`
5. `Streamlit` 前端必须还能作为 fallback 使用
6. 不轻易改 `ga_switch` 的数据库 schema
7. UI 必须继续复用现有结构化接口，而不是绕过它直接读 session 细节

### 5.2 前端实现约束

Qt 前端继续工作时，请遵守下面的技术边界：

1. 首选使用 [ga_switch/service.py](</D:/DEV/harness/generic-agent/ga_switch/service.py>) 的 `get_ui_snapshot(agent)`
2. 前端状态整理由 [ga_switch/viewmodel.py](</D:/DEV/harness/generic-agent/ga_switch/viewmodel.py>) 承担
3. 具体动作继续走：
   - `agent.set_active_route(...)`
   - `agent.reload_llm_config(...)`
   - `service.import_legacy_mykey(...)`
   - `service.run_model_test(...)`
   - `service.upsert_provider(...)`
   - `service.upsert_route(...)`
4. 不要在 Qt 页里直接拼装 `llmcore` 内部细节
5. 不要新增一套“只给 Qt 用、后端完全不认识”的路由语义

### 5.3 体验约束

这一轮前端已经锁定了几个产品方向，后续不应回退：

1. 全中文用户界面
2. 路由总览优先
3. 渐进式披露
4. 高级设置默认折叠
5. 诊断原始 JSON 默认折叠
6. 首屏不再出现工程态三栏工作台和常驻长表单

---

## 6. 当前 UI 收敛方向

### 6.1 已经完成的方向

目前 `Qt Route Center` 已经从工程台形态转成第一版产品态：

- 一级导航改为：
  - `总览`
  - `全部路由`
  - `模型服务`
  - `诊断记录`
- 路由页默认先看摘要，不直接摊开表单
- 模型服务页默认先看摘要和最近状态
- 空状态有明确动作入口
- 聊天页与路由页已经联动

### 6.2 还没有完成的部分

这版还只能算“结构收拢到位，视觉品质未到位”。

当前剩余问题主要在：

1. 卡片密度和间距还偏粗糙
2. 按钮层级还不够克制
3. 深色主题的精致度不够
4. 列表项的状态表达还不够漂亮
5. 还没有做真正统一的视觉语言
6. 宿主壳的老风格与新路由页之间还有轻微割裂

### 6.3 PR 线建议收敛目标

如果是继续在 GenericAgent 内优化 UI 并开 PR，建议只收敛到下面这个层级：

1. 让 Qt 版 `路由` 页成为可长期使用的正式工作台
2. 继续提升视觉精度，但不重做技术栈
3. 保持与聊天页的高耦合联动
4. 不追求“独立产品壳”，而追求“GenericAgent 内自然的一部分”

这条线更适合做：

- 视觉 polish
- 交互节奏优化
- 卡片层级
- 状态 chips
- 列表/详情的动线优化
- 空状态和错误状态设计

不适合做：

- 全新桌面容器
- 新的跨进程通信层
- 前后端分离重构

---

## 7. 独立仓库方向建议

### 7.1 为什么值得单独做

GenericAgent 内的 Qt 版更适合“贴近宿主能力的正式工作台”。

如果目标变成：

- 更激进的视觉语言
- 更完整的独立产品感
- 更自由的 UI 架构
- 更接近 `cc-switch` 乃至超过它的桌面体验

那单独起仓库是合理的。

### 7.2 独立仓库不应该重复造什么

独立仓库可以换壳，但不应该再重造下面这些东西：

1. 路由语义
2. provider / route / diagnostic event 数据结构
3. active route / soft reload / model test 的语义
4. `legacy mykey` 导入语义

更好的方式是：

- 继续复用 `ga_switch` 的领域模型
- 明确一层稳定的服务契约
- 独立仓库只重做“视图”和“交互壳”

### 7.3 独立仓库建议前提

在真正独立之前，建议先把下面两件事补齐：

1. 把 `get_ui_snapshot()` 和视图模型字段进一步稳定下来
2. 明确一份“前端契约文档”，避免新仓库反向绑死主仓库内部实现

换句话说，独立仓库应建立在“后端契约已稳定”的前提上，而不是直接复制现在的 Qt 页面。

---

## 8. 关键文件导览

### 8.1 直接相关文件

- [launch.pyw](</D:/DEV/harness/generic-agent/launch.pyw>)
  - 入口与 Qt/Streamlit fallback
- [frontends/qtapp.py](</D:/DEV/harness/generic-agent/frontends/qtapp.py>)
  - 桌面壳
  - 聊天页与路由页联动
- [frontends/qt_switch.py](</D:/DEV/harness/generic-agent/frontends/qt_switch.py>)
  - Route Center 主体
- [ga_switch/viewmodel.py](</D:/DEV/harness/generic-agent/ga_switch/viewmodel.py>)
  - 前端视图模型
- [ga_switch/service.py](</D:/DEV/harness/generic-agent/ga_switch/service.py>)
  - 后端服务入口
- [agentmain.py](</D:/DEV/harness/generic-agent/agentmain.py>)
  - agent 与 ga_switch 的 runtime 绑定
- [tests/test_ga_switch.py](</D:/DEV/harness/generic-agent/tests/test_ga_switch.py>)
  - 结构化配置、视图模型、payload builder、reload 相关测试

### 8.2 参考文件

- [docs/CC_SWITCH_UI_AUDIT.md](</D:/DEV/harness/generic-agent/docs/CC_SWITCH_UI_AUDIT.md>)
- [README.md](</D:/DEV/harness/generic-agent/README.md>)
- [GETTING_STARTED.md](</D:/DEV/harness/generic-agent/GETTING_STARTED.md>)

---

## 9. 当前已知问题与注意事项

### 9.1 本机环境问题

这台机器当前最实际的问题是：

- GenericAgent 现有 `.venv` 中的 `PySide6` 不可靠
- 所以本机 Qt 调试走的是 `pixi`

这不是仓库设计目标，而是本机现实。

### 9.2 工作树状态

当前仓库是脏工作树，已有较多未提交改动，包括：

- `ga_switch/`
- `frontends/qt_switch.py`
- `frontends/qtapp.py`
- `launch.pyw`
- `agentmain.py`
- `llmcore.py`
- 文档与测试文件

接手时不要假定工作树是干净的，也不要粗暴回滚。

### 9.3 Qt 页面还不是最终视觉稿

当前 Qt 路由页只能算：

- 信息架构已进入正确方向
- 可用性显著好于第一版
- 但还远未达到“高完成度美术品质”

因此：

- 如果是继续开 PR，请聚焦在“收敛和 polish”
- 如果是单独仓库，请把它当成“产品语义样板”，而不是视觉最终稿

---

## 10. 建议工作流

### 10.1 GenericAgent 内继续优化并开 PR

建议顺序：

1. 先稳定 `qt_switch.py` 的视觉和交互
2. 再统一 `qtapp.py` 宿主层的风格和用词
3. 尽量把前端展示逻辑继续下沉到 `ga_switch/viewmodel.py`
4. 每次改完都回归：
   - `tests.test_ga_switch`
   - `tests.test_minimax`
5. 保持 `launch.pyw` 的 fallback 逻辑不破

### 10.2 单独仓库方向

建议顺序：

1. 先冻结一版服务契约
2. 明确“宿主模式”和“独立模式”的边界
3. 再决定新仓库 UI 技术栈
4. 优先复用现有 `ga_switch` 语义，而不是复制 Qt 页面代码

---

## 11. 建议验收清单

### 11.1 PR 线验收

至少保证：

1. `launch.pyw` 在安装了 `PySide6` 时优先进 Qt
2. 缺 `PySide6` 时仍能回退到 Streamlit
3. 聊天页能明确看到当前路由、当前成员、最近错误
4. 路由页能完成：
   - 创建/编辑路由
   - 创建/编辑模型服务
   - 切换当前路由
   - 连通性测试
   - 软重载
   - 导入 `mykey`
5. 编辑时不应因高级设置未展开而抹掉已有高级值
6. UI 文案不再混用英文工程词

### 11.2 独立仓库线验收

至少保证：

1. 独立视图不重新发明路由语义
2. 能读稳定契约
3. 聊天联动语义不丢
4. 最近错误、健康状态、备用链路语义完整保留

---

## 12. 已验证命令

### 12.1 仓库内测试

```powershell
python -m unittest tests.test_ga_switch tests.test_minimax
```

本轮最近一次回归结果：

- `31` 个测试通过

### 12.2 本机 Qt 启动

```powershell
pixi exec --spec "python=3.11" --spec pyside6 --spec requests python frontends\qtapp.py
```

### 12.3 仓库标准入口

```powershell
python launch.pyw
```

---

## 13. 推荐交接结论

如果下一位工程师是专业前端工程师，建议这样切分任务：

### 阶段 A：GenericAgent 内 PR

目标：

- 把 `Qt Route Center` 打磨到“可以合入、可以长期使用”的程度

关注点：

- 视觉 polish
- 交互动线
- 中文化一致性
- 状态层级
- 空状态 / 错误状态体验

不要做：

- 新技术栈迁移
- 新运行时依赖体系
- 与宿主脱钩

### 阶段 B：独立仓库

目标：

- 在不背离现有后端语义的前提下，做一个更自由、更高完成度的独立视图

关注点：

- 更成熟的 UI 语言
- 更完整的独立桌面感
- 更高的视觉上限

不要做：

- 重造路由内核
- 重造测试 / 诊断 / 软重载语义

---

## 14. 一句话总结

当前 `GA Switch` 已经完成了从“底层能力存在”到“结构化产品工作台”的第一步。

下一位前端工程师的真正任务，不是从零发明一个模型切换器，而是：

- 在 GenericAgent 内，把现有 Qt 工作台收敛成一个成熟、统一、可合入的正式前端；
- 在未来独立仓库里，把同一套语义做成更高上限的独立视图。
