# skill_learn_from_cases — 案例驱动技能学习 CLI 工具

通过真实案例学习一项技能，并用案例验证能力习得。  
零外部依赖（除搜索引擎 API key），**可选大模型增强**（DeepSeek/Ollama/OpenAI兼容）。

---

## 快速开始

```bash
# 最简用法（纯规则模式）
python -m tools.skill_learn_from_cases docker_compose_production

# 查看可用环境和预览
python -m tools.skill_learn_from_cases wiki_search --dry-run

# 启用 LLM 增强
set SKILL_LLM_ENABLE=1
set LLM_API_BASE=https://api.deepseek.com/v1
set LLM_API_KEY=sk-xxx
set LLM_MODEL=deepseek-chat
python -m tools.skill_learn_from_cases cypher_programming_language

# 支持中文技能名
python -m tools.skill_learn_from_cases "小微贷款图像凭证鉴定"
```

---

## 工作流程

### 6 阶段流

```
Phase 0: 启动 + 版本管理
Phase 0.5: 环境探测（新增）
   自动扫描: Neo4j/Docker/SQLite/Git/PaddleOCR
   缺密码? → ask_user() 交互式询问
Phase 1: 技能定义
   Skill Hub 查前置知识 + Web/Wikipedia 摘要
   LLM 增强 → 结构化定义（前置知识/核心概念/常见陷阱）
Phase 2: 案例搜索
   Skill Hub: 关键词重叠过滤 → 排除 agentskill_skills/ 假案例
   Web 搜索: LLM 生成多样化搜索词（6 个）
   Wikipedia: 标题去重 + 无关结果过滤
   所有 case 带 type/relevance 字段
Phase 3: 模式提炼
   规则路径: 领域匹配(skill_domain_patterns.json) + 通用模式
   LLM 路径: 零预设领域，从案例智能提取模式
   继承过滤: 不相关模式自动过滤（最多保留最近3版）
Phase 4: 构建验证工具
   生成 assess.py → 选择题 + 模式覆盖率检查
   复制 practical hooks → practice/ 目录
   hook 互斥规则: neo4j 匹配时排除 sql.py
Phase 5: 运行验证
   知识测试: LLM 批量评估 / 规则评分
   实操测试: 自动扫描 practice/ 运行所有 hook
   最终评分: 加权综合（知识35% + 模式35% + 实操30%）
```

### 迭代反馈环

每次学习创建 `revN/` 版本目录，下次迭代继承上一版模式：

```
skills_learning/{skill_name}/
  ├── rev1/         第一次学习（案例+模式+工具+报告）
  ├── rev2/         第二次学习（继承 rev1 模式并改进）
  ├── rev3/         第三次学习（继承 rev1+rev2）
  └── ...           保留最近3版，旧版自动清理
```

---

## LLM 增强

| 阶段 | 规则路径 | LLM 增强路径 |
|------|----------|-------------|
| P1 定义 | Wikipedia 摘要拼接 | 结构化定义（前置知识+概念+陷阱） |
| P2 搜索 | 模板化搜索词 x3 | 多样化搜索词 x6 |
| P3 模式 | 领域关键词匹配 | 零预设领域，智能模式提取+技能分解 |
| P5 评估 | 规则评分（基于模式质量） | 批量评估 8 题 + 真实场景实操题 |

```bash
set SKILL_LLM_ENABLE=1           # 启用 LLM
set LLM_API_BASE=http://localhost:11434/v1  # Ollama 默认
set LLM_API_KEY=sk-xxx           # DeepSeek/OpenAI
set LLM_MODEL=deepseek-chat      # 模型名
set LLM_TIMEOUT=120              # 超时秒数
set LLM_CACHE_ENABLE=1           # 缓存（默认开启）
```

---

## 环境探测

工具自动探测本机可用服务，缺密码时交互式询问：

```bash
[探测] 可用: neo4j, docker, sqlite, git, paddle_ocr
```

| 服务 | 端口 | 用途 | 密码变量 |
|------|------|------|----------|
| Neo4j | 7687 (Bolt) | Cypher 查询验证 | `neo4j_password` |
| Docker | WSL socket | Compose 校验 | 无需密码 |
| SQLite | CLI | SQL 查询验证 | 无需密码 |
| Git | CLI | Git 操作验证 | 无需密码 |
| PaddleOCR | 8090 (llama-server) | OCR 图像识别 | 无需密码（localhost） |

---

## 实操测试体系

### practice/ 目录

每个 `revN/` 包含一个 `practice/` 子目录，存放实操测试脚本：

```
revN/
  ├── practice/
  │   ├── neo4j_hook.py     ← 真实 Neo4j 连接，执行 Cypher 查询
  │   ├── docker_compose.py ← 真实 docker compose config 校验
  │   ├── sql.py           ← SQLite 查询验证
  │   ├── git.py           ← Git 操作验证
  │   └── document_check.py ← PaddleOCR-VL 图像识别 + 本地库检测
  ├── tools/
  │   └── assess.py
  └── patterns/
```

### 统一接口

每个 hook 遵循标准协议：

```python
def run(env: dict = None) -> dict:
    """env 来自 env_detector.detect_all()"
    返回 {"score": 0-100, "passed": bool, "note": str}
}

if __name__ == "__main__":
    print(json.dumps(run()))
```

### hook 匹配规则

```
neo4j/cypher/graph_database/图数据库 → neo4j_hook.py
docker/compose/container            → docker_compose.py
sql/mysql/postgres/sqlite            → sql.py
git                                  → git.py
async/asyncio                        → python_async.py
图像/凭证/证件/鉴定/ocr/image        → document_check.py
```

### hook 互斥

当更特定的 hook 已匹配时，排除通用 hook：
- `neo4j_hook.py` 已匹配 → 排除 `sql.py`, `docker_compose.py`
- `docker_compose.py` 已匹配 → 排除 `sql.py`

---

## 案例质量过滤

### 多层过滤链

```
Skill Hub 搜索结果
  ↓ 关键词重叠过滤（排除不通用的 skill 定义）
  ↓ agentskill_skills/ 前缀过滤（排除内部技能元数据）
  ↓
Web 搜索结果（LLM 生成多样化搜索词）
  + Wikipedia（标题去重 + 无关内容过滤）
  ↓
最终案例列表（带 type/relevance 字段）
```

### 效果对比（cypher_programming_language）

```
改前: 15案例 → 10条无关skill定义 + 5条wiki
改后: 30案例 → 0条无关skill定义 + 30条真实web文章 ✅
```

---

## 安全设计

| 风险 | 防护措施 |
|------|----------|
| 路径遍历 | `_sanitize_skill_name()` 清洗目录名 |
| API Key 泄漏 | 子进程过滤 `_API_KEY`/`_SECRET` 等敏感后缀 |
| 代码注入 | eval/exec 限制 `__builtins__`，无 `open`/`__import__` |
| 模板注入 | `json.dumps()` 自动转义，无 eval/exec |
| Shell 注入 | 使用列表参数调用 subprocess.run |

---

## CLI 参数

```bash
python -m tools.skill_learn_from_cases [skill_name] [选项]

选项:
  --dry-run       预览：显示环境/领域/hooks 而不实际执行
  --list          列出所有已学习的技能
  --show SKILL    显示某技能的最新学习报告
  --version       显示工具版本
  --force         强制刷新搜索案例（不继承上一版）
  --delete SKILL  删除指定技能的所有学习记录
```

### --dry-run 示例

```bash
$ python -m tools.skill_learn_from_cases wiki_search --dry-run
[DRY RUN] 将学习技能: wiki_search
          目录名: wiki_search
          流程: Phase 0→1→2→3→4→5
          环境: neo4j, docker, sqlite, git, paddle_ocr
          LLM: 启用(deepseek-chat)
```

---

## 领域扩展

`skill_domain_patterns.json` 控制领域匹配，当前支持 16 个领域：

```
async, performance, fastapi, web_scraping, kubernetes,
database, frontend_react, git, testing, networking,
finance, image_processing, document_verification,
remote_sensing, graph_database, search
```

新增领域：在 JSON 中添加 `domain_name → {keywords, principles[]}` 即可。

---

## 版本演进

| 版本 | 改进 |
|------|------|
| v1 | 基础 5 阶段流 + 规则模式提取 |
| v2 | LLM 增强（Phase 1/2/3/5）+ 批量评估 |
| v3 | 安全审计修复（路径/密钥/eval）|
| v4 | 案例质量过滤（Skill Hub 关键词 + agentskill 排除）|
| v5 | 环境探测 + practice/目录 + 统一 hook 接口 |
| v6 | search 领域扩展 + 无关 domain 匹配收紧 |
| v7 | hook 互斥规则 + PaddleOCR-VL 集成 |
| v8 | --dry-run 增强 + ask_user 交互式询问 |
