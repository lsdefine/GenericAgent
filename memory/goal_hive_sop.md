# Goal Hive Mode SOP

## 定义

Goal Hive = Goal Mode 的多 worker 协作协议
Hive模式单独运行，不要和plan/supervisor/subagent混杂

## 启动

1. 选一个空闲端口 `PORT` 和本次协作 key `BOARD_KEY`。
2. 创建本次 Hive 数据目录：`BBS_CWD=<CodeRoot>/temp/hive_<目标短名>`。
3. 启动 BBS：`start /b python <CodeRoot>/assets/agent_bbs.py --cwd <BBS_CWD> --port <PORT> --key <BOARD_KEY>`。
4. 按http://127.0.0.1:<PORT>/readme?key=<BOARD_KEY>，在bbs发第一个帖子，包括1.任务目标；2.以下的Hive Master职责；3.优先使用`<BBS_CWD>`进行文件传输而非bbs的文件功能；4.附加说明：`此为最终目标，worker不要接单，先等hive master拆分子任务。`
5. 后台启动首个worker
6. 询问用户时间预算，按`goal_mode_sop.md`后台启动hive master
7. Hive master，workers都是与你不同的独立进程，你启动它们后应当报告用户并停止

## Goal Master

`objective` 必须逐字包含三块，缺一不可：用户目标、`http://127.0.0.1:<PORT>/readme?key=<BOARD_KEY>`、下方“Hive Master 职责”全文；启动 master 前必须回读 `goal_state.json`，确认 objective 包含完整`Hive Master 职责`（一字不改），否则不得启动。

`done_prompt`：goal_state.json 中必须设置此字段为：`关闭所有你拉起的worker，并在BBS发一条帖子，宣告你管理的任务结束，worker除了明确追加任务外，不应再回应。`（一字不改）

Hive Master 职责：
1. 你**负责任务调度和团队组织**，不允许亲自干活导致 worker 空转，耗时执行与复杂复核应拆给 worker
2. 终极目标是要做到**完美的找不到任何问题的**任务交付结果，保证用户满意，围绕核心产出（不太需要额外产出）
3. 针对任务目标设计要做的子任务，发到bbs上，worker会接任务并完成
4. 如果子任务很多，worker做不过来，可以参照Goal Hive Mode SOP拉起更多worker
5. 只要时间没到，就持续验收结果、检查问题、寻找下一个改进点，并继续设计新子任务
6. 时间没到不允许交付，必须头脑风暴找改进点和检查点，也可发动worker一起寻找改进点

## 拉起 worker

启动 worker：`start /b python <CodeRoot>/agentmain.py --reflect <CodeRoot>/reflect/agent_team_worker.py --base_url http://127.0.0.1:<PORT> --board_key <BOARD_KEY> --name hive-worker-1`。

后续 worker 由 Goal Master 按需要增加（不能超过10个，一般任务2-4个足够）。
