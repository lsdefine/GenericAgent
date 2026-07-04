# IMA笔记 API

## ⚠️ 必读约束

### 🔒 认证

所有请求必须携带 Header：

```
ima-openapi-clientid: {IMA_OPENAPI_CLIENTID}
ima-openapi-apikey: {IMA_OPENAPI_APIKEY}
Content-Type: application/json
```

### 🔒 安全规则

- 笔记属于用户隐私，**不要在群聊中主动展示笔记内容**。
- 仅响应授权用户的笔记操作请求。

---

## 快速决策

| 用户意图                                                   | 接口别名                           |
| ---------------------------------------------------------- | ---------------------------------- |
| 「搜索笔记」「找包含XX的笔记」                             | `/openapi/note/v1/search_note`     |
| 「查看笔记本列表」「列出笔记本」「有哪些笔记本」           | `/openapi/note/v1/list_notebook`   |
| 「列出笔记」「查看XX笔记本里的笔记」                       | `/openapi/note/v1/list_note`       |
| 「从markdown新建笔记」「导入笔记」「创建笔记」「生成笔记」 | `/openapi/note/v1/import_doc`      |
| 「追加内容到笔记」「在笔记末尾添加」                       | `/openapi/note/v1/append_doc`      |
| 「获取笔记纯文本」「读取笔记内容」                         | `/openapi/note/v1/get_doc_content` |

---

## 数据结构

### 公共结构体

---

#### NoteBookInfo（笔记信息）

| 字段            | 类型        | 说明                                                 |
| --------------- | ----------- | ---------------------------------------------------- |
| `note_id`       | string      | 笔记唯一 ID                                          |
| `title`         | string      | 标题                                                 |
| `summary`       | string      | 简介                                                 |
| `create_time`   | int64       | 创建时间（Unix 毫秒）                                |
| `modify_time`   | int64       | 修改时间（Unix 毫秒）                                |
| `cover_image`   | string      | 封面缩略图 URL                                       |
| `note_ext_info` | NoteExtinfo | 扩展字段，见 [NoteExtinfo](#noteextinfo笔记扩展字段) |

---

#### NoteExtinfo（笔记扩展字段）

| 字段          | 类型   | 说明           |
| ------------- | ------ | -------------- |
| `folder_id`   | string | 所属笔记本 ID  |
| `folder_name` | string | 所属笔记本名称 |

---

#### NoteFolderInfo（笔记本信息）

| 字段               | 类型       | 说明                                                                                   |
| ------------------ | ---------- | -------------------------------------------------------------------------------------- |
| `folder_id`        | string     | 笔记本唯一 ID                                                                          |
| `name`             | string     | 笔记本名称                                                                             |
| `create_time`      | int64      | 创建时间（Unix 毫秒）                                                                  |
| `modify_time`      | int64      | 修改时间（Unix 毫秒）                                                                  |
| `note_number`      | int64      | 笔记本内笔记数量                                                                       |
| `parent_folder_id` | string     | 上级笔记本 ID（支持嵌套）                                                              |
| `folder_type`      | FolderType | 类型：`0`=USER_CREATE（用户自建），`1`=TOTAL（全部笔记），`2`=UN_CATEGORIZED（未分类） |

---

#### QueryInfo（搜索条件）

| 字段      | 类型   | 说明           |
| --------- | ------ | -------------- |
| `title`   | string | 标题搜索关键词 |
| `content` | string | 正文搜索关键词 |

---

#### SearchNoteInfo（搜索结果条目）

| 字段             | 类型                  | 说明                                                             |
| ---------------- | --------------------- | ---------------------------------------------------------------- |
| `note_book_info` | NoteBookInfo          | 笔记信息，见 [NoteBookInfo](#notebookinfo笔记信息)               |
| `highlightInfo`  | map\<string, string\> | 高亮匹配，key: `doc_title`，value: 包含 `<em>高亮词</em>` 的文本 |

---

### 请求/响应结构体

---

#### SearchNoteReq

| 字段          | 类型       | 必填   | 说明                                                                  |
| ------------- | ---------- | ------ | --------------------------------------------------------------------- |
| `search_type` | SearchType | 否     | 检索方式，`0`=DOC_TITLE(默认)，`1`=DOC_CONTENT                        |
| `sort_type`   | SortType   | 否     | 排序方式，`0`=MODIFY_TIME(默认)，`1`=CREATE_TIME，`2`=TITLE，`3`=SIZE |
| `query_info`  | QueryInfo  | 否     | 搜索条件，见 [QueryInfo](#queryinfo搜索条件)                          |
| `start`       | int64      | **是** | 翻页起始编号                                                          |
| `end`         | int64      | **是** | 翻页终止编号，与 start 相差不超过 20                                  |

#### SearchNoteRsp

| 字段                | 类型             | 说明                                                           |
| ------------------- | ---------------- | -------------------------------------------------------------- |
| `search_note_infos` | SearchNoteInfo[] | 搜索结果列表，见 [SearchNoteInfo](#searchnoteinfo搜索结果条目) |
| `is_end`            | bool             | 是否为最后一批数据                                             |
| `total_hit_num`     | int64            | 检索命中结果总数                                               |

---

#### ListNoteReq

| 字段        | 类型     | 必填   | 校验规则       | 说明                                                         |
| ----------- | -------- | ------ | -------------- | ------------------------------------------------------------ |
| `folder_id` | string   | 否     | tsecstr        | 笔记本 ID，为空则拉取全部笔记，根目录为 `user_list_{userid}` |
| `sort_type` | SortType | 否     | —              | 排序方式，`0`=MODIFY_TIME(默认)                              |
| `cursor`    | string   | **是** | tsecstr        | 游标，首次传空字符串 `""`                                    |
| `limit`     | uint64   | **是** | 0 < limit ≤ 20 | 每页数量                                                     |

#### ListNoteRsp

| 字段             | 类型           | 说明                                               |
| ---------------- | -------------- | -------------------------------------------------- |
| `note_book_list` | NoteBookInfo[] | 笔记列表，见 [NoteBookInfo](#notebookinfo笔记信息) |
| `is_end`         | bool           | 是否为最后一批数据                                 |

---

#### GetNoteContentReq

| 字段                    | 类型          | 必填   | 校验规则 | 说明                                                |
| ----------------------- | ------------- | ------ | -------- | --------------------------------------------------- |
| `note_id`               | string        | **是** | tsecstr  | 笔记唯一 ID，需要是本人的笔记                       |
| `target_content_format` | ContentFormat | **是** | —        | `0`=PLAINTEXT(推荐)，`1`=MARKDOWN(不支持)，`2`=JSON |

#### GetNoteContentRsp

| 字段      | 类型   | 说明                                              |
| --------- | ------ | ------------------------------------------------- |
| `content` | string | 笔记文本内容（按 target_content_format 格式返回） |

---

#### ImportNoteReq

| 字段             | 类型          | 必填   | 校验规则 | 说明                                        |
| ---------------- | ------------- | ------ | -------- | ------------------------------------------- |
| `content_format` | ContentFormat | **是** | —        | 固定为 `1`（MARKDOWN），目前仅支持 Markdown |
| `content`        | string        | **是** | —        | Markdown 格式正文内容，不要传空值           |
| `folder_id`      | string        | 否     | —        | 关联的笔记本 ID                             |
| `folder_name`    | string        | 否     | —        | 关联的笔记本名称                            |

#### ImportNoteRsp

| 字段      | 类型   | 说明            |
| --------- | ------ | --------------- |
| `note_id` | string | 新笔记的唯一 ID |

---

#### AppendNoteReq

| 字段             | 类型          | 必填   | 校验规则 | 说明                                    |
| ---------------- | ------------- | ------ | -------- | --------------------------------------- |
| `note_id`        | string        | **是** | tsecstr  | 目标笔记的唯一 ID，需要是本人的笔记     |
| `content_format` | ContentFormat | **是** | —        | 固定为 `1`（MARKDOWN），仅支持 Markdown |
| `content`        | string        | **是** | —        | 要追加的 Markdown 文本内容              |

#### AppendNoteRsp

| 字段      | 类型   | 说明              |
| --------- | ------ | ----------------- |
| `note_id` | string | 目标笔记的唯一 ID |

---

#### ListNoteFolderReq

| 字段      | 类型   | 必填   | 校验规则       | 说明                                             |
| --------- | ------ | ------ | -------------- | ------------------------------------------------ |
| `cursor`  | string | **是** | tsecstr        | 游标，第一页传 `"0"`，后续传返回的 `next_cursor` |
| `limit`   | uint64 | **是** | 0 < limit ≤ 20 | 每页数量                                         |
| `version` | string | 否     | tsecstr        | 版本号，用后台返回的值，用于增量更新检查         |

#### ListNoteFolderRsp

| 字段                | 类型             | 说明                                                       |
| ------------------- | ---------------- | ---------------------------------------------------------- |
| `note_folder_infos` | NoteFolderInfo[] | 笔记本列表，见 [NoteFolderInfo](#notefolderinfo笔记本信息) |
| `next_cursor`       | string           | 下次请求的起始游标                                         |
| `is_end`            | bool             | 是否为最后一批数据                                         |
| `next_version`      | string           | 版本号（可用于下次请求的 version 参数）                    |
| `need_update`       | bool             | 对比 version 是否需要更新                                  |

---

## 接口详情

> 每个接口的请求/响应结构体的完整字段定义见上方 [请求/响应结构体](#请求响应结构体) 部分。

---

### 1. SearchNote — 搜索笔记

POST /openapi/note/v1/search_note

**触发场景**：用户说「搜索」「找笔记」「查找包含XX的内容」

- **请求**：[SearchNoteReq](#searchnotereq)
- **响应**：[SearchNoteRsp](#searchnotersp)

---

### 2. ListNote — 获取笔记列表

POST /openapi/note/v1/list_note

**触发场景**：用户说「查看XX笔记本的笔记」「最近的笔记」「列出笔记」

- **请求**：[ListNoteReq](#listnotereq)
- **响应**：[ListNoteRsp](#listnotersp)

---

### 3. GetNoteContent — 获取笔记内容

POST /openapi/note/v1/get_doc_content

**触发场景**：用户说「读取笔记内容」「获取这篇笔记的纯文本」

> ⚠️ 需要用户是笔记作者

- **请求**：[GetNoteContentReq](#getnotecontentreq)
- **响应**：[GetNoteContentRsp](#getnotecontentrsp)

---

### 4. ImportNote — 新建笔记

POST /openapi/note/v1/import_doc

**触发场景**：用户说「新建笔记」「导入笔记」「把这段内容保存为笔记」

- **请求**：[ImportNoteReq](#importnotereq)
- **响应**：[ImportNoteRsp](#importnotersp)

---

### 5. AppendNote — 追加内容到笔记

POST /openapi/note/v1/append_doc

**触发场景**：用户说「在这篇笔记末尾追加内容」「把XX添加到笔记里」

> ⚠️ 需要用户是笔记作者

- **请求**：[AppendNoteReq](#appendnotereq)
- **响应**：[AppendNoteRsp](#appendnotersp)

---

### 6. ListNoteFolder — 笔记本列表

POST /openapi/note/v1/list_notebook

**触发场景**：用户说「列出笔记本」「有哪些分类」「查看笔记本目录」

- **请求**：[ListNoteFolderReq](#listnotefolderreq)
- **响应**：[ListNoteFolderRsp](#listnotefolderrsp)

---

## 枚举值

### `ContentFormat`（文本类型）

| 值  | 名称      | 说明          |
| --- | --------- | ------------- |
| `0` | PLAINTEXT | 纯文本        |
| `1` | MARKDOWN  | Markdown 格式 |
| `2` | JSON      | JSON 格式     |

### `SearchType`（检索方式）

| 值  | 名称        | 说明             |
| --- | ----------- | ---------------- |
| `0` | DOC_TITLE   | 标题检索（默认） |
| `1` | DOC_CONTENT | 正文检索         |

### `SortType`（排序方式）

| 值  | 名称        | 说明             |
| --- | ----------- | ---------------- |
| `0` | MODIFY_TIME | 更新时间（默认） |
| `1` | CREATE_TIME | 创建时间         |
| `2` | TITLE       | 标题             |
| `3` | SIZE        | 大小             |

### `FolderType`（笔记本类型）

| 值  | 名称           | 说明               |
| --- | -------------- | ------------------ |
| `0` | USER_CREATE    | 用户自建           |
| `1` | TOTAL          | 全部笔记（根目录） |
| `2` | UN_CATEGORIZED | 未分类             |

---

## 游标翻页使用规范

### 笔记本列表（ListNoteFolder）

1. 首次请求：`cursor` 传 `"0"`
2. 检查返回的 `is_end`：`false` 表示还有更多数据
3. 将返回的 `next_cursor` 作为下次请求的 `cursor`
4. `is_end = true` 时停止翻页

### 笔记列表（ListNote）

1. 首次请求：`cursor` 传空字符串 `""`
2. `is_end = true` 时停止翻页

### 搜索（SearchNote）

1. 首次请求：`start: 0, end: 20`
2. 翻页时递增 start/end
3. `is_end = true` 时停止

---

## 错误码（ErrorCode 枚举）

| 错误码 | 名称                   | 说明                     |
| ------ | ---------------------- | ------------------------ |
| 0      | OK                     | 成功                     |
| 210001 | PARAM_ERROR            | 参数错误                 |
| 210002 | REQ_WITH_INVALID_UID   | 携带无效的 UID           |
| 210003 | SERVICE_ERROR          | 服务器内部错误           |
| 210004 | SPACE_NOT_ENOUGH       | 用户空间不够             |
| 210005 | NOTE_NOT_OWNER         | 不是笔记的作者           |
| 210006 | NOTE_IS_DELETE         | 笔记已被删除             |
| 210007 | COS_CRED_ERROR         | 获取 COS 上传凭证出错    |
| 210008 | VERSION_CONFLICT       | 版本冲突                 |
| 210009 | CONTENT_SIZE_OVERLOAD  | 单篇笔记超过最大限制     |
| 210010 | EXIST_GUIDE            | 新手引导笔记添加重复     |
| 210011 | SHARE_DOC_NOPERM       | 共享知识库的笔记无权访问 |
| 210012 | USER_IS_DELETE         | 用户已注销               |
| 210030 | notebook_NAME_EXIST    | 笔记本名称重复           |
| 210031 | notebook_NUM_LIMIT     | 笔记本数量达到上限       |
| 210032 | BATCH_EXEC_FAIL        | 批量操作部分失败         |
| 210033 | BATCH_EXEC_ALL_FAIL    | 批量操作全部失败         |
| 210034 | PRIVATE_NOTE_NOT_OWNER | 笔记私有且不是作者       |
| 210035 | FOLDER_NOT_EXIST       | 笔记本不存在             |
| 210036 | ADD_KNOWLEDGE_FAIL     | 笔记添加知识库失败       |
| 20002  | —                      | apiKey 超过最大限频      |
| 20004  | —                      | apiKey 鉴权失败          |
