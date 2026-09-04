# llm_audit_ctf

轻量化的 LLM 服务暴露面候选发现与人工审计项目。扫描器只做低影响 `GET` 指纹探测，不登录、不提交利用请求、不读取认证会话端点。

## 当前结构

- `work/scanner/probe.py`：异步候选发现器，固定 worker 池、共享 HTTP 会话、并发上限、追加式 JSONL、`--resume` 续跑。
- `work/fingerprints/ai_fingerprints.json`：可扩展指纹库。每条 probe 的全部 `expect` 必须满足；纯状态码和认证/会话路径不作为候选证据。
- `work/data/raw/`：脱敏后的输入目标；禁止放身份证、Cookie、API Key、代理凭据。
- `work/data/candidates/`：扫描输出 JSONL；结果仅保存有限、脱敏证据。
- `work/candidate_review.md`、`work/audit_report.md`：人工复核与对外审计报告模板。

本机网络监听快照属于临时运行交接信息，不纳入版本库；本项目不启动固定监听端口。

## 最小运行

```text
python work/scanner/probe.py -i work/data/raw/hosts.txt -o work/data/candidates/result.jsonl --resume
```

常用参数：

- `-c/--concurrency`：并发数，程序限制为 1..100；建议从 4 或 8 开始。
- `-t/--timeout`：单请求超时，必须大于 0。
- `-f/--fingerprint`：指纹库路径。
- `-p/--proxies`：可选的完整 `http(s)` 代理 URL 列表；按目标稳定选择代理，代理地址只进入请求层，不写入结果。
- `--probe-only /v1/models,/api/models`：仅使用指定路径；空白项会忽略，路径必须以 `/` 开头。
- `--resume`：跳过输出 JSONL 已记录的目标。
- 输出 JSONL 每条记录包含 `run` 元数据（扫描器/指纹库版本、超时、代理数量及关键开关），便于复核和复现；不包含代理地址。
- `--insecure`：仅本地测试使用；生产审计默认校验证书。
- `--follow-redirects`：仅明确需要时开启；默认不跟随跳转。

## 工作流

1. 对目标来源、授权边界和时间窗口做记录；输入先脱敏。
2. 以低并发、短超时运行候选发现；保留原始 JSONL，不覆盖历史结果。
3. 用 `candidate_review.md` 逐项人工复核：资产归属、未授权可见性、最小证据和影响。
4. 只在明确授权且必要时做最小深度验证；禁止猜测口令、提取密钥、调用模型生成内容。
5. 用 `audit_report.md` 形成可提交报告，并保留修复建议、复测条件和时间线。

## 结果解释

`candidate` 只是指纹候选，不等于漏洞或可用 2API。`no_match_or_unreachable` 也不等于安全：可能受限于 TLS、网络、WAF、代理或探针覆盖范围。所有结论必须以人工复核证据为准。

## 安全边界

不启动项目服务、不复用常见代理监听端口、不读取密钥文件、不把真实凭据写入仓库。代理、目标和报告中的敏感字段应使用占位符或哈希/截断值。
