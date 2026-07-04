# Notes (笔记)

> ⛔ Before ANY write (`import_doc`/`append_doc`): validate ALL string fields (`content`, `title`) are legal UTF-8.
> Non-UTF-8 content causes irreversible garbled text in IMA. See root SKILL.md § MANDATORY RULES for platform-specific validation methods.

API base path: `openapi/note/v1`

通过 IMA OpenAPI 管理用户个人笔记，支持读取（搜索、列表、获取内容）和写入（新建、追加）。

完整的数据结构和接口参数详见 `references/api.md`。

> **隐私规则：** 笔记内容属于用户隐私，在群聊场景中只展示标题和摘要，禁止展示笔记正文。

## 接口决策表

| 用户意图                                                                          | 调用接口          | 关键参数                                                                  |
| --------------------------------------------------------------------------------- | ----------------- | ------------------------------------------------------------------------- |
| 搜索/查找笔记                                                                     | `search_note`     | `query_info`（QueryInfo 对象）                                            |
| 查看笔记本列表 / 列出笔记本                                                       | `list_notebook`   | `cursor`(必填，首页传`"0"`) + `limit`(必填)                               |
| 列出笔记/获取多篇笔记信息                                                         | `list_note`       | `folder_id`(选填,空为全部) + `sort_type` + `cursor`(首次传`""`) + `limit` |
| 读取笔记正文                                                                      | `get_doc_content` | `note_id` + `target_content_format`(必填，推荐`0`纯文本)                  |
| 新建一篇笔记（用户明确说"新建/创建笔记"时走此接口）                               | `import_doc`      | `content` + `content_format`(必填，固定`1`) + 可选 `folder_id`            |
| 往已有笔记追加内容（⚠️ **敏感操作**：用户必须明确指定目标笔记，否则先确认再操作） | `append_doc`      | `note_id` + `content` + `content_format`(必填，固定`1`)                   |

## ⚠️ 新建 vs. 追加 — 行为规则

**新建笔记（`import_doc`）** 和 **追加内容到已有笔记（`append_doc`）** 是两个完全不同的操作，务必正确区分：

### 明确走新建的信号词

用户说以下任一表述时，**直接调用 `import_doc` 创建新笔记**：

- "**新建**笔记"、"**创建**笔记"、"**写一篇**笔记"
- "**新建**一篇笔记记录这些内容"

### 明确走追加的信号词

用户说以下任一表述时，**调用 `append_doc` 追加到已有笔记**（但仍需确认目标笔记，见下方规则）：

- "把这段话**追加到**《XX》笔记里"
- "在那篇笔记**末尾加上**这段内容"

### 模糊场景 — 必须先询问用户

以下表述**既可能是新建、也可能是追加**，agent **不得自行假设**，必须先向用户确认：

- "帮我记一下"、"记录一下"、"保存为笔记"、"存成笔记"
- "把这段内容记到笔记里"
- "添加到笔记里"
- 任何其他未明确表达"新建"或"追加"意图的表述

询问示例：

> "您是想**创建一篇新笔记**，还是**追加到某篇已有笔记**？"

### 追加到已有笔记是敏感操作

`append_doc` 会**不可撤销地修改**用户的现有笔记，因此必须谨慎处理：

1. **用户明确指定了目标笔记** — 可以直接追加。例如：

   - "把这段话追加到《会议纪要》笔记里"
   - "在那篇笔记末尾加上这段内容"（上下文中已有明确的笔记对象）

2. **用户没有明确指定目标笔记** — **必须先向用户确认**，不要自行猜测。例如：
   - 用户说"添加到笔记里" → 询问："您想追加到哪篇已有笔记？请提供笔记标题或让我帮您搜索。"
   - 用户说"把这个加到之前那篇笔记" → 如果上下文中有多篇笔记或不确定是哪篇 → 列出候选笔记让用户选择

> **原则**：不确定时，先问。宁可多问一句，也不要误改用户的已有笔记或自作主张创建新笔记。

### 🖼️ 本地图片不支持

`import_doc` 和 `append_doc` 的 `content` 字段仅支持Markdown，**不支持本地图片**。

写入笔记内容前，必须检查并处理图片引用：

1. **过滤本地图片** — 如果用户提供的内容中包含本地图片路径（如 `![](file:///...)`, `![](/Users/...)`, `![](C:\...)` 等），**移除这些图片引用**，不要将其写入笔记。
2. **告知用户** — 移除后主动提醒用户：
   > "笔记接口暂不支持上传本地图片，以下图片已被过滤：`xxx.png`、`yyy.jpg`。您可以先将图片上传到网络，再用网络链接插入笔记。"
3. **保留网络图片** — 以 `http://` 或 `https://` 开头的图片链接可以正常保留。

## 常用工作流

### 查找并阅读笔记

先搜索获取 `note_id`，再用 `get_doc_content` 读取正文：

```bash
# 1. 按标题搜索
ima_api "openapi/note/v1/search_note" '{"search_type": 0, "query_info": {"title": "会议纪要"}, "start": 0, "end": 20}'
# 从返回的 search_note_infos[].note_book_info.note_id 中取目标笔记 ID

# 2. 读取正文（纯文本格式，Markdown 格式目前不支持）
ima_api "openapi/note/v1/get_doc_content" '{"note_id": "目标note_id", "target_content_format": 0}'
```

### 列出自己有哪些笔记

直接使用`list_note`，拉取全部笔记列表，直到符合用户要求（如：用户要求全部笔记，则到 `is_end=true` 时停止；用户要求近30天的笔记，则根据`modify_time`与当前时间判断停止）

```bash
# 1. 拉取全部笔记的列表（首页 cursor 传 ""）
ima_api "openapi/note/v1/list_note" '{"folder_id":"", "sort_type":0, "cursor": "", "limit": 20}'
# 获取全部笔记中前20篇笔记的信息

```

### 浏览笔记本里的笔记

先拉笔记本列表获取 `folder_id`，再拉该笔记本下的笔记：

```bash
# 1. 列出笔记本（首页 cursor 传 "0"）
ima_api "openapi/note/v1/list_notebook" '{"cursor": "0", "limit": 20}'

# 2. 拉取指定笔记本的笔记（首页 cursor 传 ""）
ima_api "openapi/note/v1/list_note" '{"folder_id": "目标folder_id", "cursor": "", "limit": 20}'
```

### 新建笔记

```bash
# 新建到默认位置
ima_api "openapi/note/v1/import_doc" '{"content_format": 1, "content": "# 标题\n\n正文内容"}'

# 新建到指定笔记本
ima_api "openapi/note/v1/import_doc" '{"content_format": 1, "content": "# 标题\n\n正文内容", "folder_id": "笔记本ID"}'
# 返回 note_id，后续可用于 append_doc
```

### 追加内容到已有笔记

```bash
ima_api "openapi/note/v1/append_doc" '{"note_id": "笔记ID", "content_format": 1, "content": "\n## 补充内容\n\n追加的文本"}'
```

### 按正文搜索

```bash
ima_api "openapi/note/v1/search_note" '{"search_type": 1, "query_info": {"content": "项目排期"}, "start": 0, "end": 20}'
```

## 核心响应字段

**搜索结果**（`SearchNoteInfo`）：笔记信息路径为 `search_note_infos` 包含 `NoteBookInfo`，关键字段：`note_id`、`title`、`summary`、`create_time`、`modify_time`、`note_ext_info.folder_id`、`note_ext_info.folder_name`。额外包含 `highlightInfo`（高亮匹配，key 为 `doc_title`，value 含 `<em>高亮词</em>`）。

**笔记列表条目**（`NoteBookInfo`）：关键字段：`note_id`、`title`、`summary`、`create_time`、`modify_time`、`cover_image`、`note_ext_info`（含 `folder_id`、`folder_name`）。

**笔记本条目**（`NoteFolderInfo`）：关键字段：`folder_id`、`name`、`note_number`、`create_time`、`modify_time`、`parent_folder_id`、`folder_type`（`0`=用户自建，`1`=全部笔记，`2`=未分类）。

**写入结果**（`import_doc`/`append_doc`）：返回 `note_id`（新建或目标笔记的唯一 ID）。

完整字段定义见 `references/api.md`。

## 分页

- **游标分页 — 笔记本列表**（`list_notebook`）：首次 `cursor: "0"`，后续用 `next_cursor`，`is_end=true` 时停止。
- **游标分页 — 笔记列表**（`list_note`）：首次 `cursor: ""`，`is_end=true` 时停止。
- **偏移量分页**（`search_note`）：首次 `start: 0, end: 20`，翻页时递增，`is_end=true` 时停止。

## 枚举值

- **`content_format`：** `0`=纯文本，`1`=Markdown，`2`=JSON。写入（`import_doc`/`append_doc`）目前仅支持 `1`（Markdown）。读取（`get_doc_content`）推荐 `0`（纯文本），Markdown 格式不支持。
- **`search_type`：** `0`=标题检索（默认），`1`=正文检索
- **`sort_type`：** `0`=更新时间（默认），`1`=创建时间，`2`=标题，`3`=大小（仅 `search_note_book` 使用）
- **`folder_type`：** `0`=用户自建，`1`=全部笔记（根目录），`2`=未分类

## 注意事项

- `folder_id` 不可为 `"0"`，根目录 ID 格式为 `user_list_{userid}`（从 `folder_type=1` 的笔记本条目获取）
- 笔记内容有大小上限，超过时返回 `100009`，可拆分为多次 `append_doc` 写入
- 写入内容不支持本地图片，写入前必须过滤本地图片路径并告知用户（详见"🖼️ 本地图片不支持"规则）
- 展示笔记列表时只展示标题、摘要和修改时间，不要主动展示正文
- 时间字段是 Unix 毫秒时间戳，展示时转为可读格式
- 返回数据为嵌套结构：搜索结果取 `SearchNoteInfo[].note_book_info.note_id`，笔记本列表取 `NoteFolderInfo[].folder_id`，笔记列表取 `NoteBookInfo[].note_id`，注意按层级解析

## 错误处理

| 错误码 | 含义                   | 建议处理                     |
| ------ | ---------------------- | ---------------------------- |
| 100001 | 参数错误               | 检查请求参数格式和必填字段   |
| 100002 | 无效 ID                | 检查凭证配置                 |
| 100003 | 服务器内部错误         | 等待后重试                   |
| 100004 | size 不合法 / 空间不够 | 检查参数范围                 |
| 100005 | 无权限                 | 确认操作的是用户自己的笔记   |
| 100006 | 笔记已删除             | 告知用户该笔记不存在         |
| 100008 | 版本冲突               | 重新获取内容后再操作         |
| 100009 | 超过大小限制           | 拆分为多次 `append_doc` 写入 |
| 310001 | 笔记本不存在           | 检查 `folder_id` 是否正确    |
| 20002  | apiKey超过最大限频     |
| 20004  | apikey 鉴权失败        | 检查凭证配置是否正确         |
