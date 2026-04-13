"""
CRITICAL: 严禁在此工具链中 import pyautogui (会污染 win32api 导致逻辑冲突)。
ljqCtrl Quick Reference:
- dpi_scale: float (Logical = Physical * dpi_scale)
- Click(x, y): Use Physical Coordinates (from screenshots)
- SetCursorPos(z): Use Physical Coordinates z=(x, y)
- Press(cmd, staytime=0): Keyboard shortcuts (e.g. 'ctrl+v')
- FindBlock(fn, wrect=None, threshold=0.8) -> (obj_center_phys, is_found)
- MouseDClick(staytime=0.05), MouseClick(staytime=0.05)
- GrabWindow(hwnd) -> PIL Image: DPI-safe window screenshot
"""

import os, sys, time, random, math, win32api, win32con, ctypes
import numpy as np

dpi_scale = 1
try:
	from PIL import ImageGrab, Image, ImageEnhance, ImageFilter, ImageDraw
	import cv2
except: pass

_hdc = ctypes.windll.user32.GetDC(0)
swidth = ctypes.windll.gdi32.GetDeviceCaps(_hdc, 118)   # DESKTOPHORZRES (物理)
sheight = ctypes.windll.gdi32.GetDeviceCaps(_hdc, 117)   # DESKTOPVERTRES
ctypes.windll.user32.ReleaseDC(0, _hdc)
cwidth = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)  # 逻辑
cheight = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
dpi_scale = cwidth / swidth
print('Screen width & height:', swidth, sheight)
print('dpi_scale:', dpi_scale)

def MouseDown(): win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN,0,0) 
def MouseUp(): win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP,0,0)

def MouseClick(staytime=0.05):
	MouseDown(); time.sleep(staytime)
	MouseUp(); time.sleep(0.05)

def MouseDClick(staytime=0.05):
	MouseDown(); MouseUp() 
	MouseDown(); MouseUp() 
	time.sleep(0.05)

def SetCursorPos(z):
	z = tuple(map(lambda v:int(v*dpi_scale), z))
	win32api.SetCursorPos(z)
	time.sleep(0.05) 

def Click(x, y=None):
	if type(x) is type(tuple()): x, y = int(x[0]), int(x[1])
	SetCursorPos( (x, y) )
	MouseClick()
click = Click
	
def Press(cmd, staytime=0):
	if type(cmd) is list: cmds = [x.lower() for x in cmd]
	else: cmds = cmd.lower().split('+')
	for z in cmds: 
		win32api.keybd_event(VK_CODE[z], 0, 0, 0)
		time.sleep(staytime)
	for z in reversed(cmds):
		time.sleep(staytime)
		win32api.keybd_event(VK_CODE[z], 0, win32con.KEYEVENTF_KEYUP, 0)
press = Press

VK_CODE = {'backspace':0x08, 'tab':0x09, 'clear':0x0C, 'enter':0x0D, 'shift':0x10, 'ctrl':0x11, 'alt':0x12, 'pause':0x13, 'caps_lock':0x14, 'esc':0x1B, 'escape':0x1B, 'space':0x20, 'page_up':0x21, 'page_down':0x22, 'end':0x23, 'home':0x24, 'left_arrow':0x25, 'up_arrow':0x26, 'right_arrow':0x27, 'down_arrow':0x28, 'select':0x29, 'print':0x2A, 'execute':0x2B, 'print_screen':0x2C, 'ins':0x2D, 'del':0x2E, 'help':0x2F, '0':0x30, '1':0x31, '2':0x32, '3':0x33, '4':0x34, '5':0x35, '6':0x36, '7':0x37, '8':0x38, '9':0x39, 'a':0x41, 'b':0x42, 'c':0x43, 'd':0x44, 'e':0x45, 'f':0x46, 'g':0x47, 'h':0x48, 'i':0x49, 'j':0x4A, 'k':0x4B, 'l':0x4C, 'm':0x4D, 'n':0x4E, 'o':0x4F, 'p':0x50, 'q':0x51, 'r':0x52, 's':0x53, 't':0x54, 'u':0x55, 'v':0x56, 'w':0x57, 'x':0x58, 'y':0x59, 'z':0x5A, 'numpad_0':0x60, 'numpad_1':0x61, 'numpad_2':0x62, 'numpad_3':0x63, 'numpad_4':0x64, 'numpad_5':0x65, 'numpad_6':0x66, 'numpad_7':0x67, 'numpad_8':0x68, 'numpad_9':0x69, 'multiply_key':0x6A, 'add_key':0x6B, 'separator_key':0x6C, 'subtract_key':0x6D, 'decimal_key':0x6E, 'divide_key':0x6F, 'F1':0x70, 'F2':0x71, 'F3':0x72, 'F4':0x73, 'F5':0x74, 'F6':0x75, 'F7':0x76, 'F8':0x77, 'F9':0x78, 'F10':0x79, 'F11':0x7A, 'F12':0x7B, 'F13':0x7C, 'F14':0x7D, 'F15':0x7E, 'F16':0x7F, 'F17':0x80, 'F18':0x81, 'F19':0x82, 'F20':0x83, 'F21':0x84, 'F22':0x85, 'F23':0x86, 'F24':0x87, 'num_lock':0x90, 'scroll_lock':0x91, 'left_shift':0xA0, 'right_shift ':0xA1, 'left_control':0xA2, 'right_control':0xA3, 'left_menu':0xA4, 'right_menu':0xA5, 'browser_back':0xA6, 'browser_forward':0xA7, 'browser_refresh':0xA8, 'browser_stop':0xA9, 'browser_search':0xAA, 'browser_favorites':0xAB, 'browser_start_and_home':0xAC, 'volume_mute':0xAD, 'volume_Down':0xAE, 'volume_up':0xAF, 'next_track':0xB0, 'previous_track':0xB1, 'stop_media':0xB2, 'play/pause_media':0xB3, 'start_mail':0xB4, 'select_media':0xB5, 'start_application_1':0xB6, 'start_application_2':0xB7, 'attn_key':0xF6, 'crsel_key':0xF7, 'exsel_key':0xF8, 'play_key':0xFA, 'zoom_key':0xFB, 'clear_key':0xFE, '+':0xBB, ',':0xBC, '-':0xBD, '.':0xBE, '/':0xBF, '`':0xC0, ';':0xBA, '[':0xDB, '\\':0xDC, ']':0xDD, "'":0xDE, '`':0xC0} 
VK_CODE = {k.lower():v for k,v in VK_CODE.items()}

def GrabWindow(hwnd):
	import win32gui; win32gui.SetForegroundWindow(hwnd); time.sleep(0.3)
	bbox = tuple(int(v / dpi_scale) for v in win32gui.GetWindowRect(hwnd))
	return ImageGrab.grab(bbox)

def imshow(mt, sec=0):
	cv2.imshow('cc', mt)
	cv2.waitKey(sec)
	
def GetWRect(sr):
	num = int(sr[-1])
	l, u, r, b = 0, 0, swidth, sheight
	if 'left' in sr: r = swidth // num
	if 'right' in sr: l = swidth * (num-1) // num 
	if 'top' in sr: b = sheight // num
	if 'bottom' in sr: u = sheight * (num-1) // num
	return [l, u, r, b]

def FindBlock(fn, wrect=None, verbose=0, threshold=0.8):
	tic = time.process_time()
	if wrect is not None and isinstance(wrect, Image.Image): 
		scr, wrect = wrect, None
	else:
		if isinstance(wrect, str): wrect = GetWRect(wrect)
		scr = ImageGrab.grab(wrect)
	blc = Image.open(fn) if isinstance(fn, str) else fn
	T = cv2.cvtColor(np.array(blc), cv2.COLOR_RGB2BGR)
	B = cv2.cvtColor(np.array(scr), cv2.COLOR_RGB2BGR)
	tsh, tsw = T.shape[:2]
	if verbose: print('T.shape:', T.shape, '\t', 'B.shape:', B.shape)
	res = cv2.matchTemplate(B, T, cv2.TM_CCOEFF_NORMED)
	min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
	oj, oi = max_loc
	if wrect is None: wrect = [0, 0, scr.size[0], scr.size[1]]
	obj = (oj + wrect[0] + tsw//2, oi + wrect[1] + tsh//2)
	if verbose:
		print(f'Max match: {max_val:.4f} at ({oj}, {oi}) cost: {time.process_time() - tic:.3f}s')
		sscr = scr.crop([oj, oi, oj+tsw, oi+tsh])
		sscr.show()
	return obj, max_val > threshold

if __name__ == '__main__':
	#time.sleep(3)
	#SetCursorPos( (1640, 131) )
	#MouseClick()
	#print(FindBlock('z:/z.png', [1638, 214, 5838, 414], verbose=1))
	print('completed %.3f' % time.process_time())