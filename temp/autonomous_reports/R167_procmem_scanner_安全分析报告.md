# R167: procmem_scanner SOP实测 — 安全分析报告

> 扫描工具：Linux /proc 内存扫描器（procmem_scanner_sop流程的Linux移植版）
> 扫描目标：3个关键进程
> 日期：2026-06-06

---

## 一、SOP流程验证

| 步骤 | 描述 | 状态 |
|:----:|------|:----:|
| 1. 目标选定 | 选择≥3个运行中进程 | ✅ scheduler(538983), hermes dashboard(529684), TMWebDriver(539024) |
| 2. 内存区域枚举 | 读取/proc/PID/maps获取可读内存段 | ✅ 仅扫描含`r`权限的区域 |
| 3. 模式匹配 | 在内存中搜索字符串/特征 | ✅ 搜索"python""hermes""cdp"均命中 |
| 4. 上下文分析 | 提取命中地址前后32字节 | ✅ 含hex+ascii双视图 |
| 5. 安全分析 | 判断是否存在敏感信息泄露 | ✅ 见下文 |

**结论**：procmem_scanner_sop 流程在 Linux 上完整可用（需使用 /proc 替代 Win32 API）。

## 二、进程扫描结果

| PID | 名称 | 状态 | RSS | 搜索模式 | 匹配数 |
|:---:|:----:|:----:|:---:|:--------:|:-----:|
| 538983 | python3 (scheduler) | sleeping | 59MB | "python" | 9 |
| 529684 | hermes (dashboard) | sleeping | 177MB | "hermes" | 11 |
| 539024 | python3 (TMWebDriver) | sleeping | 70MB | "cdp" | 6 |

## 三、安全发现

### 🔴 发现1: Hermes Dashboard内存含敏感API信息
- **进程**: PID 529684 (hermes dashboard)
- **证据**: 内存中检测到 `NousResearch/hermes-4-70b`（模型路径引用），`hermes-achievements`（成就数据）
- **风险等级**: 🟡 中 — 可能泄露模型名称和内部数据路径

### 🟡 发现2: TMWebDriver内存含CDP连接配置
- **进程**: PID 539024 (TMWebDriver)
- **证据**: 内存中检测到 `"cdp_url":"","dialog` 及 `tmwd_cdp_bridge`
- **风险等级**: 🟡 中 — CDP URL可以为空，但若包含连接凭据则风险高

### 🟢 发现3: Scheduler内存仅含标准Python路径
- **进程**: PID 538983 (scheduler)
- **证据**: 匹配到 `pythonz`、`guido@python.org` 等标准开源信息
- **风险等级**: 🟢 低 — 无敏感信息

## 四、风险矩阵

| 风险项 | 可能性 | 影响 | 优先级 |
|:------:|:------:|:----:|:------:|
| Hermes内存含内部模型名称 | 中 | 低（内部引用，非凭据） | P3 |
| TMWebDriver内存含CDP配置 | 低 | 中（空URL当前安全） | P3 |
| 进程未做内存保护 | 高 | 中（所有进程均可读） | P2 |

## 五、建议

1. **P2** 对关键进程设置 `ptrace` 保护（`kernel.yama.ptrace_scope = 2`），阻止非授权内存读取
2. **P3** Hermes Dashboard 不应在内存中长期保留模型路径等元数据
3. **P3** TMWebDriver 的CDP连接信息建议运行后清零

---

*报告由自判别流程（procmem_scanner_sop + 安全分析）生成*
