# Checklist SOP

## Booter（启动者/用户）

**Checklist 模式**（单人，master自己执行）：
```python
from checklist_helper import CL
cl = CL("cl_xxx", goal="<用户要求任务，尽量原样>")
cl.start_master()   # Only for Booter，Master严禁调用
```

**MapReduce 模式**（多人，master派发+worker执行）：
```python
from checklist_helper import CL
cl = CL("cl_xxx", goal="<用户要求任务，尽量原样>", workers=2)
cl.start_master()   # Only for Booter，Master严禁调用
```

goal 写法：只写「做什么 + 参考哪个SOP」，不写怎么做。Master 自己读 SOP 决定 plan。

## Master（reflect agent 使用）

```python
from checklist_helper import CL
cl = CL("cl_xxx")              # 加载状态（BBS已在跑）
cl.add(["任务1", "任务2"])    # 在你的笔记中记录TODO项
cl.look()                     # 查进度
cl.mark(id, "摘要")           # 验收
cl.close()                    # 全部完成后关闭
```

## Master plan示例

目标可分解为多个**不相干、可并行**的子任务 → add 子任务。
B 要等 A 的结果 → 不要硬拆，串行做。

任务使用短句，派发时再补充信息。

1. 下载网盘 /game 下所有文件
   → 先 webscan 拿文件列表，再每个文件一条任务
   `cl.add(["下载A.exe", "下载B.zip", "下载C.zip"])`

2. 从语法、风格、格式角度检查 a.pdf
   → 三个维度天然独立
   `cl.add(["检查语法", "检查风格", "检查格式"])`

3. 查所有 VPS 中版本 < 22 的，升级到 24
   → 第一轮：每台一条查版本任务
   `cl.add(["查 node03 版本", "查 node09 版本", "查 Dell 版本"])`
   → reduce：master 筛出 < 22 的
   → 第二轮：每台需升级的一条任务
   `cl.add(["升级 node03 到 24", "升级 Dell 到 24"])`

## Master 循环

```
cl.look()
├─ 有未完成任务 → 去 BBS 派发（mapreduce模式）/ 自己干（无worker checklist模式）
└─ 全部完成
    ├─ 用户最终目标已达成 → close()
    └─ 最终目标未达成 → plan 下一步
        ├─ 可解耦 → add() 新一批任务
        ├─ 需串行前置 → 自己做一步，再回 look
        └─ 基本搞定 → 自己整合结果，交付最终报告
```

master会被持续唤醒直到其显式成功调用close()。

## 派发任务（有workers模式下）

worker无法看到add的任务，只能看到BBS！
每条任务 prompt 须**自包含**——worker 没有 master 的上下文。
每次最多只派发3个任务，不要一次性把所有任务贴到bbs上。
worker足够聪明，只允许写目标和需要的信息，不要干预
**master不允许执行已经派发出去的任务，会导致重复执行！** 没事就sleep！

写 prompt 要点：
1. **背景**：worker 需要的信息直接给（路径、数据、约定），不要假设 worker 知道
2. **交付物**：明确产出什么、格式、写到哪里
3. **不限手段**：说要什么结果，别规定怎么做
4. **不干预 BBS 行为**：禁止教 worker 如何抢单/回帖/报告，那是 worker 自己的机制

交付规范（写进任务 prompt）：
- 交付结果和报告信息必须分开。交付 = 纯成品；报告 = 过程/问题/备注
- 交付文件禁止出现说明性废话
- 长结果写文件，短结果直接回帖

## 验收

Master 收到 worker 回帖或自己完成子任务后：
- 检查结果，语义判断 pass/fail → `cl.mark(id, "结果摘要")`
- 交付物含过程废话 → 要求重写交付物
- 失败 → 可重发、换 prompt、或自己补

## 注意

- 若子任务需要 web 工具，提醒并行 worker 新建 tab 并使用自己的 tab
