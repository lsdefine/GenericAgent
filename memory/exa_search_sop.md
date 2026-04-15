# Exa Search SOP

> Semantic web search with content retrieval. Use when `web_scan` / Google scraping is too noisy or when you need structured, typed results fast.

**触发**：需要搜索高质量网页内容、研究论文、公司信息、新闻，或需要"语义相似页面"
**禁用**：只需要浏览器自动化（走 `web_scan` / `web_execute_js`）；只需搜本地 skill 库（走 `skill_search`）

## 一次性准备

```bash
pip install exa-py
```

配置 API Key（二选一）：
```python
# 方式A：环境变量
# export EXA_API_KEY=sk-xxx

# 方式B：keychain（推荐，跨会话持久化）
import sys; sys.path.append('../memory')
from keychain import keys
keys.set('exa_api_key', 'sk-xxx')  # 一次性，后续自动读取
```

从 https://dashboard.exa.ai/api-keys 获取 key。

## 最简调用

```python
import sys; sys.path.append('../memory')
from exa_search import search

results = search("state of the art retrieval augmented generation 2025")
for r in results:
    print(f"- {r.title}  ({r.url})")
    print(f"  {r.snippet[:200]}")
```

返回 `list[ExaResult]`，字段：`title / url / snippet / published_date / author / score / highlights / summary / text`。
`snippet` 自动从 highlights → summary → text 级联提取，不用手动 fallback。

## API 签名

```python
search(query, *,
       num_results=10,
       search_type='auto',       # 'auto'|'neural'|'fast'|'instant'|'deep'|'deep-lite'|'deep-reasoning'
       category=None,            # 'company'|'research paper'|'news'|'personal site'|'financial report'|'people'
       include_domains=None,     # list[str]
       exclude_domains=None,
       include_text=None,        # list[str] 必含词
       exclude_text=None,
       start_published_date=None, end_published_date=None,  # ISO 8601
       text=None,                # True/dict/None  完整正文
       highlights=True,          # True/dict/None  高亮片段（默认开）
       summary=None)             # dict only, e.g. {'query':'key findings'}

find_similar(url, *, num_results=10, highlights=True, text=None, summary=None)
get_contents(urls, *, text=True, highlights=None, summary=None)
```

## 典型场景

### 1. 研究论文检索
```python
search("contrastive learning for dense retrieval",
       category="research paper", num_results=20,
       start_published_date="2024-01-01T00:00:00Z")
```

### 2. 公司尽调（限定域名）
```python
search("Anthropic funding rounds",
       category="company",
       include_domains=["crunchbase.com", "techcrunch.com"])
```

### 3. 要完整正文 + 摘要
```python
# 可同时拿三种内容，不是互斥
search("Kimi K2 benchmarks",
       text={"maxCharacters": 3000},
       highlights={"maxCharacters": 500, "query": "MMLU scores"},
       summary={"query": "benchmark results"})
```

### 4. 已知 URL 拿正文（不走搜索）
```python
from exa_search import get_contents
[page] = get_contents(["https://arxiv.org/abs/2501.00001"])
print(page.text)
```

### 5. 以图搜图式的语义近邻
```python
from exa_search import find_similar
find_similar("https://openai.com/index/gpt-5/", num_results=8)
```

## CLI

```bash
python ../memory/exa_search.py "agent frameworks 2025" 5
```

## 避坑

- ⚠️ **Exa 不再有 `keyword` search type**，老文档里的 `type="keyword"` 会报错，用 `type="fast"` 或 `type="auto"`
- ⚠️ **不要 `text=True` + `num_results=50`**：每个结果 ~几 KB 正文，会直接炸 LLM 上下文。要批量召回先只开 `highlights`，再对感兴趣的 URL 调 `get_contents`
- ⚠️ **`summary` 参数必须是 dict**，传 `True` 会报错（与 `text`/`highlights` 不同）
- ⚠️ **日期要 ISO 8601**，不是 `"2024-01-01"`，要带 `T00:00:00Z`
- ⚠️ **首次导入会起一个 client 单例**，切换 key 要重启 Python 或 `import exa_search; exa_search._client = None`
- ⚠️ **网络失败不会自动重试**：在 autonomous flow 里建议包一层 try / 指数退避
- ⚠️ **include_text / exclude_text 按词组匹配**，不是正则；每项建议 ≤5 词以免命中率为零

## 何时用 Exa vs 其他工具

| 场景 | 工具 |
|---|---|
| 需要高相关度的主题检索、论文、研究、公司信息 | **exa_search** |
| 要登录后的页面内容 / 浏览器会话中的交互 | `web_scan` + `web_execute_js` |
| Google 图搜、特定站点的爬取 | `web_scan`（走真实浏览器保留登录态） |
| 检索本地 105K 技能卡 | `skill_search` |
