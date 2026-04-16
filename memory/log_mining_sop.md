# 日志挖掘 SOP

> 触发：用户要求"日志挖掘" / "挖掘日志" / "分析历史会话" / "从日志中找问题" / "会话摘要分析"

---

## Phase 0：预处理

用 code_run 执行 compress_session.py 处理原始日志：

```python
import subprocess, sys, os

# 定位项目根目录（当前cwd是temp/）
agent_root = os.path.abspath(os.path.join(os.getcwd(), '..'))
script = os.path.join(agent_root, 'memory', 'L4_raw_sessions', 'compress_session.py')
raw_dir = os.path.join(agent_root, 'temp', 'model_responses')


result = subprocess.run([sys.executable, script, raw_dir, "--run"], 
                       capture_output=True, text=True, encoding='utf-8')
print(result.stdout)
if result.returncode != 0:
    print(f"STDERR: {result.stderr}")
```


## Phase A：分批读取并逐条标记

统计文件大小和行数，计算需要分几批读入（每批400KB左右）。每批：用 file_read 读入该批内容，每扫描到一个有张力的片段就标记下来。标记完这批再读下一批。永远不要为了效率切换策略用代码做关键词匹配，始终像读论文一样从头读到尾。

每条标记只写一行：行号范围 + SESSION_ID + 一句话说明。不要展开分析，只做标记。这一步宁可多标不要漏标，筛选是下一步的事。

每批标记完后，用 code_run 将该批标记追加写入 tension_marks.txt，防止早期标记被遗忘。

---

## Phase B：筛选与归类

先 file_read tension_marks.txt 获取所有标记，然后：

1. **筛选**：去掉 Phase A 中 agent 层面无能为力的标记（即使记进记忆下次也无法避免的问题）。一次性的工具语法错误也去掉，除非同一个错误在多个会话反复出现。

2. **归类**：把筛选后的标记按共性分组，每组起一个类型名。同一类型下的实例应该是"同一个问题的不同次出现"。

**粒度校准**（用于理解粒度边界，不限定内容范围）：
- ✗ 太粗："反复失败"（太多不同问题被混在一起）
- ✓ 合适："subagent启动失败"（同一类型下的实例确实是同一个问题）
- ✗ 太细："0322会话中N3节点因main.py路径错误启动失败"（这是一个具体实例不是类型）

---

## Phase C：结构化索引

Phase B 的归类结果和 all_histories.txt 都已在你的上下文中。基于 Phase B 的归类结果，对每个类别记录：出现次数、会话 ID 列表、关键证据片段，生成 tension_index.json。严格按以下结构，不要自创字段或改变嵌套关系：

```json
{
  "类型名": {
    "description": "一句话描述",
    "count": 数量,
    "sessions": [
      {
        "id": "SESSION时间戳",
        "evidence": "[Agent]/[USER]开头的摘要原文行",
        "outcome": "贴合类型语境的简短结果标签"
      }
    ]
  }
}
```

- evidence：直接复制摘要中该问题的原文行，用于回溯原始日志
- outcome：看该SESSION结束时这个问题的状态来判断（不只看紧邻的几行，看整个SESSION的结尾）。如"已解决""切换策略""持续失败""已采纳""未验证""转向成功"等。尽量不写"未知"——如果SESSION结尾agent报告了完成或用户确认了，那就是"已解决"；如果agent放弃了换方案，那就是"切换策略"

用 code_run 写入 JSON 文件。
