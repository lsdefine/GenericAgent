#!/usr/bin/env python3
"""
vision_agent.py - 统一视觉接口 (vision_sop 实战化)
====================================================
整合 Xvfb 截图 + OCR + UI 检测 + 视觉问答 + 鼠标键盘交互 为统一接口.

能力:
  1. 窗口枚举与定位 (xdotool)
  2. 截图 (全屏/窗口/区域)
  3. OCR 文字提取 (rapidocr-onnxruntime)
  4. UI 元素检测 (YOLO + OCR)
  5. 视觉问答 (vision_api, 若有配置)
  6. 文本定位 (find_text)
  7. 鼠标点击 (坐标 / 文字定位)
  8. 键盘输入 (文字 / 特殊键)

CLI 用法:
  vision_agent.py list                            # 枚举窗口
  vision_agent.py screenshot [--window TITLE] [--save path]
  vision_agent.py ocr [--window TITLE] [--save path]
  vision_agent.py detect [--window TITLE] [--mode crop|match]
  vision_agent.py find TEXT [--window TITLE]
  vision_agent.py ask "prompt" [--window TITLE]
  vision_agent.py click --x 100 --y 200            # 坐标点击
  vision_agent.py click --text "搜索" --window T  # OCR定位点击
  vision_agent.py type "hello"                     # 输入文字
  vision_agent.py key Return                       # 按特殊键
  vision_agent.py interact --text "搜索" --input "Sessions" --key Return
  vision_agent.py pipeline [--window TITLE] [--all]

Python API:
  from scripts.vision_agent import VisionAgent
  va = VisionAgent()
  va.list_windows()
  va.screenshot(window_title="...")
  va.ocr(image)
  va.detect(image)
  va.find_text(image, "text")
  va.ask(image, "prompt")
  va.click(x, y)
  va.click_by_text("text")
  va.type_text("text")
  va.press_key("Return")
  va.interact_pipeline(...)
"""
import os, sys, subprocess, json, re, argparse, time
from pathlib import Path
from PIL import Image, ImageGrab
from io import BytesIO
import base64

# ── 路径 ──────────────────────────────────────────────
SCRIPTS_DIR = Path(__file__).resolve().parent
MEMORY_DIR = SCRIPTS_DIR.parent / 'memory'
sys.path.insert(0, str(MEMORY_DIR))

DISPLAY = os.environ.get('DISPLAY') or ':99'


# ═══════════════════════════════════════════════════════
#  VisionAgent class
# ═══════════════════════════════════════════════════════

class VisionAgent:
    """统一视觉代理:截图 + OCR + UI检测 + 视觉问答 + 鼠标键盘交互"""

    def __init__(self, display=DISPLAY):
        self.display = display
        self._ocr_engine = None

    # ── 窗口工具 ──────────────────────────────────────

    def list_windows(self):
        """枚举 X11 窗口标题"""
        try:
            result = subprocess.run(
                ['xdotool', 'search', '.'],
                capture_output=True, text=True, timeout=5,
                env={**os.environ, 'DISPLAY': self.display}
            )
            if result.returncode != 0:
                return []
            ids = [int(w) for w in result.stdout.strip().split() if w.strip()]
            titles = []
            for wid in ids:
                name = subprocess.run(
                    ['xdotool', 'getwindowname', str(wid)],
                    capture_output=True, text=True, timeout=3,
                    env={**os.environ, 'DISPLAY': self.display}
                ).stdout.strip()
                if name:
                    geo = self._get_window_geo(wid)
                    titles.append({'id': wid, 'title': name, 'geometry': geo})
            seen = set()
            uniq = []
            for w in titles:
                if w['title'] not in seen:
                    seen.add(w['title'])
                    uniq.append(w)
            return uniq
        except Exception as e:
            return [{'error': str(e)}]

    def _get_window_geo(self, wid):
        """获取窗口几何信息"""
        try:
            geo = subprocess.run(
                ['xdotool', 'getwindowgeometry', str(wid)],
                capture_output=True, text=True, timeout=3,
                env={**os.environ, 'DISPLAY': self.display}
            ).stdout
            pos_match = re.search(r'Position:\s*(-?\d+),(-?\d+)', geo)
            size_match = re.search(r'Geometry:\s*(\d+)x(\d+)', geo)
            if pos_match and size_match:
                return {
                    'x': int(pos_match.group(1)),
                    'y': int(pos_match.group(2)),
                    'width': int(size_match.group(1)),
                    'height': int(size_match.group(2))
                }
            return None
        except Exception:
            return None

    def find_window(self, title_keyword):
        """按标题关键字找窗口(面积最大匹配优先)"""
        wins = self.list_windows()
        matches = []
        for w in wins:
            if title_keyword.lower() in w['title'].lower():
                geo = w.get('geometry')
                area = 0
                if geo:
                    area = geo.get('width', 0) * geo.get('height', 0)
                matches.append((area, w))
        if matches:
            matches.sort(key=lambda x: -x[0])
            return matches[0][1]
        return None

    # ── 截图 ──────────────────────────────────────────

    def screenshot(self, window_title=None, region=None, save_path=None):
        """
        截图: 全屏 / 窗口 / 区域
        :param window_title: 窗口标题关键字
        :param region: (x, y, w, h) 或 (left, top, right, bottom)
        :param save_path: 保存路径
        :return: PIL Image
        """
        if window_title:
            win = self.find_window(window_title)
            if not win:
                raise ValueError(f"找不到窗口: {window_title}")
            geo = win.get('geometry')
            if not geo:
                raise ValueError(f"窗口 {window_title} 无几何信息")
            bbox = (geo['x'], geo['y'], geo['x'] + geo['width'], geo['y'] + geo['height'])
        elif region:
            if len(region) == 4:
                if region[2] < 100 and region[3] < 100:
                    bbox = region
                else:
                    bbox = (region[0], region[1], region[0] + region[2], region[1] + region[3])
            else:
                raise ValueError("region 需为 (x,y,w,h) 或 (left,top,right,bottom)")
        else:
            bbox = None

        old_display = os.environ.get('DISPLAY')
        os.environ['DISPLAY'] = self.display
        try:
            img = ImageGrab.grab(bbox=bbox)
        finally:
            if old_display:
                os.environ['DISPLAY'] = old_display
            else:
                del os.environ['DISPLAY']

        if save_path:
            img.save(save_path)
            print(f"\U0001f4f8 截图保存: {save_path}")
        return img

    # ── OCR ────────────────────────────────────────────

    def _get_ocr(self):
        if self._ocr_engine is None:
            from ocr_utils import ocr_image
            self._ocr_engine = ocr_image
        return self._ocr_engine

    def ocr(self, image, enhance=False):
        """
        对图片进行 OCR
        :param image: PIL Image 或 路径(str)
        :param enhance: 是否预处理增强
        :return: dict {text, lines, details}
        """
        ocr_fn = self._get_ocr()
        return ocr_fn(image, enhance=enhance)

    def ocr_window(self, window_title, enhance=False):
        """截图窗口并 OCR"""
        img = self.screenshot(window_title=window_title)
        return self.ocr(img, enhance=enhance)

    # ── UI 检测 ──────────────────────────────────────

    def detect(self, image, mode='crop', conf=0.25):
        """对图片进行 UI 元素检测"""
        try:
            from ui_detect import ui_detect
            return ui_detect(image, mode=mode, conf=conf)
        except ImportError:
            return {'error': 'ui_detect 模块不可用'}

    # ── 文本定位 ──────────────────────────────────────

    def find_text(self, image, target_text, threshold=0.5):
        """
        在图片中定位文本位置
        :param image: PIL Image 或路径
        :param target_text: 目标文本
        :param threshold: 模糊匹配阈值 (0~1)
        :return: list[dict {text, box, match_ratio}]
        """
        ocr_result = self.ocr(image)
        matches = []
        for d in ocr_result.get('details', []):
            if target_text.lower() in d.get('text', '').lower():
                matches.append(d)
            else:
                from difflib import SequenceMatcher
                ratio = SequenceMatcher(None, target_text.lower(), d.get('text', '').lower()).ratio()
                if ratio >= threshold:
                    matches.append({**d, 'match_ratio': ratio})
        return matches

    # ── 鼠标/键盘交互 ────────────────────────────────

    def click(self, x=None, y=None, window_title=None, button=1):
        """
        鼠标点击(坐标或当前焦点)
        :param x: x 坐标 (绝对坐标)
        :param y: y 坐标
        :param window_title: 若提供, 先激活窗口
        :param button: 1=左键, 2=中键, 3=右键
        :return: bool
        """
        try:
            if window_title:
                win = self.find_window(window_title)
                if win:
                    subprocess.run(
                        ['xdotool', 'windowactivate', str(win['id'])],
                        capture_output=True, timeout=3,
                        env={**os.environ, 'DISPLAY': self.display}
                    )
                    time.sleep(0.2)
            if x is not None and y is not None:
                subprocess.run(
                    ['xdotool', 'mousemove', '--sync', str(x), str(y), 'click', str(button)],
                    capture_output=True, timeout=5,
                    env={**os.environ, 'DISPLAY': self.display}
                )
            else:
                subprocess.run(
                    ['xdotool', 'click', str(button)],
                    capture_output=True, timeout=5,
                    env={**os.environ, 'DISPLAY': self.display}
                )
            return True
        except Exception as e:
            print(f"点击失败: {e}")
            return False

    def click_by_text(self, target_text, window_title=None, click_offset=(0, 0), button=1):
        """
        通过 OCR 定位文本并点击
        :param target_text: 目标文本
        :param window_title: 窗口标题关键字
        :param click_offset: (dx, dy) 额外偏移
        :param button: 鼠标按钮
        :return: dict {success, x, y, text}
        """
        if window_title:
            img = self.screenshot(window_title=window_title)
        else:
            img = self.screenshot()

        matches = self.find_text(img, target_text)
        if not matches:
            print(f"未找到文本: {target_text}")
            return {'success': False, 'text': target_text, 'reason': 'not_found'}

        # 取第一个匹配的中心点
        m = matches[0]
        box = m.get('box', m.get('coordinates', None))
        if box and len(box) >= 4:
            xs = [box[i] for i in range(0, len(box), 2)]
            ys = [box[i+1] for i in range(0, len(box), 2)]
            cx = int(sum(xs) / len(xs)) + click_offset[0]
            cy = int(sum(ys) / len(ys)) + click_offset[1]
        else:
            cx, cy = click_offset

        ok = self.click(cx, cy, button=button)
        return {'success': ok, 'x': cx, 'y': cy, 'text': target_text}

    def type_text(self, text):
        """
        在当前焦点输入文字
        :param text: 要输入的文字
        """
        try:
            subprocess.run(
                ['xdotool', 'type', '--delay', '30', text],
                capture_output=True, timeout=10,
                env={**os.environ, 'DISPLAY': self.display}
            )
            return True
        except Exception as e:
            print(f"输入失败: {e}")
            return False

    def press_key(self, key):
        """
        按特殊键
        :param key: 键名 (Return, Tab, Escape, BackSpace, ...)
        """
        try:
            subprocess.run(
                ['xdotool', 'key', key],
                capture_output=True, timeout=5,
                env={**os.environ, 'DISPLAY': self.display}
            )
            return True
        except Exception as e:
            print(f"按键失败: {e}")
            return False

    def interact_pipeline(self, window_title=None, click_text=None, type_input=None, press_key=None):
        """
        完整交互管线: 截图 → OCR定位 → 点击 → 输入 → 按键 → 再次截图验证
        :param window_title: 窗口标题关键字
        :param click_text: 要点击的文字
        :param type_input: 要输入的文字
        :param press_key: 要按的键
        :return: dict {before_ocr, click, type, key, after_ocr, after_image}
        """
        result = {}
        # 操作前截图
        before_img = self.screenshot(window_title=window_title)
        result['before_ocr'] = self.ocr(before_img)
        result['before_image'] = before_img

        if click_text:
            result['click'] = self.click_by_text(click_text, window_title=window_title)
            time.sleep(0.5)

        if type_input:
            result['type'] = self.type_text(type_input)
            time.sleep(0.3)

        if press_key:
            result['key'] = self.press_key(press_key)
            time.sleep(0.5)

        # 操作后截图
        after_img = self.screenshot(window_title=window_title)
        result['after_ocr'] = self.ocr(after_img)
        result['after_image'] = after_img
        return result

    # ── 管线 ──────────────────────────────────────────

    def pipeline(self, window_title=None, do_ocr=True, do_detect=False, do_ask=False, ask_prompt=None,
                 do_click=False, click_text=None, click_x=None, click_y=None,
                 do_type=False, type_text=None,
                 do_key=False, key_name=None,
                 do_interact=False, interact_text=None, interact_input=None, interact_key=None):
        """
        全功能管线: 截图 + OCR + 检测 + 视觉问答 + 交互
        """
        result = {}
        img = self.screenshot(window_title=window_title)
        result['image_size'] = img.size

        if do_ocr:
            result['ocr'] = self.ocr(img)
        if do_detect:
            result['detect'] = self.detect(img)
        if do_ask:
            result['ask'] = self.ask(img, ask_prompt)

        # 交互
        if do_interact:
            result['interact'] = self.interact_pipeline(
                window_title=window_title,
                click_text=interact_text,
                type_input=interact_input,
                press_key=interact_key
            )
        elif do_click and click_text:
            result['click'] = self.click_by_text(click_text, window_title=window_title)
        elif do_click and click_x is not None and click_y is not None:
            result['click'] = self.click(click_x, click_y, window_title=window_title)
        if do_type and type_text:
            result['type'] = self.type_text(type_text)
        if do_key and key_name:
            result['key'] = self.press_key(key_name)

        return result

    # ── 视觉问答 ──────────────────────────────────────

    def ask(self, image, prompt="描述图片内容", backend=None):
        try:
            from vision_api import ask_vision
        except ImportError:
            template = MEMORY_DIR / 'vision_api.template.py'
            target = MEMORY_DIR / 'vision_api.py'
            if template.exists() and not target.exists():
                import shutil
                shutil.copy(str(template), str(target))
                from vision_api import ask_vision
            else:
                return {"error": "vision_api 不可用", "template_exists": template.exists()}
        return ask_vision(image, prompt, backend=backend)


# ═══════════════════════════════════════════════════════
#  CLI entry
# ═══════════════════════════════════════════════════════

def build_parser():
    p = argparse.ArgumentParser(description="VisionAgent - 统一视觉接口")
    p.add_argument('action', nargs='?', default='screenshot',
                   choices=['list', 'screenshot', 'ocr', 'detect', 'find', 'ask',
                            'click', 'type', 'key', 'interact', 'pipeline'],
                   help='操作')
    p.add_argument('--window', '-w', default=None, help='窗口标题关键字')
    p.add_argument('--save', '-s', default=None, help='保存路径')
    p.add_argument('--enhance', action='store_true', help='OCR 增强预处理')
    p.add_argument('--mode', choices=['crop', 'match'], default='crop', help='检测模式')
    p.add_argument('--conf', type=float, default=0.25, help='YOLO 置信度阈')
    p.add_argument('--all', action='store_true', help='pipeline 执行全部')
    p.add_argument('--display', default=DISPLAY, help='X display')
    # click args
    p.add_argument('--x', type=int, default=None, help='click x 坐标')
    p.add_argument('--y', type=int, default=None, help='click y 坐标')
    p.add_argument('--text', default=None, help='OCR 目标文本')
    p.add_argument('--input', default=None, help='type 输入文本')
    p.add_argument('--key', default=None, help='key 按键名称')
    p.add_argument('--offset-x', type=int, default=0, help='click 偏移 x')
    p.add_argument('--offset-y', type=int, default=0, help='click 偏移 y')
    p.add_argument('--json', action='store_true', help='JSON 输出')
    return p


def main():
    parser = build_parser()
    args = parser.parse_args()

    os.environ['DISPLAY'] = args.display or DISPLAY

    va = VisionAgent(display=args.display)

    try:
        if args.action == 'list':
            wins = va.list_windows()
            print(f"窗口 ({len(wins)}):")
            for w in wins:
                geo = w.get('geometry', {})
                g_str = f" [{geo.get('x',0)},{geo.get('y',0)} {geo.get('width',0)}x{geo.get('height',0)}]" if geo else ""
                print(f"  [{w['id']}] {w['title']}{g_str}")

        elif args.action == 'screenshot':
            img = va.screenshot(window_title=args.window, save_path=args.save)
            print(f"截图: {img.size}")

        elif args.action == 'ocr':
            if args.window:
                result = va.ocr_window(args.window, enhance=args.enhance)
            else:
                img = va.screenshot()
                result = va.ocr(img, enhance=args.enhance)
            text = result.get('text', '')
            print(f"OCR ({len(result.get('details',[]))} blocks):")
            print(text if text else '(empty)')
            if args.json:
                print(json.dumps(result, ensure_ascii=False, default=str, indent=2))

        elif args.action == 'detect':
            img = va.screenshot(window_title=args.window)
            result = va.detect(img, mode=args.mode, conf=args.conf)
            print(json.dumps(result, ensure_ascii=False, default=str, indent=2))

        elif args.action == 'find':
            img = va.screenshot(window_title=args.window)
            target = args.text or args.input or ''
            if not target:
                parser.error("find 需要 --text 参数")
            matches = va.find_text(img, target)
            if matches:
                print(f"找到 {len(matches)} 处 '{target}':")
                for m in matches[:5]:
                    print(f"  '{m.get('text','')}' @ {m.get('box',m.get('coordinates',''))}")
            else:
                print(f"未找到 '{target}'")

        elif args.action == 'ask':
            prompt = args.text or args.input or "描述图片内容"
            img = va.screenshot(window_title=args.window)
            result = va.ask(img, prompt)
            print(result)

        elif args.action == 'click':
            if args.text:
                result = va.click_by_text(args.text, window_title=args.window,
                                          click_offset=(args.offset_x, args.offset_y))
                status = "✅" if result.get('success') else "❌"
                print(f"{status} 点击文本 '{result.get('text','')}' @ ({result.get('x','?')},{result.get('y','?')})")
            elif args.x is not None and args.y is not None:
                ok = va.click(args.x, args.y, window_title=args.window)
                print(f"{'✅' if ok else '❌'} 点击坐标 ({args.x},{args.y})")
            else:
                parser.error("click 需要 --text 或 --x --y")

        elif args.action == 'type':
            text = args.input or args.text or ''
            if not text:
                parser.error("type 需要 --input 或 --text")
            va.type_text(text)
            print(f"键入: {text}")

        elif args.action == 'key':
            key = args.key or ''
            if not key:
                parser.error("key 需要 --key 参数")
            va.press_key(key)
            print(f"按键: {key}")

        elif args.action == 'interact':
            result = va.interact_pipeline(
                window_title=args.window,
                click_text=args.text,
                type_input=args.input,
                press_key=args.key
            )
            text_before = result.get('before_ocr', {}).get('text', '')[:100]
            text_after = result.get('after_ocr', {}).get('text', '')[:100]
            print(f"交互管线:")
            print(f"  操作前: {text_before}")
            if 'click' in result:
                c = result['click']
                print(f"  点击: {'✅' if c.get('success') else '❌'} '{c.get('text','')}'")
            if 'type' in result:
                print(f"  输入: ✅")
            if 'key' in result:
                print(f"  按键: ✅")
            print(f"  操作后: {text_after}")

        elif args.action == 'pipeline':
            result = va.pipeline(
                window_title=args.window,
                do_ocr=True,
                do_detect=args.mode != 'crop',
                do_ask=bool(args.text),
                ask_prompt=args.text,
                do_interact=args.all
            )
            if args.json:
                print(json.dumps(result, ensure_ascii=False, default=str, indent=2))
            else:
                print(f"\U0001f4ca Pipeline:")
                print(f"  Size: {result.get('image_size')}")
                if 'ocr' in result:
                    t = result['ocr'].get('text','')
                    print(f"  OCR: {t[:100] if t else '(empty)'}")
                if 'detect' in result:
                    print(f"  Detect: {len([e for e in result['detect'] if 'error' not in e])} elements")
                if 'ask' in result:
                    print(f"  Ask: {result['ask'][:200]}")
                if 'click' in result:
                    c = result['click']
                    ok_mark = chr(0x1f7e9) if c.get('success') else chr(0x274c)
                    print(f"  Click: {ok_mark} {c.get('text','')} @ ({c.get('x','?')},{c.get('y','?')})")
                if 'type' in result:
                    print(f"  Type: {result['type'][:50]}")
                if 'after_ocr' in result:
                    t = result['after_ocr'].get('text','')
                    print(f"  After OCR: {t[:100] if t else '(empty)'}")

    except Exception as e:
        print(f"{chr(0x274c)} 错误: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
