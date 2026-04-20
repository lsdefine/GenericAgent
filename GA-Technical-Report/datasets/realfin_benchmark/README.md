# Finance Dataset

这是金融任务数据集，包含 40 个金融量化分析任务，用于评测 AI Agent 在金融领域的数据处理和分析能力。

## 数据格式

数据以 JSONL (JSON Lines) 格式存储在 `tasks.jsonl` 文件中，每行一个 JSON 对象代表一个任务。

## 字段说明

### 基础信息

- **id** (string): 任务唯一标识符，格式为 `task_XX_description`
- **name** (string): 任务中文名称
- **category** (string): 任务类别，详见下方分类说明
- **timeout_seconds** (integer): 任务执行超时时间（秒）

### 评分配置

- **grading_type** (string): 评分类型
  - `automated`: 纯自动化评分
  - `hybrid`: 混合评分（自动化 + LLM 评审）

- **grading_weights** (object): 评分权重配置（仅 hybrid 类型）
  - `automated` (float): 自动化评分权重，范围 0.0-1.0
  - `llm_judge` (float): LLM 评审权重，范围 0.0-1.0
  - 两者之和应为 1.0

### 任务内容

- **prompt** (string): 给 Agent 的任务描述，包含：
  - 时间基准说明
  - 具体任务要求
  - 输出格式要求

- **expected_behavior** (string): 期望的 Agent 行为步骤，描述完成任务的标准流程

- **workspace_files** (array): 任务所需的预置文件列表（当前所有任务均为空数组）

### 评分标准

- **grading_criteria** (array of strings): 评分检查点列表，每个元素是一个评分维度的描述

- **automated_checks** (string): 自动化评分的 Python 代码
  - 函数签名: `def grade(transcript: list, workspace_path: str) -> dict`
  - 输入:
    - `transcript`: Agent 执行过程的对话记录
    - `workspace_path`: Agent 工作目录路径
  - 输出: 字典，键为评分项名称，值为分数（0.0-1.0）

- **llm_judge_criteria** (array of objects): LLM 评审标准（仅 hybrid 类型）
  - `name` (string): 评审维度名称
  - `weight` (float): 该维度权重，范围 0.0-1.0

## 任务分类

数据集包含以下类别的任务：

### 技术指标类
- `technical_filter`: 技术指标筛选
- `complex_signal`: 复杂信号组合
- `trend_strength`: 趋势强度分析
- `multi_timeframe_resonance`: 多周期共振

### 形态识别类
- `pattern_detection`: 形态检测
- `breakout_pattern`: 突破形态
- `candlestick_pattern`: K线形态
- `bullish_pattern`: 看涨形态

### 量价分析类
- `volume_trend`: 成交量趋势
- `volume_breakout`: 量能突破
- `complex_volume_price_pattern`: 复杂量价形态
- `divergence_detection`: 背离检测

### 波动率类
- `volatility_breakout`: 波动率突破
- `volatility_compression_expansion`: 波动率压缩扩张

### 统计分析类
- `statistical_analysis`: 统计分析
- `statistical_count`: 统计计数
- `ranking`: 排名分析
- `duration_analysis`: 持续时间分析

### 多因子类
- `multi_factor_momentum_reversal`: 多因子动量反转
- `composite_scoring_model`: 综合评分模型
- `fundamental_technical_combined`: 基本面技术面结合

### 跨市场/板块类
- `sector_rotation_multi_hop`: 板块轮动（多跳）
- `sector_leadership`: 板块领涨
- `multi_hop_sector_technical`: 多跳板块技术分析
- `multi_hop_correlation_signal`: 多跳相关性信号
- `etf_constituent_arbitrage`: ETF成分股套利

### 资金流向类
- `fund_flow_technical_multi_hop`: 资金流技术分析（多跳）

### 组合管理类
- `portfolio_performance_analysis`: 组合绩效分析
- `risk_adjusted_return`: 风险调整收益

### 事件驱动类
- `event_driven_breakout_followthrough`: 事件驱动突破跟进

### 日内交易类
- `intraday_anomaly`: 日内异常

### 极端情况类
- `extreme_reversal`: 极端反转

### 宏观策略类
- `macro_interest_rate_strategy`: 宏观利率策略
- `commodity_equity_linkage`: 商品股票联动

### 特征工程类
- `feature_engineering`: 特征工程

### 综合类
- `ultimate_multi_condition_multi_hop`: 终极多条件多跳
- `moving_average_pattern`: 均线形态
- `ma_convergence_divergence`: 均线收敛发散
- `cross_timeframe_pattern`: 跨周期形态

## 统计信息

- **任务总数**: 40
- **评分类型分布**:
  - Hybrid (混合评分): 32 个任务
  - Automated (纯自动化): 8 个任务
- **类别数量**: 40 个不同类别（每个任务一个独特类别）

## 使用示例

### 读取数据集

```python
import json

tasks = []
with open('tasks.jsonl', 'r', encoding='utf-8') as f:
    for line in f:
        task = json.loads(line)
        tasks.append(task)

print(f"加载了 {len(tasks)} 个任务")
```

### 按类别筛选

```python
# 筛选所有技术指标类任务
technical_tasks = [t for t in tasks if 'technical' in t['category']]
```

### 执行自动化评分

```python
def run_automated_grading(task, transcript, workspace_path):
    """执行任务的自动化评分"""
    if task['automated_checks']:
        # 执行评分代码
        exec_globals = {'transcript': transcript, 'workspace_path': workspace_path}
        exec(task['automated_checks'], exec_globals)
        grade_func = exec_globals['grade']
        scores = grade_func(transcript, workspace_path)
        return scores
    return {}
```

## 时间基准说明

所有任务使用统一的时间基准：
- **分析截止日**: 2026-03-31
- **回看窗口**: 根据题目要求（5/10/15/20/30/60/252个交易日等）从截止日向前回看
- **停牌处理**: 停牌样本按可得交易日顺延补足

## 数据来源

任务由原始 Markdown 文件转换而来，使用 `convert_to_jsonl.py` 脚本进行转换。

## 版本信息

- **版本**: v1
- **创建日期**: 2026-04
- **任务数量**: 40
