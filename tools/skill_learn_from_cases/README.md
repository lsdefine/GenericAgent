# skill_learn_from_cases   案例驱动技能学习 CLI 工具

通过真实案例学习一项技能，并用案例验证能力习得  
零外部依赖 除搜索引擎 API key   可选大模型增强

---

## 快速开始

```bash
# 最简用法 纯规则模式
python -m tools.skill_learn_from_cases docker_compose_production

# 查看预览 展示环境/领域/hooks
python -m tools.skill_learn_from_cases wiki_search --dry-run

# 启用 LLM 增强
set SKILL_LLM_ENABLE=1
set LLM_API_BASE=https://api.deepseek.com/v1
set LLM_API_KEY=sk-xxx
set LLM_MODEL=deepseek-chat
python -m tools.skill_learn_from_cases cypher_programming_language

# 支持中英文混合技能名
python -m tools.skill_learn_from_cases 人机交互ui设计原型handoff
```

## 6 阶段工作流

```text
Phase 0:    启动  目录创建 + 环境探测
Phase 0.5:  探测  自动扫描 Neo4j/Docker/SQLite/Git/PaddleOCR 缺密码时交互询问
Phase 1:    定义  LLM 结构化定义 Wikipedia 摘要
Phase 2:    搜索  多个渠道并行搜索 + 同义词扩展 + 多步案例过滤
Phase 3:    模式  LLM 智能提取 + 技能分解  规则匹配 16 个领域
Phase 4:    构建  生成评估工具 + 实操测试 practice/ 目录
Phase 5:    验证  知识测试 + 实操测试 + 模式覆盖率
     \_____________________/
        迭代反馈环 继承+改进
```

## 元学习闭环

本工具最独特的特性是能够**学习技能后反哺自身**:

```text
学习技能  提取知识模式  应用到 CLI 工具自身  验证效果  继续迭代
```

已成功完成 5 轮元学习闭环:

| 轮次 | 学习技能 | 评分 | 应用到 CLI 工具 |
|:----:|---------|:----:|----------------|
| 1 | structured_logging | 95/100 | 新建 logging_setup.py, llm_helper.py print logger |
| 2 | cli_ux_design | 86/100 | --help 重写为结构化文档 |
| 3 | test_strategy | 94/100 | 15 个测试覆盖 4 个模块 + CI 配置 |
| 4 | wiki_search | 97/100 | 搜索词同义词扩展 多步案例过滤 |
| 5 | error_handling | 84/100 | 异常分类 错误上下文日志 |

## 核心特性

### 1. LLM 增强 可选降级

| 阶段 | LLM 路径 | 规则降级路径 |
|------|---------|-------------|
| 定义 | 结构化定义 前置知识 概念 陷阱 | Wikipedia 摘要 |
| 搜索 | 6 个多样化搜索词 | 模板化搜索词 含同义词扩展 |
| 模式 | 智能模式提取 + 技能分解 | 16 个领域关键词匹配 |
| 验证 | 批量评估 + 实操题 | 模式覆盖质量评分 |

### 2. 环境探测 + 实操测试

自动探测本机可用服务 缺密码时 ask_user 交互询问:

| 服务 | 探测方式 | 用途 |
|------|---------|------|
| Neo4j | 端口 7687 + env | Cypher 实操测试 |
| Docker | WSL Docker socket | Compose 实操测试 |
| SQLite | CLI sqlite3 | SQL 实操测试 |
| Git | git --version | Git 实操测试 |
| PaddleOCR | 端口 8090 + API | 文档鉴权实操测试 |

结果存入 practice/ 目录:

```text
rev5/
  practice/
    neo4j_hook.py      真实 Neo4j 连接 100/100
    docker_compose.py  docker compose config 校验
    sql.py             SQLite 查询验证
    git.py             Git 操作验证
    python_async.py    异步代码执行
    react_hook.py      Node.js 浏览器检测
    ui_design_hook.py  Chrome Edge 设计工具检测
    document_check.py  PaddleOCR-VL 图像识别 85/100
```

### 3. 案例质量过滤

3 层过滤链确保案例质量:

```text
原始搜索结果   Skill Hub 关键词重叠过滤
                     Wikipedia 标题去重 + 无关内容过滤
                          agentskill_skills 前缀排除
                              最终高质量案例集
```

效果: cypher 技能相关案例从 27% 提升到 83%

### 4. 安全设计

| 风险 | 防护措施 |
|------|----------|
| 路径遍历 | sanitize_skill_name 清洗目录名 |
| API Key 泄漏 | 子进程过滤 API_KEY SECRET 等敏感后缀 |
| 代码注入 | eval exec 限制 builtins 无 open import |
| 模板注入 | json.dumps 自动转义 |
| Shell 注入 | 列表参数调用 subprocess.run |

## CLI 参数

```bash
python -m tools.skill_learn_from_cases [skill_name] [选项]

选项:
  --dry-run       预览 显示环境/领域/hooks
  --list          列出所有已学习的技能
  --show SKILL    显示某技能的最新学习报告
  --version       显示工具版本
  --force         强制刷新搜索案例 不继承上一版
  --delete SKILL  删除指定技能的所有学习记录
```

## 工作流示例

```bash
1. 初次学习:
   python -m tools.skill_learn_from_cases docker_compose_production

2. 查看已有学习:
   python -m tools.skill_learn_from_cases --list
   python -m tools.skill_learn_from_cases --show wiki_search

3. 强制刷新 重新搜索案例:
   python -m tools.skill_learn_from_cases python_async --force

4. LLM 增强学习:
   set SKILL_LLM_ENABLE=1
   set LLM_API_KEY=sk-xxx
   python -m tools.skill_learn_from_cases image_voucher_verification
```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| SKILL_LLM_ENABLE | 0 | 启用 LLM 增强 |
| LLM_API_BASE | http://localhost:11434/v1 | LLM API 端点 |
| LLM_API_KEY |  | API 密钥 |
| LLM_MODEL | qwen2.5:7b | 模型名 |
| LLM_TIMEOUT | 120 | HTTP 超时秒数 |
| LLM_CACHE_ENABLE | 1 | 启用 LLM 响应缓存 |
| LLM_CACHE_TTL | 86400 | 缓存有效期秒数 |
| neo4j_password |  | Neo4j 数据库密码 |
| SKILL_FORCE_REFRESH | 0 | 强制刷新案例 |

## 测试

```bash
pip install pytest
python -m pytest tests/ -v
```

## 目录结构

```text
tools/skill_learn_from_cases/
  engine.py            6 阶段流编排
  assess_template.py   评估工具模板
  env_detector.py      环境自动探测
  llm_helper.py        统一 LLM 接口 + 缓存
  logging_setup.py     结构化日志
  dir_manager.py       版本目录管理 + 路径清洗
  name_converter.py    中英文技能名转换 含 71 个映射
  skill_domain_patterns.json  16 个领域库
  practical_hooks/     9 个实操测试 hook
tests/
  tools/skill_learn_from_cases/
    test_name_converter.py
    test_env_detector.py
    test_dir_manager.py
.github/workflows/
  ci.yml
```

## 扩展指南

### 新增领域

编辑 skill_domain_patterns.json 添加新条目:

```json
{
  "new_domain": {
    "keywords": ["keyword1", "keyword2"],
    "domain_label": "新领域",
    "principles": [
      {"principle": "最佳实践描述", "id": "P_xxx", "confidence": 90}
    ]
  }
}
```

### 新增实操 hook

在 practical_hooks/ 下创建文件实现 run env -> dict 接口,
然后在 engine.py 的 hook_rules 列表中添加关键词匹配。

## 依赖

Python 3.10+
pip: neo4j  用于 Neo4j 实操测试
可选: pytesseract/PIL/paddleocr  用于 OCR 实操测试

## License

MIT
