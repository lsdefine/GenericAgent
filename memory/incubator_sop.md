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

## 依赖
requests beautifulsoup4

## 通信
同subagent协议：`agentmain.py --task {name} --input "..."`
或起reflect worker并设置bbs信息

## 干预记忆
直接编辑远端 memory/ 下的文件（SOP/全局记忆）
