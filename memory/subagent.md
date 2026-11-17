# Subagent 调用 SOP

## 两种模式

### --func 纯函数模式
- `python agentmain.py --func prompt.txt [--llm_no N]`（cwd=代码根）
- 读prompt文件→执行→结果写`prompt.out.txt`→退出，主agent读完可删
- 后台启动(print PID)，加`--nobg`前台同步等结果
- 仅用于快速一次性任务，难以中途干预

### --task 持续协作模式
- `python agentmain.py --task {name} [--input "短文本"] [--llm_no N]`（cwd=代码根）
- `--input`自动建目录+清旧output+写input.txt；长文本先手动写input.txt再启动(不带--input)
- **不要--nobg**（会卡在等reply循环），只能后台启动
- 通信：output.txt(`[ROUND END]`=轮完成) → 写reply.txt继续 → 不写10min退出。reply后输出为output1/2/3.txt
- 干预文件：`_stop`(当轮结束) | `_keyinfo`(注入working memory) | `_intervene`(追加指令)
- [[可选fork]]：将变量history(str)写入task目录下`_history.json`继承对话上下文
- [[可选监察者]]：主agent空闲时读output观察进度，必要时干预文件纠偏。加`--verbose`可审查原始数据

## Hub：向已有 agent 投递消息
通过 Hub 向已有 agent 投递消息：查 GA 代码根 `frontends/hub.py`，页面入口及投递接口均在其中。

## 共通规则
- 从代码根启动，agent运行cwd为temp/，共享文件系统
- input：目标+约束即可，subagent同等智能。**禁写步骤/过度描述**，大量数据给路径

## 场景1：测试模式 - 行为验证
**用途**：观察agent真实行为，修正RULES/L2/L3/SOP
**流程**：写prompt→启动subagent→轮询结果→验证→清理
**原则**：不诱导做法；Insight优先级>SOP
**两种测试**：
- 测SOP质量：input指定SOP名，排除导航干扰，验证SOP可执行性
- 测导航能力：input只写目标，验证能自主从insight找到正确SOP

## 场景2：Map模式 - 并行处理
**用途**：N个独立同构子任务分发，独立上下文避免交叉污染
**约束**：键鼠不可共享；用浏览器时，input注明：不共用tab，每agent同时≤3个，读完即关
**流程**：准备独立输入文件→每个启动subagent→收集输出汇总
