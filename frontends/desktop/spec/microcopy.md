# Desktop Microcopy Spec — Settings "数据维护" Section

## Design Decision: Three-Layer Information Architecture

**Context**: Settings panel operations need to communicate what they do without overwhelming the scan. The previous design put medium-length descriptions inline, creating an awkward layer that was too long for scanning but too short for full explanation.

**Decision**: 采用三层信息架构：

| Layer | Role | Length | GA Implementation |
|-------|------|--------|-------------------|
| Layer 1: Inline label | 扫视级 — user sees it immediately | 2-4 中文字 / 2-3 英文词 | `.ga-data-row-label` |
| Layer 2: Tooltip | 解释级 — hover/focus reveals detail | 4-8 中文字 / 3-8 英文词 | `<Tooltip>` on label |
| Layer 3: Panel | 诊断级 — full documentation | Sentences | Not needed here |

**Rule**: When Layer 1 label is already a complete verb phrase (e.g., button text "导入"), the label itself is sufficient — no tooltip needed on the button. Tooltip goes on the **row label** (the noun phrase) to explain what the thing IS, not what the button does.

---

## Convention: No Abstraction Leaks in User-Facing Text

**What**: Internal names (`mykey`, `源目录`, `GA 目录`) must not appear in user-facing microcopy.

**Why**: Users don't know what `mykey.py` is. They know "密钥配置" (key config). They don't know "GA 目录" — they know "本地仓库" (local repo). Abstraction leaks create confusion and erode product credibility.

**Mapping**:

| Internal concept | User-facing label (zh) | User-facing label (en) |
|-----------------|----------------------|----------------------|
| `mykey.py` | 密钥配置 | Key config |
| GA source directory / checkout | 本地仓库 | Local repository |
| memory/ directory | 记忆与会话 | Memory & sessions |
| `desktop_bridge.py` | (never shown) | (never shown) |
| `agentmain.py` | (never shown in label; validation error says "无效仓库") | (never shown) |

---

## Microcopy Table v2

### Section title

| Key | zh | en |
|-----|----|----|
| `data.title` | 数据维护 | Data |

### 导入密钥配置 (was: 导入 mykey)

| Key | zh | en | Layer |
|-----|----|----|-------|
| `data.importKey` | 导入密钥配置 | Import key config | L1 label |
| `data.importKeyTip` | 从本地 .py 文件导入模型密钥与接口地址 | Import model keys and endpoints from a local .py file | L2 tooltip |
| `data.importKeyBtn` | 导入 | Import | button |
| `data.importKeySuccess` | 密钥配置已导入 | Key config imported | toast |
| `data.importKeyError` | 导入失败 | Import failed | toast |

### 导出密钥配置 (was: 导出 mykey)

| Key | zh | en | Layer |
|-----|----|----|-------|
| `data.exportKey` | 导出密钥配置 | Export key config | L1 label |
| `data.exportKeyTip` | 将当前密钥与接口配置保存为文件，便于迁移 | Save current keys and endpoints to a file for portability | L2 tooltip |
| `data.exportKeyBtn` | 导出 | Export | button |
| `data.exportKeySuccess` | 已导出 | Exported | toast |
| `data.exportKeyError` | 导出失败 | Export failed | toast |

### 导入记忆与会话 (was: 导入记忆)

| Key | zh | en | Layer |
|-----|----|----|-------|
| `data.importData` | 导入记忆与会话 | Import memory & sessions | L1 label |
| `data.importDataTip` | 从另一个本地仓库合并记忆文件和历史会话 | Merge memory files and session history from another local repository | L2 tooltip |
| `data.importDataBtn` | 选择仓库 | Pick repository | button |
| `data.importDataSuccess` | 导入完成 — {copied} 个文件，{skipped} 个跳过 | Done — {copied} files, {skipped} skipped | toast |
| `data.importDataError` | 导入失败 | Import failed | toast |
| `data.importDataNoData` | 所选目录中未找到记忆或会话数据 | No memory or session data found | toast |

### 连接本地仓库 (was: 连接源目录)

| Key | zh | en | Layer |
|-----|----|----|-------|
| `data.localRepo` | 连接本地仓库 | Connect local repository | L1 label |
| `data.localRepoTip` | 使用本地 GA 仓库作为运行时，实时共享记忆和会话 | Use a local GA repository as runtime, sharing memory and sessions live | L2 tooltip |
| `data.localRepoPick` | 选择仓库 | Pick repository | button |
| `data.localRepoChange` | 更换 | Change | button |
| `data.localRepoDisconnect` | 断开 | Disconnect | button |
| `data.localRepoConnected` | 已连接 | Connected | status |
| `data.localRepoSwitching` | 切换中… | Switching… | status |
| `data.localRepoSuccess` | 已连接 — 运行时已切换 | Connected — runtime switched | toast |
| `data.localRepoCleared` | 已断开，回到内置运行时 | Disconnected — using built-in runtime | toast |
| `data.localRepoError` | 无效仓库 | Invalid repository | toast |
| `data.localRepoSwitchFailed` | 切换失败 | Switch failed | toast |

---

## Visual Hierarchy Rules for DataSection

1. **All operations live under one "数据维护" heading** — no sub-headings that make items look independent
2. **Divider separates ephemeral ops from persistent connection** — import/export are one-shot; "连接本地仓库" is persistent state. The divider marks this boundary.
3. **GaSourceBlock does NOT get its own section title** — it uses the same `.ga-data-row-label` styling as OpRow labels, keeping visual weight consistent
4. **Tooltip on row labels** — each label is wrapped in `<Tooltip content={t('..Tip')}>`, providing Layer 2 explanation on hover without cluttering the scan layer

---

## Component Pattern: OpRow with Tooltip

```tsx
function OpRow({ label, tip, btnText, onClick, disabled }: OpRowProps) {
  return (
    <div className="ga-data-row">
      <div className="ga-data-row-info">
        <Tooltip content={tip}>
          <span className="ga-data-row-label">{label}</span>
        </Tooltip>
      </div>
      <Button size="small" type="tertiary" onClick={onClick} disabled={disabled}>
        {btnText}
      </Button>
    </div>
  );
}
```

Key differences from v1:
- `desc` prop removed — no inline description text
- `tip` prop added — tooltip content for Layer 2
- Label wrapped in `<Tooltip>` with the tip text
- No `.ga-data-row-desc` rendered

---

## Wrong vs Correct

### Wrong: Inline description as explanation

```tsx
<div className="ga-data-row-label">导入 mykey</div>
<div className="ga-data-row-desc">从本地文件导入模型配置</div>
```

Problems:
- "mykey" is an internal name
- Description is always visible, cluttering scan layer
- Neither short enough for L1 nor detailed enough for L2

### Correct: Clean label + tooltip explanation

```tsx
<Tooltip content={t('data.importKeyTip')}>
  <span className="ga-data-row-label">{t('data.importKey')}</span>
</Tooltip>
```

Result: user sees "导入密钥配置" at scan level; hovering reveals "从本地 mykey.py 导入模型密钥与接口地址"

---

## Failure Modes & Error Microcopy

### Failure Taxonomy

"连接本地仓库" has three failure classes, each requiring distinct messaging:

| # | Failure | Cause | Rust behavior | User sees |
|---|---------|-------|---------------|-----------|
| F1 | 结构验证失败 | 选的目录缺 `agentmain.py` | `set_ga_source` returns Err immediately | Toast error — 无效仓库 |
| F2 | 兼容性探测失败 | 外部核心不满足 Desktop 2.0 契约 | 写设置前返回 Err | Toast error — 核心不兼容 |
| F3 | 运行时启动超时 | 包内 bridge 没有在预期时间就绪 | 恢复旧设置并回滚启动 | Toast error — 启动超时 |
| F4 | 启动时静默 fallback | 上次连接的仓库已被移动/删除 | `valid_ga_source_override()` returns None → 用 bundle | 状态回到 idle + 一次性 toast 告知 |

### Error Microcopy Table

| Key | zh | en | Trigger |
|-----|----|----|---------|
| `data.localRepoErrNoAgent` | 无效仓库 — 未找到 agentmain.py | Invalid — agentmain.py not found | F1: missing agentmain |
| `data.localRepoErrIncompatible` | 该核心与 Desktop 2.0 不兼容 | This core is incompatible with Desktop 2.0 | F2: probe failure |
| `data.localRepoErrTimeout` | 启动超时 — 仓库环境可能不完整 | Startup timed out — environment may be incomplete | F3: readiness timeout |
| `data.localRepoErrNoResolve` | 无法定位运行时 | Cannot resolve runtime | F2: empty project string |
| `data.localRepoFallback` | 上次连接的仓库不可用，已回到内置运行时 | Previously linked repository unavailable — using built-in runtime | F3: startup fallback |
| `data.localRepoSwitchFailed` | 切换失败 | Switch failed | Catch-all |

### Design Decisions

1. **F1 只验证核心入口**：外部仓库不需要自带 Desktop bridge。
2. **F2 提供产品级结论**：不在 Toast 展开 probe 细节，只告知与 Desktop 2.0 不兼容。
3. **F3 不暴露技术细节**：不说 "port 14168" 或 "Python" — 说"环境可能不完整"。
4. **F4 用一次性 toast**：启动时的 fallback 不应该弹 modal 打断用户。
4. **错误消息不用 confirm/retry 按钮**：所有操作可逆且可重试，toast 消失后用户自然会重新操作

### Fallback Safety Net (Rust layer — DO NOT MODIFY)

```
valid_ga_source_override():
  settings.ga_source_override → validate(agentmain.py)
  → valid: return Some(path)  → injected as GA_ROOT into the bundled bridge
  → invalid/missing: return None → fallback to bundle's runtime/app/
```

This means the app can NEVER be bricked by a stale source override. The worst case is it silently falls back to the embedded runtime — which is exactly the right default.

### Frontend Error Routing

The Rust error strings are English technical messages. Frontend should pattern-match on keywords to select the right i18n key:

```tsx
function mapSourceError(msg: string, t: TFn): string {
  if (msg.includes('agentmain.py')) return t('data.localRepoErrNoAgent');
  if (msg.includes('not compatible') || msg.includes('compatibility probe')) {
    return t('data.localRepoErrIncompatible');
  }
  if (msg.includes('20s') || msg.includes('ready')) return t('data.localRepoErrTimeout');
  if (msg.includes('no GenericAgent source')) return t('data.localRepoErrNoResolve');
  return t('data.localRepoSwitchFailed');
}
```

This keeps Rust errors stable (English, technical) while frontend renders localized user-facing messages.
