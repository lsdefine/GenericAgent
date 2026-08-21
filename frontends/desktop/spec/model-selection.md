# Model Selection — 设计契约

## 1. 核心原则：前后端分离

模型选择遵循 **读/申请** 模式：

| 角色 | 职责 | 不做 |
|------|------|------|
| 前端 | 读取当前模型状态并展示；向后端申请切换 | 不持有模型真相；不缓存"应该用哪个模型" |
| Bridge | 持有每个 session 的 `llm_no` 绑定；执行切换；在每次 response 中返回权威模型状态 | 不由前端强制覆盖 |
| GenericAgent | 持有 `self.llm_no` 和活跃的 `llmclient` | 可以在运行中自行切换模型 |

**前端永远不是 source of truth。** 前端显示的模型必须来自后端最近一次返回的数据，而不是前端自己记住的上一次操作。

---

## 2. 模型绑定层级

模型选择是 **per-session** 的，有 fallback 链：

```
session.llm_no  →  global default (ui.llmNo)  →  0 (第一个 profile)
```

| 层级 | 持久化位置 | 修改入口 |
|------|-----------|---------|
| Session 绑定 | `temp/desktop_sessions/{id}.json` → `llm_no` 字段 | `POST /session/{sid}/model` |
| 全局默认 | `~/.ga_desktop_settings.json` → `ui.llmNo` | `POST /config` (body: `{llmNo}`) |
| Conductor 绑定 | `~/.ga_desktop_settings.json` → `conductor.llmNo` | `POST /services/conductor/model` |

**设计要求**：
- 切换会话时，Model Pill 必须反映目标会话的绑定，而非上一个会话的选择
- 新建会话继承全局默认；用户在新会话中切换模型后，该绑定跟随会话持久化
- Conductor 拥有独立绑定，不受 chat 会话模型切换的影响

---

## 3. Model Pill（ModelSelector 组件）

### 3.1 显示状态

Model Pill 在 Composer 工具栏中显示当前会话使用的模型。

| 状态 | Pill 显示内容 | 来源 |
|------|-------------|------|
| Idle，有 session 绑定 | 模型短名（如 `claude-4-sonnet`） | `session.llm_no` 对应 profile |
| Running，模型与绑定一致 | 模型短名 | `running_model` |
| Running，模型与绑定不一致 | `当前模型 → 下次模型`（如 `claude → deepseek`） | `running_llm_no` + `llm_no` |
| 无 session（首次打开） | 全局默认的模型名 | `ui.llmNo` 对应 profile |

### 3.2 选择行为

| 场景 | 用户操作 | 系统行为 |
|------|---------|---------|
| Idle + 有活跃 session | 点击 pill → 选择模型 | `POST /session/{sid}/model` → 即时生效（`agent.next_llm`）|
| Running + 有活跃 session | 点击 pill → 选择模型 | `POST /session/{sid}/model` → 绑定更新，下次 turn 生效 |
| 无活跃 session | 点击 pill → 选择模型 | 前端暂存选择；创建 session 时绑定 |
| 切换到另一个 session | 点击 sidebar 会话 | Pill 重置 → poll 返回新 session 的 `model.llmNo` → 更新显示 |

### 3.3 前端状态同步协议

1. **Optimistic update**：用户选择后立即更新 UI（避免感知延迟）
2. **API confirm**：收到 response 后用 `response.model.llmNo` 覆盖本地状态
3. **Rollback**：API 失败时恢复到上一次已确认的值
4. **Session switch**：将 `sessionModelNo` 置 null → poll 新 session → 用 response 中的 `model.llmNo` 填充

**关键约束**：`pollMessages` 的 response 始终包含 `model` 字段，前端每次 poll 都从中更新显示状态。这保证即使后端自行切换了模型（如 agent 内部 `next_llm`），前端也能反映。

---

## 4. 数据流

### 4.1 用户切换模型

```
用户点击 Model Pill → 选择模型 X (index = N)
  │
  ├─ 前端: sessionModelNo = N (optimistic)
  │
  ├─ POST /session/{sid}/model  { llmNo: N }
  │     │
  │     └─ Bridge:
  │          sess.llm_no = N (持久化)
  │          if idle && agent: agent.next_llm(N)  → 立即生效
  │          if running: 下次 turn 生效
  │          return { ok, model: { llmNo, current, isMixin, ... } }
  │
  └─ 前端: 用 response.model 更新 Pill 显示
```

### 4.2 切换会话

```
用户点击 Sidebar 会话 B
  │
  ├─ 前端: sessionModelNo = null (清空)
  │
  ├─ GET /session/B/messages
  │     │
  │     └─ response.model.llmNo = 会话 B 的绑定
  │
  └─ 前端: sessionModelNo = response.model.llmNo
         → Pill 显示会话 B 的模型
```

### 4.3 Agent 自行切换模型

```
Agent 内部: self.next_llm(M)  (如 reflection、auto-fallback)
  │
  ├─ Bridge: 下次 poll 时 _live_model() 返回新的 running_model
  │
  └─ 前端: poll response.model → 更新 Pill
         → 显示 agent 实际使用的模型（可能与用户选择不同）
```

---

## 5. Conductor 模型选择

Conductor 拥有独立的模型绑定，与 chat 会话解耦：

| 属性 | 行为 |
|------|------|
| 持久化 | `~/.ga_desktop_settings.json` → `conductor.llmNo` |
| Fallback | 若未设置或无效 → 使用 `ui.llmNo`（全局默认）→ 使用 0（首个可用） |
| 生效时机 | 每次 conductor task 开始前重新读取，无需重启 |
| 前端入口 | Services 页面或 Collab 页面中的独立 model selector |
| API | `GET/POST /services/conductor/model` |

**设计要求**：Conductor 的模型选择 UI 独立于 Chat Composer 中的 Model Pill。两者互不影响。

---

## 6. Wrong vs Correct

### Wrong — 前端持有模型真相

```tsx
// 用户切了模型，前端记住，切换会话时不清空
const [modelNo, setModelNo] = useState(0);  // ← 全局，不跟 session
```

结果：会话 A 用 Claude 在跑，切到会话 B 选了 DS，切回 A → Pill 显示 DS（但后端实际跑的是 Claude）。

### Correct — 前端只读后端

```tsx
// sessionModelNo 每次 session switch 清空，从 poll 重建
setActiveSession(id) {
  set({ sessionModelNo: null });  // 清空
  pollMessages(id).then(res => {
    set({ sessionModelNo: res.model.llmNo });  // 后端说什么就显示什么
  });
}
```

结果：切回会话 A → Pill 显示 Claude（后端当前绑定）。

### Wrong — Conductor 继承 chat 模型

```python
# conductor 每次 task 前读 chat 的 llm_no
conductor_model = current_chat_session.llm_no  # ← 耦合
```

结果：用户在 chat 切了个便宜模型来做快速问答，conductor 的复杂编排也用了这个模型。

### Correct — Conductor 独立绑定

```python
# conductor 有自己的持久化配置
no = settings.get("conductor", {}).get("llmNo")  # 独立
if no is None or no >= len(clients):
    no = global_default_llm_no()  # fallback
```

---

## 7. UI 行为规格

| 场景 | 预期 UI 表现 |
|------|------------|
| 打开 app，无历史 | Pill 显示全局默认模型 |
| 新建会话前选模型 | Pill 更新；发送第一条消息后绑定到新 session |
| 运行中切换模型 | Pill 显示过渡态 `当前 → 下次`；本轮结束后切为新模型 |
| 切换到另一会话 | Pill 0 延迟内显示目标会话的绑定模型 |
| Agent 自行切换 | Pill 在下次 poll 后更新为 agent 实际使用的模型 |
| Conductor 独立运行 | Chat 的 Pill 不受 conductor 模型影响 |
| 网络断开 | Pill 保持最后已确认状态，不尝试切换 |

---

## 8. 验收标准

- [ ] 切换会话后 Model Pill 始终反映目标会话的后端绑定
- [ ] 并行运行的不同会话可以各自使用不同模型
- [ ] Agent 内部切换模型后，Pill 在 ≤1s poll 周期内更新
- [ ] Conductor 模型设置独立于任何 chat 会话
- [ ] API 失败时 Pill 回滚到上一已确认状态，不停留在错误值
- [ ] 前端不存在不经 API confirm 就持久显示的模型状态
