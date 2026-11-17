# 旁路模型

在 GA 所在进程设置普通变量；默认关闭，无环境变量：

```python
from plugins import shadow_model
shadow_model.MODEL = '已有模型配置名'  # 下一步起启用
shadow_model.MODEL = ''               # 不再启动新请求
```

一个 `llm_before` hook：复制当前历史，创建副 client，后台调用现成的
`client.chat`。每步独立，不执行工具，不回写主历史，副模型自行裁剪上下文。
主输出沿用原日志；主日志中的 `Shadow` 标记给出本步副日志路径，位于
`temp/shadow_model/*.log`。日志拼装与输出均复用 llmcore。

无队列、子进程、重试框架或专用日志格式。默认关闭不启动请求、不写文件。
启用时每步起一个 daemon 线程，不等待旁路完成；关闭不会取消已有请求。
退出可能中断未完成请求，慢请求可能重叠；llmcore 的全局统计与调试输出仍共享。
网络重试沿用 llmcore，后台未捕获异常使用 Python 默认线程异常输出。
日志可能含敏感任务内容，按原会话日志管理。

离线测试：`python -m unittest discover -s tests -p 'test_shadow_model.py' -v`
