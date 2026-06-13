"""
macljqCtrl —— ljqCtrl 的 macOS 等价实现 (Quartz CGEvent + screencapture)。
与 ljqCtrl.py API 镜像对齐, 跨平台代码可写 `import macljqCtrl as ljqCtrl`。

CRITICAL: 严禁 import pyautogui。
依赖: pyobjc-framework-Quartz, pyobjc-framework-Cocoa (其余 numpy/opencv/Pillow 同 Windows 版)。
坐标约定 (与 Windows 版完全一致):
  - 对外 API 接收【物理像素坐标】(= screencapture/ui_detect 截图内坐标)
  - dpi_scale = 逻辑点 / 物理像素 (Retina=0.5, 普通屏=1.0)
  - 逻辑坐标 = 物理坐标 * dpi_scale  (CGEvent 内部用逻辑点)

权限前置 (缺失则键鼠/截图静默失败):
  - 辅助功能(Accessibility): 系统设置>隐私与安全性>辅助功能, 授权 GA 宿主进程
  - 屏幕录制(Screen Recording): 同上>屏幕录制
  用 macljqCtrl.check_permissions() 自检。

API 快速参考:
  - dpi_scale: float
  - Click(x, y=None, check=True): 物理坐标; check=True 比较前后像素变化, 返回变化信息
  - SetCursorPos((x,y)): 物理坐标移动鼠标
  - Press(cmd, staytime=0): 快捷键, 如 'cmd+v' 'cmd+c' 'enter' 'cmd+shift+4'
  - TypeText(s): 直接键入文本(Unicode, 无需剪贴板)
  - MouseClick / MouseDClick / MouseDown / MouseUp / RightClick
  - GrabWindow(win) -> PIL Image: 指定窗口截图(物理像素)。win=窗口号(int)或标题/应用名子串(str)
  - GrabScreen(bbox=None) -> PIL Image: 全屏或区域截图, bbox=(l,u,r,b)物理像素
  - ScreenCapAt(x, y, r=100) -> PIL Image: 物理坐标(x,y)±r 区域截图
  - FindBlock(fn, wrect=None, threshold=0.8) -> ((cx,cy), is_found): 模板匹配, 物理坐标
  - ListWindows(name=None) -> [dict]: 枚举窗口(替代 win32gui), 返回号/标题/应用/物理bbox
  - ActivateApp(name): 激活应用到前台(替代 win32gui.SetForegroundWindow)
"""
import os, sys, time, subprocess, tempfile, math
import numpy as np

try:
    from PIL import Image, ImageGrab, ImageEnhance, ImageFilter, ImageDraw
    import cv2
    _HAS_CV2 = True
except Exception:
    _HAS_CV2 = False

import Quartz
from AppKit import NSScreen, NSWorkspace, NSPasteboard, NSStringPboardType, NSRunningApplication

verbose_click = True  # Click 像素变化打印开关

# ---------- 屏幕几何 & dpi_scale ----------
_main = Quartz.CGMainDisplayID()
_bounds = Quartz.CGDisplayBounds(_main)
cwidth = int(_bounds.size.width)    # 逻辑点宽 (CGEvent 坐标系)
cheight = int(_bounds.size.height)
_mode = Quartz.CGDisplayCopyDisplayMode(_main)
swidth = int(Quartz.CGDisplayModeGetPixelWidth(_mode))   # 物理像素宽
sheight = int(Quartz.CGDisplayModeGetPixelHeight(_mode))
dpi_scale = cwidth / swidth if swidth else 1.0           # 逻辑/物理, Retina=0.5


def check_permissions(verbose=True):
    """返回 (accessibility_ok, screen_recording_ok)。缺失时打印授权指引。"""
    sc = bool(Quartz.CGPreflightScreenCaptureAccess()) if hasattr(Quartz, 'CGPreflightScreenCaptureAccess') else None
    ax = None
    try:
        import HIServices
        ax = bool(HIServices.AXIsProcessTrusted())
    except Exception:
        try:
            from ApplicationServices import AXIsProcessTrusted
            ax = bool(AXIsProcessTrusted())
        except Exception:
            ax = None
    if verbose:
        print(f'[PERM] Accessibility(键鼠): {ax}   ScreenRecording(截图): {sc}')
        if ax is False:
            print('  → 系统设置>隐私与安全性>辅助功能, 勾选 GA 宿主进程后重启 GA')
        if sc is False:
            print('  → 系统设置>隐私与安全性>屏幕录制, 勾选 GA 宿主进程后重启 GA')
    return ax, sc


# ---------- 鼠标 ----------
def _post(ev):
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)

def _cursor_logical():
    e = Quartz.CGEventCreate(None)
    loc = Quartz.CGEventGetLocation(e)
    return loc.x, loc.y

def _phys_to_logical(x, y):
    return x * dpi_scale, y * dpi_scale

def SetCursorPos(z):
    """z=(x,y) 物理坐标。移动鼠标(不点击)。"""
    lx, ly = _phys_to_logical(int(z[0]), int(z[1]))
    ev = Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventMouseMoved,
                                        Quartz.CGPointMake(lx, ly), Quartz.kCGMouseButtonLeft)
    _post(ev)
    time.sleep(0.05)

def _mouse_event(etype, button=Quartz.kCGMouseButtonLeft):
    lx, ly = _cursor_logical()
    ev = Quartz.CGEventCreateMouseEvent(None, etype, Quartz.CGPointMake(lx, ly), button)
    _post(ev)

def MouseDown():
    _mouse_event(Quartz.kCGEventLeftMouseDown)
def MouseUp():
    _mouse_event(Quartz.kCGEventLeftMouseUp)

def MouseClick(staytime=0.05):
    MouseDown(); time.sleep(staytime)
    MouseUp(); time.sleep(0.05)

def MouseDClick(staytime=0.05):
    # 真双击: 同坐标连发2次, 用 click state=2
    lx, ly = _cursor_logical()
    p = Quartz.CGPointMake(lx, ly)
    for state in (1, 2):
        down = Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventLeftMouseDown, p, Quartz.kCGMouseButtonLeft)
        Quartz.CGEventSetIntegerValueField(down, Quartz.kCGMouseEventClickState, state)
        _post(down)
        up = Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventLeftMouseUp, p, Quartz.kCGMouseButtonLeft)
        Quartz.CGEventSetIntegerValueField(up, Quartz.kCGMouseEventClickState, state)
        _post(up)
    time.sleep(0.05)

def RightClick(staytime=0.05):
    lx, ly = _cursor_logical()
    p = Quartz.CGPointMake(lx, ly)
    down = Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventRightMouseDown, p, Quartz.kCGMouseButtonRight)
    _post(down); time.sleep(staytime)
    up = Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventRightMouseUp, p, Quartz.kCGMouseButtonRight)
    _post(up); time.sleep(0.05)

# ---------- 键盘 ----------
# macOS 虚拟键码 (kVK_*)
_KEYMAP = {
    'a':0,'s':1,'d':2,'f':3,'h':4,'g':5,'z':6,'x':7,'c':8,'v':9,'b':11,'q':12,
    'w':13,'e':14,'r':15,'y':16,'t':17,'1':18,'2':19,'3':20,'4':21,'6':22,'5':23,
    '=':24,'9':25,'7':26,'-':27,'8':28,'0':29,']':30,'o':31,'u':32,'[':33,'i':34,
    'p':35,'l':37,'j':38,"'":39,'k':40,';':41,'\\':42,',':43,'/':44,'n':45,'m':46,
    '.':47,'`':50,
    'enter':36,'return':36,'tab':48,'space':49,' ':49,'delete':51,'backspace':51,
    'esc':53,'escape':53,'forwarddelete':117,
    'left':123,'right':124,'down':125,'up':126,
    'home':115,'end':119,'pageup':116,'pagedown':121,
    'f1':122,'f2':120,'f3':99,'f4':118,'f5':96,'f6':97,'f7':98,'f8':100,'f9':101,
    'f10':109,'f11':103,'f12':111,
}
_MODS = {
    'cmd':Quartz.kCGEventFlagMaskCommand, 'command':Quartz.kCGEventFlagMaskCommand,
    'ctrl':Quartz.kCGEventFlagMaskControl, 'control':Quartz.kCGEventFlagMaskControl,
    'alt':Quartz.kCGEventFlagMaskAlternate, 'option':Quartz.kCGEventFlagMaskAlternate,
    'opt':Quartz.kCGEventFlagMaskAlternate,
    'shift':Quartz.kCGEventFlagMaskShift,
    'fn':Quartz.kCGEventFlagMaskSecondaryFn,
}

def _key_tap(keycode, flags=0):
    down = Quartz.CGEventCreateKeyboardEvent(None, keycode, True)
    if flags: Quartz.CGEventSetFlags(down, flags)
    _post(down)
    up = Quartz.CGEventCreateKeyboardEvent(None, keycode, False)
    if flags: Quartz.CGEventSetFlags(up, flags)
    _post(up)

def Press(cmd, staytime=0):
    """快捷键。如 'cmd+v' 'cmd+shift+4' 'enter' 'cmd+c'。Win版的 ctrl 在mac多对应 cmd, 调用方自行决定。"""
    parts = [p.strip().lower() for p in str(cmd).split('+') if p.strip()]
    flags = 0; key = None
    for p in parts:
        if p in _MODS: flags |= _MODS[p]
        else: key = p
    if key is None:
        return
    kc = _KEYMAP.get(key)
    if kc is None:
        # 单字符走 TypeText
        TypeText(key)
    else:
        _key_tap(kc, flags)
    if staytime: time.sleep(staytime)
    time.sleep(0.03)

def TypeText(s):
    """直接键入 Unicode 文本 (无需剪贴板)。"""
    for ch in str(s):
        ev = Quartz.CGEventCreateKeyboardEvent(None, 0, True)
        Quartz.CGEventKeyboardSetUnicodeString(ev, len(ch), ch)
        _post(ev)
        ev2 = Quartz.CGEventCreateKeyboardEvent(None, 0, False)
        Quartz.CGEventKeyboardSetUnicodeString(ev2, len(ch), ch)
        _post(ev2)
        time.sleep(0.005)

# 剪贴板 (替代 pyperclip)
def set_clipboard(text):
    pb = NSPasteboard.generalPasteboard()
    pb.clearContents()
    pb.setString_forType_(text, NSStringPboardType)

def get_clipboard():
    pb = NSPasteboard.generalPasteboard()
    return pb.stringForType_(NSStringPboardType)

def Paste(text):
    """把 text 放剪贴板并 cmd+v 粘贴 (等价 Win版 pyperclip+ctrl+v)。"""
    set_clipboard(text); time.sleep(0.05); Press('cmd+v')


# ---------- 截图 (screencapture, 输出物理像素) ----------
def GrabScreen(bbox=None):
    """全屏或区域截图 -> PIL Image。bbox=(l,u,r,b) 物理像素坐标。"""
    fd, fn = tempfile.mkstemp(suffix='.png'); os.close(fd)
    try:
        if bbox:
            l, u, r, b = bbox
            # screencapture -R 用逻辑点; 转换 物理->逻辑
            lx, ly = l*dpi_scale, u*dpi_scale
            lw, lh = (r-l)*dpi_scale, (b-u)*dpi_scale
            cmd = ['/usr/sbin/screencapture','-x','-t','png',
                   f'-R{lx:.0f},{ly:.0f},{lw:.0f},{lh:.0f}', fn]
        else:
            cmd = ['/usr/sbin/screencapture','-x','-t','png', fn]
        subprocess.run(cmd, check=True, capture_output=True)
        return Image.open(fn).copy()
    finally:
        try: os.remove(fn)
        except Exception: pass

def ScreenCapAt(x, y, r=100):
    """物理坐标(x,y)为中心±r 截图 -> PIL Image。"""
    return GrabScreen((x-r, y-r, x+r, y+r))

def GrabWindow(win):
    """窗口截图 -> PIL Image。win=窗口号(int) 或 标题/应用名子串(str)。物理像素。"""
    if isinstance(win, str):
        ws = ListWindows(win)
        if not ws: raise RuntimeError(f'window not found: {win}')
        win = ws[0]['id']
    fd, fn = tempfile.mkstemp(suffix='.png'); os.close(fd)
    try:
        subprocess.run(['/usr/sbin/screencapture','-x','-o','-l',str(win),'-t','png',fn],
                       check=True, capture_output=True)
        return Image.open(fn).copy()
    finally:
        try: os.remove(fn)
        except Exception: pass

# ---------- 窗口枚举 / 激活 (替代 win32gui) ----------
def ListWindows(name=None):
    """枚举屏上窗口 -> [{'id','title','app','bbox'(物理像素 l,u,r,b),'pid'}]。
    name: 标题或应用名子串过滤(不区分大小写)。"""
    opts = Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements
    infos = Quartz.CGWindowListCopyWindowInfo(opts, Quartz.kCGNullWindowID)
    out = []
    inv = 1.0 / dpi_scale  # 逻辑->物理
    for w in infos:
        b = w.get('kCGWindowBounds') or {}
        layer = w.get('kCGWindowLayer', 0)
        if layer != 0:  # 只要普通应用窗口层
            continue
        title = w.get('kCGWindowName') or ''
        app = w.get('kCGWindowOwnerName') or ''
        l = b.get('X', 0)*inv; u = b.get('Y', 0)*inv
        r = l + b.get('Width', 0)*inv; bo = u + b.get('Height', 0)*inv
        rec = {'id': int(w.get('kCGWindowNumber', 0)), 'title': title, 'app': app,
               'pid': int(w.get('kCGWindowOwnerPID', 0)),
               'bbox': (int(l), int(u), int(r), int(bo))}
        if name:
            n = name.lower()
            if n not in title.lower() and n not in app.lower():
                continue
        out.append(rec)
    return out

def ActivateApp(target):
    """激活应用到前台 (替代 SetForegroundWindow)。

    macOS 的前台是 *应用* 粒度而非窗口句柄粒度, 故无法 1:1 镜像 Win 版
    Activate(hwnd)。target 支持两种定位键, 优先用精确的:
      - int  : 进程 pid (来自 ListWindows 的 'pid' 字段) —— 精确, 不受语言/本地化影响, **推荐**
      - str  : 应用名 / bundle id。按精确度分级匹配, 避免误中同厂商应用:
               ① bundle id 精确等值 (如 'com.tencent.meeting') —— 最可靠
               ② localizedName 精确等值 (如 '腾讯会议')
               ③ localizedName 子串 (最后兜底, 可能模糊)
               注意: 不对 bundle id 做子串匹配, 因同厂商应用共享前缀
               (微信 com.tencent.xinWeChat 与腾讯会议 com.tencent.meeting 都含 'tencent')。
    返回是否成功。"""
    ws = NSWorkspace.sharedWorkspace()
    # 1) pid 精确激活 (首选)
    if isinstance(target, int):
        app = NSRunningApplication.runningApplicationWithProcessIdentifier_(target)
        if app is not None:
            app.activateWithOptions_(1 << 1)  # NSApplicationActivateAllWindows
            time.sleep(0.3)
            return True
        return False
    # 2) 字符串: 按精确度分级匹配 (避免同厂商前缀误伤)
    key = str(target)
    keyl = key.lower()
    apps = list(ws.runningApplications())
    def _fire(app):
        app.activateWithOptions_(1 << 1)
        time.sleep(0.3)
        return True
    # ① bundle id 精确等值
    for app in apps:
        if (app.bundleIdentifier() or '').lower() == keyl:
            return _fire(app)
    # ② localizedName 精确等值
    for app in apps:
        if (app.localizedName() or '').lower() == keyl:
            return _fire(app)
    # ③ localizedName 子串 (兜底)
    for app in apps:
        if keyl in (app.localizedName() or '').lower():
            return _fire(app)
    # 3) 兜底用 open -a
    try:
        subprocess.run(['open', '-a', str(target)], check=True, capture_output=True)
        time.sleep(0.5); return True
    except Exception:
        return False


# ---------- 模板匹配 FindBlock ----------
def GetWRect(sr):
    """快捷区域名 -> 物理像素 [l,u,r,b]。如 'left2'=左半屏, 'top3'=上1/3。"""
    num = int(sr[-1])
    l, u, r, b = 0, 0, swidth, sheight
    if 'left' in sr: r = swidth // num
    if 'right' in sr: l = swidth * (num - 1) // num
    if 'top' in sr: b = sheight // num
    if 'bottom' in sr: u = sheight * (num - 1) // num
    return [l, u, r, b]

def FindBlock(fn, wrect=None, verbose=0, threshold=0.8):
    """在屏幕(或wrect区域)内找模板图 fn。返回 ((cx,cy), is_found), 物理坐标。
    fn: 模板图路径(str)或 PIL Image。
    wrect: None=全屏 | [l,u,r,b]物理像素 | 'left2'等快捷名 | PIL Image(直接当搜索底图)。"""
    if not _HAS_CV2:
        raise RuntimeError('FindBlock 需要 opencv-python 和 Pillow')
    if wrect is not None and isinstance(wrect, Image.Image):
        scr, wrect = wrect, None
    else:
        if isinstance(wrect, str): wrect = GetWRect(wrect)
        scr = GrabScreen(wrect)  # 物理像素
    blc = Image.open(fn) if isinstance(fn, str) else fn
    T = cv2.cvtColor(np.array(blc), cv2.COLOR_RGB2BGR)
    B = cv2.cvtColor(np.array(scr), cv2.COLOR_RGB2BGR)
    tsh, tsw = T.shape[:2]
    res = cv2.matchTemplate(B, T, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)
    oj, oi = max_loc
    if wrect is None: wrect = [0, 0, scr.size[0], scr.size[1]]
    obj = (oj + wrect[0] + tsw // 2, oi + wrect[1] + tsh // 2)
    if verbose:
        print(f'FindBlock {fn}: score={max_val:.4f} at phys={obj}')
    return obj, max_val > threshold

def imshow(mt, sec=0):
    cv2.imshow('cc', mt); cv2.waitKey(sec)



# ---------- Click (带像素变化检测) ----------
def Click(x, y=None, check=True, r=60):
    """物理坐标点击。check=True 时比较点击前后周边像素变化, 返回 (变化百分比, 截图)。
    若变化≈0 → 可能点歪了 (同 Win 版语义)。"""
    if y is None and isinstance(x, (tuple, list)):
        x, y = x[0], x[1]
    x, y = int(x), int(y)
    before = None
    if check:
        try: before = np.array(ScreenCapAt(x, y, r))
        except Exception: before = None
    SetCursorPos((x, y)); time.sleep(0.05)
    MouseClick()
    if check:
        time.sleep(0.25)
        try:
            after = np.array(ScreenCapAt(x, y, r))
        except Exception:
            return None
        if before is not None and before.shape == after.shape:
            diff = np.mean(np.any(before != after, axis=-1)) * 100
            if verbose_click:
                print(f'Click({x},{y}) pixel change: {diff:.1f}%')
            if diff < 0.5:
                print(f'[WARN] Click({x},{y}) 像素变化≈0%, 可能点歪了, 请诊断坐标!')
            return diff, Image.fromarray(after)
    return None


# ---------- AX 辅助功能控件枚举 (UIA 层的 macOS 等价) ----------
try:
    from ApplicationServices import (
        AXUIElementCreateApplication, AXUIElementCopyAttributeValue,
        AXValueGetValue, AXUIElementPerformAction, AXIsProcessTrusted,
        kAXChildrenAttribute, kAXRoleAttribute, kAXDescriptionAttribute,
        kAXPositionAttribute, kAXSizeAttribute, kAXWindowsAttribute,
        kAXTitleAttribute, kAXValueCGPointType, kAXValueCGSizeType,
        kAXPressAction,
    )
    _HAS_AX = True
except ImportError:
    _HAS_AX = False


def _ax_attr(el, key):
    """读取单个 AX 属性,失败返回 None。"""
    if not _HAS_AX:
        return None
    err, val = AXUIElementCopyAttributeValue(el, key, None)
    return val if err == 0 else None


def AXElements(target, max_depth=10, include_zero_size=False):
    """枚举应用控件树。

    Parameters
    ----------
    target : int | str
        pid(int) 或 bundle_id(str, 如 'com.tencent.meeting')。
    max_depth : int
        递归深度上限。
    include_zero_size : bool
        是否包含 w<=0 或 h<=0 的零尺寸节点。

    Returns
    -------
    list[dict] : 每项含 role/desc/title/id/value/x/y/w/h(物理像素)/depth/el。
        value 为控件当前值(文本/输入框内容等),非文本值为 None。
        el 是原始 AXUIElement 引用,目标窗口关闭/重建后失效,AXPress 前宜就近重新枚举。
    """
    if not _HAS_AX:
        raise RuntimeError(
            'AX 不可用。请安装: pip install pyobjc-framework-ApplicationServices')
    if not AXIsProcessTrusted():
        raise PermissionError('需要授予辅助功能权限(系统设置 > 隐私与安全 > 辅助功能)')
    # 解析 target → pid
    if isinstance(target, str):
        ws = AppKit.NSWorkspace.sharedWorkspace()
        pid = None
        for a in ws.runningApplications():
            if a.bundleIdentifier() == target:
                pid = a.processIdentifier()
                break
        if pid is None:
            raise ValueError(f'找不到 bundle_id={target!r} 对应的运行中应用')
    else:
        pid = int(target)

    app_el = AXUIElementCreateApplication(pid)
    wins = _ax_attr(app_el, kAXWindowsAttribute) or []
    scale = dpi_scale  # 逻辑/物理, Retina=0.5

    results = []

    def _walk(el, depth):
        if depth > max_depth:
            return
        role = _ax_attr(el, kAXRoleAttribute)
        desc = _ax_attr(el, kAXDescriptionAttribute)
        title = _ax_attr(el, kAXTitleAttribute)
        ident = _ax_attr(el, 'AXIdentifier')
        value = _ax_attr(el, 'AXValue')
        # AXValue 多为 str/num(文本/输入框);若是 AXValueRef(坐标等)忽略
        if value is not None and not isinstance(value, (str, int, float, bool)):
            value = None
        pos_val = _ax_attr(el, kAXPositionAttribute)
        sz_val = _ax_attr(el, kAXSizeAttribute)
        # 解包坐标(逻辑点)
        px = py_ = pw = ph = 0.0
        if pos_val is not None:
            ok, pt = AXValueGetValue(pos_val, kAXValueCGPointType, None)
            if ok:
                px, py_ = pt.x, pt.y
        if sz_val is not None:
            ok, sz = AXValueGetValue(sz_val, kAXValueCGSizeType, None)
            if ok:
                pw, ph = sz.width, sz.height
        # 转物理像素
        phys_x = px / scale if scale else px
        phys_y = py_ / scale if scale else py_
        phys_w = pw / scale if scale else pw
        phys_h = ph / scale if scale else ph

        if not include_zero_size and (phys_w <= 0 or phys_h <= 0):
            pass  # 跳过零尺寸,但仍递归子节点
        else:
            results.append(dict(
                depth=depth, role=role, desc=desc, title=title, id=ident,
                value=value,
                x=round(phys_x), y=round(phys_y),
                w=round(phys_w), h=round(phys_h), el=el))
        for child in (_ax_attr(el, kAXChildrenAttribute) or []):
            _walk(child, depth + 1)

    for win in wins:
        _walk(win, 0)
    return results


def AXPress(element) -> bool:
    """对 AX element 执行 Press 动作(免坐标点击)。"""
    if not _HAS_AX:
        return False
    err = AXUIElementPerformAction(element, kAXPressAction)
    return err == 0


def AXFind(target, role=None, desc=None, title=None, identifier=None, max_depth=10):
    """枚举并过滤控件。所有过滤条件为子串匹配(大小写不敏感)。

    Returns
    -------
    list[dict] : 匹配项,同 AXElements 返回格式。
    """
    nodes = AXElements(target, max_depth=max_depth)
    out = []
    for n in nodes:
        if role and (not n['role'] or role.lower() not in n['role'].lower()):
            continue
        if desc and (not n['desc'] or desc.lower() not in n['desc'].lower()):
            continue
        if title and (not n['title'] or title.lower() not in n['title'].lower()):
            continue
        if identifier and (not n['id'] or identifier.lower() not in n['id'].lower()):
            continue
        out.append(n)
    return out


# ---------- API 镜像别名 (drop-in 替换 ljqCtrl 用) ----------
click = Click
press = Press
activate = ActivateApp        # 注意: Win 版 Activate(hwnd) 收窗口句柄, Mac 版收应用名子串
GrabWindowBg = GrabWindow     # Mac screencapture 本身支持后台窗口
VK_CODE = _KEYMAP             # 名称兼容


if __name__ == '__main__':
    print('--- macljqCtrl self-check ---')
    check_permissions()
    print('cursor(logical):', _cursor_logical())
    print('windows(top5):')
    for w in ListWindows()[:5]:
        print('  ', w['id'], '|', w['app'], '|', w['title'][:30], '|', w['bbox'])
