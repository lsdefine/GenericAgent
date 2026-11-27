# Project Memory: llm_audit_ctf

## 任务背景
- 厂商主办的官方赛事，主题：LLM/大模型服务暴露面审计（找适合做 2API 的网站/服务 → 判断可被二次封装利用的程度 → 出审计报告提交给网站/主办方）
- 赛制：奖金与产出成果量挂钩，产出越多奖金越高；单人参赛
- 状态：已获合法授权；题目原文未脱敏（含个人身份证信息），暂不提供，等脱敏后给

## 已有资产
- `work/fingerprints/ai_fingerprints.json`：指纹库 v0.2，保留17条带内容特征的低影响 GET 探针；不含认证/会话路径或纯状态规则。
- `work/scanner/probe.py`：aiohttp 异步候选发现器；严格 AND 匹配、代理实传、保留端口/IPv6、默认 TLS 校验且不跟随跳转、共享 Session、固定 worker 池、追加 JSONL 与 `--resume`。
- `README.md`：运行约定与安全边界。
- `work/candidate_review.md`：候选人工复核表。
- `work/audit_report.md`：审计报告模板。
- `work/data/`：raw（脱敏目标）/ candidates（扫描结果）/ findings（深度验证）三级目录。

## 约束与纪律
- 项目文件一律放 `./projects/llm_audit_ctf/`，禁止丢 temp 根目录
- 密钥/身份证等敏感信息仅引用不读取；报告脱敏
- 只做被动验证与最小 PoC，不真实套利、不批量薅资源（防法律风险+保报告可信度）
- 入库判据：记忆归零后接手缺了会重复付出认知代价才记

## 本机验收结论（2026-08-11）
- 已通过 Python 编译、`--help`、裸主机/端口/显式 URL/IPv6 输入规范化测试；含 URL 凭据和非 HTTP(S) 方案会被拒绝。
- 随机 `127.0.0.1` 回环 E2E：带 `status:200` 与 `json_contains:data` 的 `/v1/models` 规则命中；普通 HTTP 200 页面不命中；`--resume` 不重访已记录目标。
- 默认指纹和输出路径已锚定到脚本所在 `work/`，可从项目根直接运行。最终回环普通页只产生 `no_match_or_unreachable`，规则库静态检查无敏感路径或纯状态规则。
- 未启动项目服务、未外部批量扫描、未验证或修改本机代理链，未读取任何凭据。

## 待办
- [ ] 拿到脱敏后的题目原文 → 拆解评分点（产出计量方式、官方报告字段、提交渠道、时间线）。
- [ ] 按赛事实际规则补充指纹、候选排序和报告字段；每条新增规则先做本机反例/正例测试。
- [ ] 仅在明确授权范围内导入脱敏目标并进行小批次候选发现，再按 `candidate_review.md` 人工复核。
- [ ] 形成发现、修复建议、复测与提交的闭环；将官方字段映射到 `audit_report.md`。

## 本机代理监听快照（2026-08-11 21:46 +08:00）
- 只读核对结果已写入 `work/NETWORK_HANDOVER.md`（无业务内容、无凭据）；`7897` 由 PID 19600 `BaoKeMengCore.exe` 监听（`::`），`18910` 由 PID 25412 `xray.exe` 监听（仅 `127.0.0.1`）；`10810/10811/10822/10823` 未监听。
- 本次未读取代理配置或凭据，未验证代理认证/链式转发/出口 IP；后续若要启动业务代理链必须获得明确指令，且 `10810/10811` 与 `18910` 只读、禁止批量终止 xray。

## 版本化迁移（2026-08-11）
- 可追踪主副本为仓库根的 `projects/llm_audit_ctf/`；原 `temp/projects/llm_audit_ctf/` 保留作项目模式下的本地工作与回退副本。
- 项目级 `.gitignore` 忽略 `work/data/{raw,candidates,findings}/` 和 `work/reports_out/` 的运行数据，仅追踪各目录 `.gitkeep`、源码、规则与模板。
- 版本化副本通过本机 `127.0.0.1` 正负回环验收：`/api/models` 的 `{"data":[...]}` 命中 Open WebUI，普通 HTTP 200 页面写入 `no_match_or_unreachable`。
