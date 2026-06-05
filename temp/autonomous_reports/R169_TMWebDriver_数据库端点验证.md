# R169: TMWebDriver 数据库端点验证报告

> 验证目标：TMWebDriver CDP数据库端点可用性
> 日期：2026-06-06

---

## 一、端点探测

| 端点 | 方法 | 结果 |
|:----:|:----:|:----:|
| `/tmdb_bridge` | GET/POST | ❌ 404 Not Found |
| `/link` + `execute_js` | POST | ✅ 可用 |
| `websocket://127.0.0.1:18765` | WS | ✅ 运行中 |

## 二、数据库操作验证（通过JS注入）

通过 `/link` 端点的 `execute_js` 命令，在 Browser 中执行 IndexedDB 操作：

| # | 操作 | 命令 | 结果 |
|:-:|:----:|:----|:----:|
| 1 | 🏗️ 打开数据库 | `indexedDB.open('TMWebDriver_Test', 1)` | ✅ `TMWebDriver_Test v1` |
| 2 | ✍️ 写入数据 | `put({id:1, name:'TMWebDriver', timestamp})` | ✅ `Write OK` |
| 3 | 📖 读取数据 | `get(1)` | ✅ `{"id":1,"name":"TMWebDriver","timestamp":1780690432092}` |
| 4 | 🔢 计数 | `count()` | ✅ `Count: 1` |

## 三、架构发现

1. **`/tmdb_bridge` 端点未实现** — TMWebDriver 当前无此路由
2. **实际数据库桥接方式**：通过 `/link` 端点的 `execute_js` 在浏览器内执行 IndexedDB/WebSQL
3. **CDP桥扩展**（`assets/tmwd_cdp_bridge/`）支持：cookies、CDP命令、batch操作、tab管理
4. **IndexedDB 全链路可用**：createObjectStore → put → get → count 均正常

## 四、建议

1. 如需独立DB桥端点，建议在TMWebDriver.py中添加 `/api/db` 路由，转发SQL到浏览器IndexedDB
2. 当前可通过 `execute_js` + IndexedDB API 完全代替专用端点

---

*报告由自判别流程生成*
