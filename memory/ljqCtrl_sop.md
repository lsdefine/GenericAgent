# ljqCtrl 使用与坐标转换 SOP

> **must call update working ckp**：`ljqCtrl一律使用物理坐标｜禁pyautogui｜操作前先gw激活窗口`

## 0. API 快速参考 (Signatures)
- `ljqCtrl.dpi_scale`: float (缩放系数 = 逻辑宽度 / 物理宽度)
- `ljqCtrl.SetCursorPos(z)`: 移动鼠标到逻辑坐标 z=(x, y)
- `ljqCtrl.Click(x, y=None)`: 模拟点击。支持 `Click((x, y))` 或 `Click(x, y)`
- `ljqCtrl.Press(cmd, staytime=0)`: 模拟按键。如 `Press('ctrl+c')`
- `ljqCtrl.FindBlock(fn, wrect=None, threshold=0.8)`: 找图。返回 `((center_x, center_y), is_found)`
- `ljqCtrl.MouseDClick(staytime=0.05)`: 鼠标双击

## 1. 环境载入
必须先将 `../memory` 加入路径，才能导入工具模块：
```python
import sys, os, pygetwindow as gw
sys.path.append("../memory")
import ljqCtrl
```

## 2. 核心：High-DPI 物理坐标换算
`ljqCtrl` 的 `Click/MoveTo` 接口接收的是**物理像素坐标**。
当使用 `pygetwindow` 等工具获取窗口位置（逻辑坐标）时，必须除以缩放系数。

- **换算公式**：`物理坐标 = 逻辑坐标 / ljqCtrl.dpi_scale`
- **注意**：3840 (4K) 仅为当前开发机示例，实际物理边界由系统环境决定，代码应始终通过 `dpi_scale` 动态计算。

## 3. 窗口操作与点击流程
1. **激活窗口**：使用 `gw.getWindowsWithTitle('标题')` 获取窗口，执行 `restore()` 和 `activate()`。
2. **坐标计算**：
```python
win = gw.getWindowsWithTitle('微信')[0]
# 计算窗口内某个点的逻辑坐标 (lx, ly)
# 转换为物理坐标并点击
px, py = lx / ljqCtrl.dpi_scale, ly / ljqCtrl.dpi_scale
ljqCtrl.Click(px, py)
```

## 4. 避坑指南
- **⚠️ 一律使用物理坐标**：传给 ljqCtrl.Click/SetCursorPos 的坐标必须是物理坐标（=截图像素坐标）。从 pygetwindow 获取的逻辑坐标需先 `/ dpi_scale` 转换。禁止传入逻辑坐标。
- **物理验证**：模拟操作前必须确保窗口已通过 `activate()` 置于前台。
- **偏移量**：所有的相对偏移像素值（如“向右移动 10 像素”）同样需要除以 `dpi_scale`。
- **坐标对齐**: 物理坐标 = 截图坐标；ljqCtrl 自动处理 DPI 换算，禁止手动重复计算。
- **⚠️ 窗口坐标转换陷阱**：使用 `win32gui.GetWindowRect(hwnd)` 获取的矩形包含标题栏和边框，而截图内容是客户区。点击截图内元素时，必须用 `win32gui.ClientToScreen(hwnd, (0, 0))` 获取客户区原点的屏幕坐标，再加上截图内坐标。禁止直接用 GetWindowRect 左上角 + 截图坐标。
- **⚠️ win32 DPI 坐标陷阱**：未调用 `SetProcessDPIAware()` 时，`GetWindowRect/ClientToScreen/GetClientRect` 等拿到的窗口/客户区坐标通常是**逻辑坐标**；若后续截图或 `ljqCtrl` 使用的是物理像素，必须统一做 `坐标 / ljqCtrl.dpi_scale`。等价方案：先 `SetProcessDPIAware()`，之后全流程直接使用 raw 物理坐标，禁止逻辑/物理坐标混用。
- **文本输入**：ljqCtrl 无 TypeText/SendKeys。向输入框键入文本：先点击/三击选中字段，再 `pyperclip.copy('文本'); ljqCtrl.Press('ctrl+v')`。