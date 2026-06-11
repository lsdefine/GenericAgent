# Project Mode SOP

## 定义

Project Mode = 跨会话保持项目认知的工作模式
载体：`project_memory.md` + 项目私域目录。两层注入：每轮自动注入的只有 L1（规则+记忆文件指针），L2（`project_memory.md` 全文）不注入——任务涉及项目上下文时自己用 file 工具去读，无关则不读

## 进入

锚 = `./.active_project.<宿主pid>`，只对当前 GA 进程有效：GA 关闭即自动失活；多开 GA 各自激活不同项目，互不干扰。（下文路径一律以 cwd 为基准，cwd 即 GA 的 temp 目录；禁写 `temp/xxx` 前缀，会嵌套出 temp/temp）

- 用户只说「进入项目模式」未指明项目：列出 `./projects/` 下各项目（名字 + memory 行数 + 最后修改时间），ask_user 让用户选定后再继续
- 用户明确说「进入/切换到 <项目名> 项目」：视为已确认，直接执行：

1. 建目录 `./projects/<项目名>/`，无则创建 `project_memory.md`（空文件即可）
2. 写文件锚，必须用 code_run（锚文件名含宿主 pid，ppid 即 GA 宿主进程）：
   `import os; open(f'./.active_project.{os.getppid()}', 'w').write('<项目名>')`
3. 回读 `project_memory.md` 全文，向用户复述项目现状

## 期间纪律

- 项目文件（todo、草稿、产物）一律放 `./projects/<项目名>/`，禁止丢 temp 根目录
- 入库判据（唯一标准）：每得到一条信息，自问「记忆归零、重新接手本项目的我，缺了这条会不会重复付出认知代价——再踩一次坑、再摸索一次、再问一次用户？」会则立即追加进 `project_memory.md`，不会则不记
- 一条一句，写成未来的自己能直接复用的形式；已有条目增量更新，不整篇重写

## 离开

用户表示「离开项目模式」时：删除 `./.active_project.<宿主pid>`（仅关闭激活态，项目目录与 `project_memory.md` 原样保留）
切换到另一项目时无需先离开，直接按「进入」覆盖文件锚即可
GA 关闭不需任何操作：锚随进程消亡自动失效，残留文件由插件下次启动时清扫
