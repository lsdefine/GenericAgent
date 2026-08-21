# 连接本地核心：包内 bridge + 外部 `GA_ROOT`

## 架构边界

Desktop 2.0 始终执行发布包内的 `frontends/desktop_bridge.py` 与
`frontends/conductor.py`。用户选择的仓库只作为外部核心和数据根，通过 `GA_ROOT`
传给包内进程；外部仓库中的桌面脚本不会被执行。

因此 identity 必须同时满足：

- `app_dir` 位于发布包的 `runtime/app/frontends`；
- `ga_root` 等于当前有效外部核心；没有有效 override 时，Windows/Linux 等于包内
  `runtime/app`，macOS `.app` 等于 Application Support 中的版本化可写副本；
- `build_id` 等于当前 Desktop 构建。

`frontends/desktop/static/**` 属于 upstream Desktop v1，React v2 不读取、复制或校验其
字节内容。React v2 只拥有 `src/**`、`public/**`、Vite 配置和 `dist/**`。

## `set_ga_source`

1. 检查目标包含 `agentmain.py`；不要求目标包含 `desktop_bridge.py`。
2. 使用包内 Python 和包内 `frontends/ga_contract_probe.py` 探测目标，显式把候选路径传为
   `GA_ROOT`。探测缺失、无结论或不兼容均失败。
3. 探测通过后才写入 `ga_source_override`。
4. 异步重启包内 bridge，并等待 `/services/identity` 的 `ga_root` 指向候选核心。
5. 任一步失败都恢复旧设置，并重新启动旧工作区；若回滚也失败，错误同时报告两段结果。

## `clear_ga_source`

清除 override 后异步重启包内 bridge，等待 identity 回到默认核心。Windows/Linux 默认核心
是包内 `runtime/app`；macOS 为避免首启修改签名 `.app`，会在首次需要时原子复制到
`~/Library/Application Support/GenericAgent/runtime/<version>/app` 并使用该可写副本。失败时
恢复原 override 并重启原工作区。

启动时若保存的 override 已被移动或删除，`valid_ga_source_override` 会忽略它，bridge
自动回退包内 runtime；`get_ga_source` 对这种失效设置返回空字符串。

## `move_ga_runtime`

命令保持既有 Tauri 调用形态，但内部通过后台任务复制：

1. 源为当前有效外部核心；没有外部核心时为平台默认核心（macOS 是可写副本）。
2. 复制完成后，将目标作为新 override，按上述带回滚流程切换并验证 identity。
3. 只有切换成功后才允许删除旧源。
4. 包内 `runtime/app` 和平台默认内部核心永远不删除；失败时旧源和旧设置都保留。

React 2.0 本轮不提供此命令的 UI 入口，但权限、注册和后端契约继续保留。

## 用户可见错误

| 类别 | UI 文案 |
| --- | --- |
| 缺少 `agentmain.py` | 无效仓库 / Invalid repository |
| compatibility probe 不通过 | 与 Desktop 2.0 不兼容 / Incompatible with Desktop 2.0 |
| bridge readiness 超时 | 启动超时 / Startup timed out |
| 无法解析包内 runtime | 无法定位运行时 / Cannot resolve runtime |
| 其他或回滚失败 | 切换失败 / Switch failed |

## 必测场景

- 兼容核心连接成功，identity 的 `app_dir` 仍属于发布包、`ga_root` 指向外部核心。
- 不兼容核心在设置写入前失败。
- 从核心 A 切换核心 B 失败时恢复 A，并可继续聊天。
- override 被删除后重启，自动回退包内 runtime。
- foreign port 不被强杀；端口释放后可恢复启动。
- 包整体移动到含空格和非 ASCII 字符的路径后仍能定位包内 bridge。
- macOS DMG 已带 `.prepared`，首启、重启和移动前后 `.app` 文件树不得变化。
- `move_ga_runtime` 成功、复制失败、切换失败和包内源保护路径均有 Rust/原生覆盖。
