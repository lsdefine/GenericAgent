# entry_dict.json 字段说明

`data/entry_dict.json` 是一个 JSON 字典，键为字符串形式的样本编号（`"0"` ~ `"19"`，共 20 条）。
每条样本是一个对象，字段如下：

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `instruction` | string | 自然语言指令（英文），即喂给模型的题面 |
| `database_name` | string | 目标数据库名（本数据集统一为 `test_db`）|
| `table_info` | object | 目标表的结构与初始数据，用于在 sandbox 中建表灌库 |
| `table_info.name` | string | 表名 |
| `table_info.column_info_list` | array&lt;object&gt; | 列定义列表，每项含 `name`（列名）和 `type`（SQL 类型，如 `INT` / `TEXT`）|
| `table_info.row_list` | array&lt;array&gt; | 初始行数据，二维数组；内层数组的元素顺序与 `column_info_list` 对应 |
| `skill_list` | array&lt;string&gt; | 该题考察的 SQL 技能标签列表（ |
| `answer_info` | object | 参考答案信息 |
| `answer_info.sql` | string | 参考答案 SQL 语句（INSERT / UPDATE / DELETE / SELECT 之一）|
| `answer_info.md5` | string | 参考答案对应结果的 md5 摘要，用于 SELECT 类题目结果比对 |
| `answer_info.direct` | any &#124; null | 直接答案字段，DBBench 一般为 `null`（评测以 SQL 执行结果为准）|
