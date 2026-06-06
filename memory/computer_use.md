# computer_use

L3 memory: ljqCtrl.py ljqCtrl_sop.md ui_detect.py

## 1. 基础规则
枚举窗口总是可用：GUI任务先用 win32gui 枚举标题/类名/rect，确定目标窗口、前台状态和客户区原点后再操作。
优先使用 Python UIA；若UIA可用，探测和操作均可使用UIA；游戏不使用UIA；
一旦 UIA 对该窗口无效，立刻改用 ui_detect 定位；
ui_detect 不足时才用 vision，vision 只用于语义理解、确认界面状态和辅助判断目标，不可信其坐标，不要直接按 vision 坐标点击。
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
