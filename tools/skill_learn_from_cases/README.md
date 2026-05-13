# skill_learn_from_cases — 案例驱动技能学习 CLI 工具

通过真实案例学习一项技能，并用案例验证能力习得。  
零外部依赖（除搜索引擎 API key），开箱即用。

---

## 工具做什么

给定一个技能名称（如 `docker_compose_production`），自动执行 5 阶段闭环：

```
定义技能 → 搜索案例 → 分析提炼 → 构建工具 → 验证能力
     ↑_____________________________________↓
                  迭代反馈环
```

每次学习都在 `skills_learning/{技能名}/revN/` 下创建迭代子目录，  
保留完整成长轨迹（rev1 → rev2 → rev3 ...）。

---

## 工作机制

### 5 阶段流程

| Phase | 动作 | 产出 |
|-------|------|------|
| **0** 🚀 启动 | 创建 `skills_learning/{技能}/revN/` 目录 | 目录结构就绪 |
| **1** 🎯 定义 | 调 **Skill Hub**（105K+ skill卡）查前置知识 | 技能定义 JSON |
| **2** 🔍 搜索 | 双渠道：**Skill Hub** + **Web 搜索** | 25+ 条真实案例 |
| **3** 🧠 分析 | 领域感知模式提取（12个技能领域） | 知识模式列表 |
| **4** 🔧 构建 | 生成 `assess.py` + 技能专属实操测试 | 验证工具 |
| **5** ✅ 验证 | 运行验证 → 评分报告 | PASS/FAIL + 分数 |

### 技能领域识别

工具内置 **11 个技能领域**，根据技能名称自动匹配：

- async / performance / docker / kubernetes
- database / react / git / testing
- web_scraping / networking / fastapi

每个领域有 6~12 条预设知识模式，匹配到的领域模式会自动注入学习流程。

### 实操测试（Practical Hooks）

如果技能匹配以下关键词，会自动添加实操测试：

| 技能关键词 | 实操测试 |
|-----------|---------|
| docker / compose / container | `docker compose config` 校验 |
| git | 临时 git 仓库操作（init/branch/commit/log） |
| sql / database / mysql / postgres | SQLite JOIN/子查询/聚合验证 |
| async / asyncio | 真实 asyncio 代码执行（gather/timeout/Queue） |

实操测试分数占综合评分的 **30%**。

### 答案随机化

知识测试的每道选择题正确答案随机分布在 A/B/C/D 位置，杜绝全选 B 的作弊行为。

---

## 使用方法

### 基本用法

```bash
# 学习一个技能
python -m tools.skill_learn_from_cases "docker_compose_production"

# 查看已学技能列表
python -m tools.skill_learn_from_cases --list

# 预览模式（不实际执行）
python -m tools.skill_learn_from_cases "kubernetes_deployment" --dry-run
```

### 迭代学习

重复学习同一技能会自动创建新版本：

```bash
python -m tools.skill_learn_from_cases "sql"
# → skills_learning/sql/rev1/  新技能

python -m tools.skill_learn_from_cases "sql"
# → skills_learning/sql/rev2/  继承 rev1 模式，补充新案例
```

### 已学技能列表

| 技能 | 版本 | 评分 | 实操 |
|------|------|------|------|
| docker_compose_production | rev13 | 100 | ✅ docker compose config |
| python_async_optimization | rev2 | 100 | ✅ asyncio 代码执行 |
| sql | rev1 | 100 | ✅ SQLite 查询 |
| git_advanced | rev1 | 100 | ✅ Git 仓库操作 |

---

## 搜索引擎配置

工具依赖两个搜索引擎：

### 1. Skill Hub（技能卡检索）

105K+ skill 卡的语义搜索引擎。  
内置默认 API 地址，**无需配置**即可使用。

如需自定义：
```bash
export SKILL_SEARCH_API="http://your-api:port"
```

详细说明见：`memory/skill_search/SKILL.md`

### 2. Web 搜索引擎（案例搜索，需用户配置）

用于搜索真实世界案例文章。  
**工具本身不内置任何搜索引擎**，需用户自行配置。不配置时跳过 Web 搜索，仅从 Skill Hub 获取案例。

```bash
# 配置搜索引擎（Python 模块路径）
export SEARCH_ENGINE_MODULE="your_module.search"   # 必填
export SEARCH_ENGINE_FUNC="search"                  # 搜索函数名（默认 search）
```

**搜索引擎模块接口约定**：  
搜索函数必须接受 `(keyword: str, size: int) -> list[dict]` 参数，返回格式：

```python
[
    {"title": "文章标题", "url": "https://...", "snippet": "摘要内容..."},
    ...
]
```

---

## 目录结构

```
GA根目录/
├── tools/skill_learn_from_cases/       ← CLI 工具
│   ├── __main__.py                     ← python -m 入口
│   ├── engine.py                       ← 5阶段引擎
│   ├── dir_manager.py                  ← 版本目录管理
│   ├── assess_template.py              ← 验证工具模板
│   └── practical_hooks/                ← 实操测试挂钩
│       ├── docker_compose.py
│       ├── sql.py
│       ├── git.py
│       └── python_async.py
├── skills_learning/                     ← 技能仓库
│   ├── docker_compose_production/
│   ├── python_async_optimization/
│   ├── sql/
│   └── git_advanced/
└── memory/
    └── skill_learning_sop.md           ← 长期记忆（供 AI 自动调用）
```

---

## 迭代计数规则

版本号自动递增：

```
skills_learning/{skill_name}/
├── rev1/         第一次学习
├── rev2/         第二次学习（继承 rev1 模式）
├── rev3/         第三次学习（继承 rev1+rev2 模式）
└── ...
```

每次版本都独立保存案例、模式、工具和报告，**历史版本不丢失**。

---

## 注意事项

- **WSL 用户**：如果本机是 Windows，且安装了 WSL，工具会自动通过 `wsl.exe` 调用 Docker 命令
- **新技能首次评分**：纯知识测试 + 模式覆盖，通常 70/100 起步。迭代后实操测试接入即可冲 100
- **领域扩展**：如需新增技能领域，编辑 `engine.py` 的 `skill_domain_patterns` 字典
