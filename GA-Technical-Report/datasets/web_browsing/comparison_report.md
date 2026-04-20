# GenericAgent vs Openclaw 对比实验报告

## 一、实验概述

本报告对比 **GenericAgent (GA)** 和 **Openclaw (OC)** 在两个网页浏览基准测试上的表现：

| 数据集 | 任务数 | 任务类型 | 评估方式 |
|--------|--------|----------|----------|
| BrowseComp-ZH | 10 | 中文多跳推理信息检索 | LLM Judge (二元判定) |
| WebCanvas | 12 | 英文网页导航与交互 | 自动 (URL checkpoint) |

两套 Agent 使用相同的底层 LLM（`claude-opus-4-6`），在完全相同的 22 道题目上进行测试。Openclaw 多次运行的任务取最佳得分。

---

## 二、成功率对比

| 指标 | GenericAgent | Openclaw | 差异 |
|------|:---:|:---:|:---:|
| **BrowseComp-ZH 准确率** | **60.0%** (6/10) | 20.0% (2/10) | GA +40pp |
| **WebCanvas 平均分** | **83.4%** | 72.2% | GA +11.2pp |
| **WebCanvas 满分率** | **6/12** (50%) | 5/12 (41.7%) | GA +1 |

![成功率对比](fig1_success_rate.png)

### 逐任务胜负

| 数据集 | GA 胜 | 平局 | OC 胜 |
|--------|:---:|:---:|:---:|
| BrowseComp-ZH | **5** | 4 | 1 |
| WebCanvas | **3** | 8 | 1 |
| **合计 (22题)** | **8** | **12** | **2** |

![胜负统计](fig3_win_lose.png)

---

## 三、效率对比

### 3.1 轮次 / 耗时 / Token

| 指标 | GA (BC-ZH) | OC (BC-ZH) | GA (WC) | OC (WC) |
|------|:---:|:---:|:---:|:---:|
| 平均轮次 | 21.7 | 26.1 | 18.0 | 19.7 |
| 平均耗时 | 251.7s | 217.2s | 178.2s | 163.0s |
| 平均 Token | 471K | **1,313K** | 185K | **707K** |

![效率对比](fig2_efficiency.png)

### 3.2 Token 成本倍率

两个数据集合计，**Openclaw 的 Token 消耗是 GA 的 3.1 倍**。

| 数据集 | OC / GA Token 倍率 |
|--------|:---:|
| BrowseComp-ZH | 2.8x |
| WebCanvas | 3.8x |
| **合计** | **3.1x** |

这主要因为架构差异：GA 用 `web_scan` 传输简化 HTML，Openclaw 用 `browser snapshot` 传输完整 accessibility tree。

![Token 倍率](fig4_token_ratio.png)

---

## 四、综合仪表盘

![综合对比](fig5_dashboard.png)

---

## 五、结论

1. **GA 在准确率上显著优于 Openclaw**：BrowseComp-ZH +40pp，WebCanvas +11.2pp，逐任务 8 胜 2 负。

2. **GA 的 Token 效率远高于 Openclaw**：总 Token 消耗仅为 Openclaw 的 1/3.1，API 成本更低。

3. **两者轮次和耗时差异不大**：轮次 GA 略少，耗时互有胜负。

4. **Openclaw 在多跳推理任务上表现较弱**：BrowseComp-ZH 仅答对 2/10，GA 的 `repeat_question` 和 `update_working_checkpoint` 机制在长推理链中可能起了关键作用。
