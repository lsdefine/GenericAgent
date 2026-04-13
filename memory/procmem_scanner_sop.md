# Memory Scanner SOP

## 1. 快速开始
内存特征搜索工具，支持 Hex (CE 风格) 和 字符串匹配。特别提供 LLM 模式，方便大模型分析内存上下文。

**Python 调用方式:**
```python
import sys
sys.path.append('../memory') # 直接挂载工具目录
from procmem_scanner import scan_memory

# 示例：搜索特定 Hex 特征码，开启 llm_mode 以获取上下文
results = scan_memory(pid, "48 8b ?? ?? 00", mode="hex", llm_mode=True)
```

**CLI:**
```powershell
# 基础搜索
python ../memory/procmem_scanner.py <PID> "pattern" --mode string

# LLM 增强模式（输出包含上下文的 JSON，推荐）
python ../memory/procmem_scanner.py <PID> "pattern" --llm
```

## 2. 典型场景：结构体或关键数据定位
1. 确定目标数据的前导特征或已知常量（如特定的 Header 或 Magic Number）。
2. 在目标进程中搜索该特征：
   `scan_memory(pid, "4D 5A 90 00", mode="hex", llm_mode=True)`
3. 分析返回的 JSON 中 `context` 字段，查看目标地址前后的原始字节及 ASCII 预览。

## 3. 注意事项
- **权限**: 并非强制要求管理员权限，但需具备对目标进程的 `PROCESS_QUERY_INFORMATION` 和 `PROCESS_VM_READ` 权限。
- **效率**: 搜索大块内存时，尽量提供更唯一的特征码以减少误报。

## 4. CE式差集扫描定位动态字段
定位微信等自绘UI中随操作变化的内存字段（如当前会话标题）。核心：一次全量scan + 多次ReadProcessMemory筛选。

**流程（3个联系人A/B/C即可收敛）：**
1. 取PID：Weixin.exe有多进程，用`win32gui.GetWindowThreadProcessId`取有窗口的
2. 当前会话=A → `scan_memory(pid, "人名A", mode="string")` → 地址集S
3. 切到B → 读S全部地址 → 保留内容≠"人名A"的 → 候选C
4. 切到A → 读C全部地址 → 保留内容=="人名A"的 → 候选C'（通常1-3个）
5. 若C'>1 → 再切B/C重复 → 直到唯一

**切换会话+读地址 完整代码：**
```python
import sys; sys.path.append('../memory')
import ljqCtrl, pygetwindow as gw, pyperclip, time, ctypes

def switch_chat(name):
    win = gw.getWindowsWithTitle('微信')[0]
    if win.isMinimized: win.restore()
    win.activate(); time.sleep(0.3)
    S = 1 / ljqCtrl.dpi_scale
    ljqCtrl.Click(int((win.left+150)*S), int((win.top+40)*S)); time.sleep(0.5)
    pyperclip.copy(name); ljqCtrl.Press('ctrl+v'); time.sleep(1.5)
    ljqCtrl.Click(int((win.left+150)*S), int((win.top+130)*S)); time.sleep(0.8)

def read_addrs(pid, addrs):
    k32 = ctypes.windll.kernel32
    hp = k32.OpenProcess(0x10, False, pid)
    buf = ctypes.create_string_buffer(256)
    rd = ctypes.c_size_t()
    result = {}
    for a in addrs:
        a = int(a, 16) if isinstance(a, str) else a
        k32.ReadProcessMemory(hp, ctypes.c_void_p(a), buf, 256, ctypes.byref(rd))
        result[a] = buf.raw.split(b'\x00')[0].decode('utf-8', errors='ignore').strip()
    k32.CloseHandle(hp)
    return result  # {addr: text}
```

**坑点：**
- 进程名Weixin.exe（非WeChat.exe）；地址字符串先`int(addr,16)`
- 步骤3筛≠A（排除空/乱码），步骤4筛==A（正向确认），交替最快
- **搜索切换会话完全可用**，大部分差集步骤直接搜索即可。注意：搜索结果首条可能是广告，粘贴后≥1.5s再点，确认是联系人再点（或点第2条）
- **仅最终消歧步骤需侧栏点击**：候选>1时，在侧栏点一个不同的人（不经搜索框），read_addrs看哪个地址跟随变化→那个就是标题栏
- 切换后用read_addrs验证确实切成功了再继续
- **步骤3/4必须用read_addrs读原始地址集，严禁重新scan**：重新scan只能找到静态残留(聊天记录等)，动态地址已变不在结果中，会导致0候选
- **选A/B联系人用wechat_db_utils.quick_connect查真人**，避免搜索触发广告弹窗（公众号/小程序名会弹广告）
- **scan_memory返回格式**：默认返回str列表（每项"Addr:0x...\nHex:..."），非dict。提取地址用`[int(r.split('\n')[0].split(':')[1],16) for r in results]`
- **侧栏点击禁止估算坐标**：会话列表顺序随消息变化。参考 vision_sop + wechat_send_sop 流程（截图→ask_vision→精确坐标→点击）