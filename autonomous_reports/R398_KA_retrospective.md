# R398 | v111#6 — knowledge_assets实用性回测报告

**抽查范围**: v108, v109, v110 (最近3轮任务)
**验收标准**: ≥1条已存在的KA未被使用，或≥1条缺失的KA应补充
**结论**: ✅ 发现 **2条已存在但未使用的KA** + **2条缺失的KA需补充**

---

## 1️⃣ [已存在但未使用] Pattern #3 超时问题排查模式

**模式**: 超时问题排查 (来源R233): "基准测试失败 ≠ 服务故障。应优先调大 timeout 复现"

**场景**: v108#3 因 RateLimit 被永久阻塞，6项TODO中唯一未完成项

**分析**: 
- Pattern #3 提供"超时→调大timeout→复现→诊断"的框架
- v108#3 遇到的是 RateLimit 而非超时，但同类结构化排查思维可迁移
- 若在v108执行初期通过 knowledge_injector 注入该模式，可能帮助区分"硬限流" vs "瞬态限流"，改变任务策略而非直接放弃

**证据**: v108结束语明确标注"#3 RateLimit阻塞" — 无任何回退/重试策略记录

## 2️⃣ [已存在但未使用] Pattern #31 自治恢复闭环

**模式**: 自治恢复闭环 (来源R312): DETECT → RECOVER → VERIFY → RECORD

**场景**: v110 OOM防御体系建设

**分析**:
- v110 核心主题是OOM防御，Pattern #31 正是系统级自恢复闭环
- Pattern #30 进程内存扫描工具(procmem_scanner) 也直接适用于内存监控
- 两个模式均从v87就存在，但在v108-v110的OOM/内存相关任务中未被引用

## 3️⃣ [缺失] Rate Limit 处理与重试策略

**背景**: v108#3 因 RateLimit 永久阻塞，暴露了系统对API限流缺乏应对策略

**建议新增 pattern**: Rate Limit 处理模式
```python
# 核心策略：指数退避 + 队列调度 + 降级回退
def call_with_retry(api_func, max_retries=3, base_delay=1.0):
    for i in range(max_retries):
        try:
            return api_func()
        except RateLimitError as e:
            if i == max_retries - 1: raise
            delay = base_delay * (2 ** i)  # 指数退避
            time.sleep(delay)
    # 备用: fallback to alternative endpoint
```

关键教训: RateLimit ≠ 终结。使用指数退避+备用端点+队列调度三种策略叠加可避免永久阻塞。

## 4️⃣ [缺失] OOM 防御实现模式

**背景**: v110 构建了OOM防御体系但未提取为可复用模式

**建议新增 pattern**: 应包含: 内存阈值监控 → 进程内存扫描(procmem_scanner) → cgroup调速 → 自治恢复 → 健康仪表盘可视化

---

## 统计

| 类别 | 数量 | 说明 |
|:----|:----:|:-----|
| 已存在KA可被使用 | 2 | Pattern #3, #31 在v108/v110中未被利用 |
| 缺失KA应补充 | 2 | RateLimit处理策略, OOM防御实现模式 |
| 已有KA被正确使用 | ~5-8 | Pattern #11(TODO评审), #14(Smart Fallback)等被日常使用 |
| 总计检出 | 4 | ✅ 达标 |

---

*生成: autonomous_reports/R398_KA_retrospective.md*
