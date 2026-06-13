# computer_use

L3 memory: ljqCtrl.py ljqCtrl_sop.md ui_detect.py

## 1. 基础规则
枚举窗口总是可用：GUI任务先用 win32gui 枚举标题/类名/rect，确定目标窗口、前台状态和客户区原点后再操作。
优先使用 Python UIA；若UIA可用，探测和操作均可使用UIA；游戏不使用UIA；
一旦 UIA 对该窗口无效，立刻改用 ui_detect 定位；
ui_detect 不足时才用 vision，vision 只用于语义理解、确认界面状态和辅助判断目标，不可信其坐标
Windows 下窗口截图和操作使用 ljqCtrl：严禁 pyautogui；记得先 Activate 到前台；
坑1-DPI：一律物理坐标；坑2-遮盖/失焦：混乱先枚举窗口确认前台；
ui_detect 的 bbox 是截图内坐标，点击前必须用 `ClientToScreen(hwnd,(0,0))/dpi_scale + bbox中心` 转屏幕物理坐标
坐标转换禁用 `GetWindowRect` 或 DWM 窗口矩形直接加截图坐标（含标题栏/边框/阴影会错位）
ljqCtrl.Click 后会返回像素/前台变化，0% 或近 0% 变化立即停下诊断，禁止盲目重试。
ljqCtrl 失效或目标为网络游戏时，必须使用硬件键鼠 Xbananakb / Arduino Leonardo（如有）
网络游戏除非用户明确允许，严禁普通键鼠事件，必须硬件执行。

## 2. GUI操作节奏建议
进入新界面时，建议先只探测不操作：枚举窗口 + UIA + ljqCtrl截图 + ui_detect，读完实际输出再决定下一步
明确一个操作后，可以在同一轮执行该动作，短暂等待，再立刻枚举窗口 + 截图/ui_detect 验证新状态；不要在未知状态下把多步决策写进大脚本
尽量不要预测关键词筛候选，应看 detect 输出、坐标、层级和上下文判断
若确定UIA可用则少用ui_detect/ljqCtrl；若UIA不可用，则后续不用UIA

临时截图/可视化文件用后清理，或固定文件名覆盖，避免堆积。
ui_detect 可跨端复用；手机端沿用本原则时，UIA 换成 ui dump/adb_ui，ljqCtrl 控制换成 adb

## 3. macOS 平台
macOS 定位链与 §1 一致，工具映射如下：
- 控制层：`import macljqCtrl as ljqCtrl`（替代 Windows ljqCtrl）
- 窗口枚举：`ListWindows()` → 返回 id/app/title/bbox/pid（替代 win32gui）
- 激活：`ActivateApp(pid)`（pid 来自 ListWindows，禁止用名字子串——同厂商 bundle 前缀会误伤）
- UIA 层 = AX 辅助功能 API：`AXElements(pid)` 枚举控件树 → role/desc/title/id/物理坐标 xywh；`AXFind(pid, role=, desc=, title=)` 过滤；`AXPress(el)` 免坐标点击
- 坐标：AX 返回逻辑点，库内自动 /dpi_scale 转物理像素，与 Click/Screenshot 统一；Retina 默认 scale=0.5
- 截图：`GrabWindow(window_id)` 或 `ScreenCapAt(x, y, radius)`（物理坐标）
- 权限：首次使用需授予「辅助功能」权限（系统设置 > 隐私与安全 > 辅助功能）；`AXIsProcessTrusted()` 检测
- 依赖：`pip install pyobjc-framework-ApplicationServices`（AX 相关，软依赖——未装时键鼠/截图正常，仅 AX 函数不可用）
- 节奏同 §2：先 ListWindows + AXElements 探测，确认控件后再操作；AXPress 优先，回退 Click(phys_cx, phys_cy)
