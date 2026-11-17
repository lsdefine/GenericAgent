# 旁路模型日志插件

默认关闭，不使用环境变量，不修改主循环或 llmcore。

## 启用 / 关闭

在 **GA 所在进程**内设置（前端可直接绑定）：

```python
from plugins import shadow_model

shadow_model.MODEL = '已有模型配置名'  # 启用，名称与 llmcore 配置一致
shadow_model.MODEL = ''               # 关闭新采集；已排队请求继续
```

只把上述赋值写在另一个 Python 进程里，不会改变正在运行的 GA。
`MODEL` 是进程级配置，对该进程中的所有 agent 生效。修改从下一步开始。

可选变量：`OUTPUT_DIR`（输出目录）、`TIMEOUT`（副请求总超时，默认 600 秒）、
`QUEUE_LIMIT`（等待队列容量，默认 32；首次启用前设置）。

## 实现

- `llm_before`：将当前 history、本轮 messages、system_prompt、tools 保存为 JSON 快照。
- 后台线程启动独立 Python 子进程，调用 `resolve_client(MODEL)` 和 `client.chat(...)`。
- 每步使用新副 client，历史来自 JSON 解码；不复制 pending IDs，不保留副模型上一步回答。
- `llm_after`：保存主模型输出。只有主模型的动作进入原工具执行循环。
- 副模型按自己的配置裁剪、压缩与适配协议；不要求主副输入完全相同。
- 独立进程隔离 llmcore 全局统计和调试输出，不改主模型日志及历史。

## 日志

默认位置：`temp/shadow_model/<run-id>/<turn>/`

| 文件 | 内容 |
|---|---|
| `input.json` | 本步状态快照、双方配置名、时间 |
| `main.json` | 主模型输出：thinking、content、tool_calls、raw、模型名 |
| `shadow.json` | 副模型输出或 `error` / `skipped` 状态 |
| `llm.log` | 副模型原有 llmcore 日志 |
| `worker.log` | 副进程调试输出及错误堆栈 |

快照只保存请求数据，不保存 API 配置或密钥；但任务上下文本身可能含敏感数据，
请按原始会话日志管理，不要直接公开或提交到 Git。

## 运行边界

- 默认关闭不写文件、不启动 worker、不发请求。
- 启用后主线程只承担快照序列化和本地写盘，不等待副模型网络请求。
- 单 worker 串行处理副请求，可能落后于主任务；队列满时标记 `skipped`，快照仍保留。
- 主请求若异常终止、没有触发 `llm_after`，该步可能只有输入/副输出，没有 `main.json`。
- GA 退出不等待队列排空；排队项可能未执行，正在运行的子进程可能继续直至结束或超时。
- 关闭 MODEL 不取消已提交请求；本插件不额外接管 GA 的取消接口。
- 子进程按配置名称独立加载配置；只在主进程内临时创建、未持久化的模型配置不可用。

需要补跑某个快照时，在仓库根目录显式运行（会调用模型并覆盖该步副输出）：

```bash
python -m plugins.shadow_model --worker temp/shadow_model/<run-id>/<turn>
```

## 离线验证

```bash
python -m unittest discover -s tests -p 'test_shadow_model.py' -v
```

测试使用真实 native client 的拼装和解析，模拟网络传输；不读取真实密钥，不调用 API。
