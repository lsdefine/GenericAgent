# Incubator SOP — 远程部署GA实例
自我复制到任意节点的agent网络。每个节点有独立记忆，可以通过编辑memory干预它们的行为

## 文件清单
```
GARoot/*.py
GARoot/assets/*.txt *.json
mykey.py
GARoot/memory/      
```
memory下大部分文件不适合分发，不要复制 memory 下未被 gitignore 白名单的文件！
不要复制 memory 下的L1/L2文件(global_mem(_insight).txt)，会自动初始化

打包红线：严格按上面4行清单执行，`*` 是 glob 全匹配，不得擅自改成“必要文件/可启动闭包”。
- `GARoot/*.py` 必须包含根目录所有 `.py`。
- `GARoot/assets/*.txt *.json` 必须包含 assets 顶层所有 `.txt`/`.json`。
- `GARoot/memory/` 只取 `.gitignore` 白名单/已允许分发文件；排除 `global_mem.txt`、`global_mem_insight.txt`、`__pycache__/`、`*.pyc`。
- 按当前清单实测压缩包约153KB/55文件；正常不应超过170KB，文件数不应超过60。

## 依赖
requests beautifulsoup4
尽量复用远端已有python/venv

## 通信
看subagent.md
同subagent协议：`agentmain.py --task {name} --input "..."`
或起reflect worker并设置bbs信息

## 干预记忆
直接编辑远端 memory/ 下的文件（SOP/全局记忆）
