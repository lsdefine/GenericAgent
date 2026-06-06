#!/usr/bin/env python3
"""
browser_interact.py — 基于Selenium的浏览器交互自动化
==========================================================
使用 Chromium + Selenium 实现：
  - 导航URL
  - 表单填写
  - 按钮点击
  - 截图 + OCR验证

依赖: selenium, Pillow, rapidocr-onnxruntime
用法:
  python scripts/browser_interact.py --help
  python scripts/browser_interact.py demo                  # 完整演示(百度搜索)
  python scripts/browser_interact.py demo --url <URL>      # 自定义URL
  python scripts/browser_interact.py demo --headless       # 无头模式
  python scripts/browser_interact.py --action navigate --url <URL>
  python scripts/browser_interact.py --action fill --selector '#kw' --value 'hello'
  python scripts/browser_interact.py --action click --selector '#su'
  python scripts/browser_interact.py --action screenshot --path out.png
  python scripts/browser_interact.py --action ocr --path out.png --expect '文本'
"""

import argparse, os, sys, time, json, tempfile
from pathlib import Path
from typing import Optional, List, Tuple

# ── Selenium ──
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# ── OCR ──
try:
    from rapidocr_onnxruntime import RapidOCR
    _ocr_engine = RapidOCR()
    _ocr_available = True
except ImportError:
    _ocr_engine = None
    _ocr_available = False

# ── PIL ──
from PIL import Image


SCRIPTS_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPTS_DIR.parent
TEMP_DIR = PROJECT_ROOT / "temp"
TEMP_DIR.mkdir(exist_ok=True)


class BrowserInteract:
    """基于Selenium的浏览器交互控制器"""

    def __init__(self, headless: bool = True, binary: str = "/usr/bin/chromium-browser",
                 window_size: Tuple[int, int] = (1280, 720)):
        self.driver: Optional[webdriver.Chrome] = None
        self.headless = headless
        self.binary = binary
        self.window_size = window_size

    def start(self) -> bool:
        """启动浏览器"""
        if self.driver:
            return True
        opts = Options()
        opts.binary_location = self.binary
        if self.headless:
            opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        opts.add_argument(f"--window-size={self.window_size[0]},{self.window_size[1]}")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        opts.add_experimental_option("useAutomationExtension", False)
        try:
            self.driver = webdriver.Chrome(options=opts)
            # 防反爬
            self.driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
                "source": """
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
                """
            })
            return True
        except Exception as e:
            print(f"❌ 浏览器启动失败: {e}")
            return False

    def stop(self):
        """关闭浏览器"""
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
            self.driver = None

    def navigate(self, url: str, wait_until: str = "load", timeout: float = 15) -> bool:
        """导航到URL"""
        if not self.driver:
            if not self.start():
                return False
        try:
            self.driver.get(url)
            # 等待页面加载
            wait_map = {
                "load": "return document.readyState === 'complete'",
                "dom": "return document.readyState === 'interactive' || document.readyState === 'complete'",
            }
            expr = wait_map.get(wait_until, wait_map["load"])
            WebDriverWait(self.driver, timeout).until(
                lambda d: d.execute_script(expr)
            )
            return True
        except Exception as e:
            print(f"❌ 导航失败: {url} — {e}")
            return False

    def fill(self, selector: str, value: str, timeout: float = 10, by: str = "css") -> bool:
        """填写表单字段（优先JS方案，绕过头盔模式不可交互限制）"""
        if not self.driver:
            print("❌ 浏览器未启动")
            return False
        by_map = {"css": By.CSS_SELECTOR, "xpath": By.XPATH, "id": By.ID, "name": By.NAME}
        locator = (by_map.get(by, By.CSS_SELECTOR), selector)
        # 方法1: 纯JS注入（参数化传递，避免引号破坏）
        try:
            self.driver.execute_script("""
                const el = document.querySelector(arguments[0]);
                if (!el) throw new Error('Element not found');
                el.value = arguments[1];
                el.dispatchEvent(new Event('input', {bubbles: true}));
                el.dispatchEvent(new Event('change', {bubbles: true}));
                el.dispatchEvent(new Event('blur', {bubbles: true}));
            """, selector, value)
            # 验证是否成功
            try:
                actual = self.driver.execute_script(
                    "return document.querySelector(arguments[0]).value", selector)
                if actual == value:
                    return True
            except:
                pass
            print(f"   JS注入后value可能不匹配, 尝试Selenium交互...")
        except Exception as e:
            print(f"   JS方案失败: {e}")

        # 方法2: Selenium原生交互（兜底）
        try:
            elem = WebDriverWait(self.driver, timeout).until(
                EC.element_to_be_clickable(locator)
            )
            try:
                elem.clear()
                elem.send_keys(value)
            except:
                self.driver.execute_script("arguments[0].value = arguments[1]", elem, value)
            return True
        except Exception as e:
            print(f"❌ 填写失败: selector={selector}, value={value} — {e}")
            return False

    def click(self, selector: str, timeout: float = 10, by: str = "css") -> bool:
        """点击元素（优先JS点击，避开遮挡）"""
        if not self.driver:
            print("❌ 浏览器未启动")
            return False
        by_map = {"css": By.CSS_SELECTOR, "xpath": By.XPATH, "id": By.ID, "name": By.NAME,
                  "link_text": By.LINK_TEXT, "partial_link": By.PARTIAL_LINK_TEXT}
        by_sel = by_map.get(by, By.CSS_SELECTOR)
        # 方法1: JS点击
        try:
            elem = WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((by_sel, selector))
            )
            self.driver.execute_script("arguments[0].click()", elem)
            return True
        except Exception:
            pass
        # 方法2: Selenium原生点击
        try:
            elem = WebDriverWait(self.driver, timeout).until(
                EC.element_to_be_clickable((by_sel, selector))
            )
            elem.click()
            return True
        except Exception as e:
            print(f"❌ 点击失败: selector={selector} — {e}")
            return False

    def screenshot(self, path: Optional[str] = None) -> Optional[str]:
        """截取页面截图，返回文件路径"""
        if not self.driver:
            print("❌ 浏览器未启动")
            return None
        if path is None:
            path = str(TEMP_DIR / f"screenshot_{int(time.time())}.png")
        try:
            self.driver.save_screenshot(path)
            print(f"📸 截图已保存: {path}")
            return path
        except Exception as e:
            print(f"❌ 截图失败: {e}")
            return None

    def get_page_text(self) -> str:
        """获取页面可见文本"""
        if not self.driver:
            return ""
        try:
            return self.driver.find_element(By.TAG_NAME, "body").text
        except:
            return ""

    def scroll_to(self, selector: str, by: str = "css") -> bool:
        """滚动到元素位置"""
        if not self.driver:
            return False
        by_map = {"css": By.CSS_SELECTOR, "xpath": By.XPATH, "id": By.ID}
        try:
            elem = self.driver.find_element(by_map.get(by, By.CSS_SELECTOR), selector)
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'})", elem)
            time.sleep(0.5)
            return True
        except:
            return False

    def wait(self, seconds: float):
        """等待指定秒数"""
        time.sleep(seconds)

    # ── OCR 方法 ──

    def ocr_image(self, image_path: str) -> List[dict]:
        """OCR识别图片中的文字"""
        if not _ocr_available:
            print("⚠️ RapidOCR未安装，请执行: pip install rapidocr-onnxruntime")
            return []
        try:
            result, _ = _ocr_engine(image_path)
            if not result:
                return []
            items = []
            for box, text, score in result:
                items.append({
                    "text": text,
                    "confidence": float(score),
                    "bbox": box.tolist() if hasattr(box, 'tolist') else box
                })
            return items
        except Exception as e:
            print(f"❌ OCR识别失败: {e}")
            return []

    def ocr_get_text(self, image_path: str) -> str:
        """OCR识别并返回完整文本"""
        items = self.ocr_image(image_path)
        return " ".join(item["text"] for item in items if item["confidence"] > 0.3)

    def ocr_verify(self, image_path: str, expected: str) -> bool:
        """OCR验证图片中是否包含期望文本"""
        items = self.ocr_image(image_path)
        full_text = " ".join(item["text"] for item in items if item["confidence"] > 0.3)
        found = expected.lower() in full_text.lower()
        print(f"🔍 OCR验证: 期望='{expected}' → {'✅ 找到' if found else '❌ 未找到'}")
        if not found:
            print(f"   识别文本(前200字): {full_text[:200]}")
        return found

    # ── 高阶方法 ──

    def submit_form(self, form_selector: str = "form", timeout: float = 10) -> bool:
        """提交表单"""
        by = By.CSS_SELECTOR
        try:
            form = WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((by, form_selector))
            )
            self.driver.execute_script("arguments[0].submit()", form)
            return True
        except Exception as e:
            print(f"❌ 表单提交失败: {e}")
            return False


def run_demo(headless: bool = False, url: Optional[str] = None):
    """
    完整演示: 导航 → 搜索 → 截图 → OCR验证

    默认使用百度搜索，演示整个流程。
    """
    search_url = url or "https://www.baidu.com"
    print("=" * 60)
    print("🚀 浏览器交互自动化 Demo")
    print("=" * 60)

    b = BrowserInteract(headless=headless)

    # 1. 启动浏览器
    print("\n[1/5] 启动浏览器...")
    if not b.start():
        print("❌ 启动失败")
        return False

    # 2. 导航到搜索页
    print(f"\n[2/5] 导航到: {search_url}")
    if not b.navigate(search_url):
        print("❌ 导航失败")
        b.stop()
        return False
    print(f"   页面标题: {b.driver.title[:60]}")
    b.wait(1)

    # 3. 搜索框填表 + 点击
    print("\n[3/5] 填写搜索框 + 点击搜索...")

    # 尝试多种搜索框选择器
    search_selectors = [
        ("css", "input[name='wd']"),  # 百度
        ("css", "input[name='q']"),   # Google
        ("css", "input[name='query']"), # DuckDuckGo
        ("css", "input[type='text']"),
        ("css", "input[type='search']"),
        ("css", "#searchInput"),       # Bing
    ]

    filled = False
    for by, sel in search_selectors:
        if b.fill(sel, "Python 自动化", by=by):
            print(f"   填写搜索框: {sel}")
            filled = True
            break

    if not filled:
        print("   ⚠️ 未找到搜索框，尝试页面文本输入...")
        # try JS to find any input
        try:
            b.driver.execute_script("""
                const inputs = document.querySelectorAll('input[type="text"], input[type="search"], input:not([type])');
                if(inputs.length > 0) inputs[0].value = 'Python 自动化';
            """)
            print("   通过JS注入文本")
        except:
            print("   ❌ 无法填写")
            b.stop()
            return False

    b.wait(0.5)

    # 尝试点击搜索按钮
    btn_selectors = [
        ("css", "input[type='submit']"),
        ("css", "button[type='submit']"),
        ("css", "#su"),               # 百度
        ("css", "button:has(svg)"),   # 搜索图标按钮
        ("css", "form button"),
        ("xpath", "//button[contains(text(),'搜索')]"),
        ("xpath", "//input[@value='百度一下']"),
        ("css", ".search-button"),
    ]
    clicked = False
    for by, sel in btn_selectors:
        try:
            if b.click(sel, timeout=3, by=by):
                print(f"   点击搜索按钮: {sel}")
                clicked = True
                break
        except:
            continue

    if not clicked:
        print("   ⚠️ 未找到搜索按钮，尝试Enter提交...")
        try:
            from selenium.webdriver.common.keys import Keys
            body = b.driver.find_element(By.TAG_NAME, "body")
            body.send_keys(Keys.ENTER)
            print("   通过Enter提交")
            clicked = True
        except:
            pass

    b.wait(2)  # 等待搜索结果

    # 4. 截图
    print("\n[4/5] 截图...")
    screenshot_path = b.screenshot()
    if not screenshot_path:
        b.stop()
        return False

    # 5. OCR验证
    print("\n[5/5] OCR验证...")
    page_text = b.get_page_text()
    print(f"   页面文本(前100字): {page_text[:100]}")
    
    keywords = ["Python", "自动化"]
    all_found = True
    for kw in keywords:
        found = b.ocr_verify(screenshot_path, kw)
        if not found:
            all_found = False

    print(f"\n{'=' * 40}")
    if all_found:
        print("✅ Demo完成！所有验证通过")
    else:
        print("⚠️ Demo完成，部分验证未通过（可能因页面布局）")
    print(f"   截图: {screenshot_path}")
    print(f"{'=' * 40}")

    b.stop()
    return True


def main():
    parser = argparse.ArgumentParser(description="浏览器交互自动化工具")
    parser.add_argument("--action", choices=["navigate", "fill", "click", "screenshot",
                                             "ocr", "get_text", "scroll", "demo"],
                        default="demo", help="执行动作")
    parser.add_argument("--url", help="目标URL")
    parser.add_argument("--selector", help="CSS选择器")
    parser.add_argument("--value", help="填写值")
    parser.add_argument("--path", help="文件路径")
    parser.add_argument("--expect", help="OCR期望文本")
    parser.add_argument("--by", default="css", choices=["css", "xpath", "id", "name",
                                                         "link_text", "partial_link"])
    parser.add_argument("--headless", action="store_true", help="无头模式")

    args, extra = parser.parse_known_args()

    if args.action == "demo" or len(sys.argv) == 1:
        run_demo(headless=args.headless, url=args.url)
        return

    b = BrowserInteract(headless=args.headless)
    if not b.start():
        return

    if args.action == "navigate":
        if not args.url:
            print("❌ --url 必须提供")
            return
        b.navigate(args.url)
        print(f"标题: {b.driver.title[:80]}")
    elif args.action == "fill":
        if not args.selector or not args.value:
            print("❌ --selector 和 --value 必须提供")
            return
        b.fill(args.selector, args.value, by=args.by)
    elif args.action == "click":
        if not args.selector:
            print("❌ --selector 必须提供")
            return
        b.click(args.selector, by=args.by)
    elif args.action == "screenshot":
        path = b.screenshot(args.path)
    elif args.action == "ocr":
        path = args.path or str(TEMP_DIR / "screenshot_latest.png")
        if not os.path.exists(path):
            print(f"❌ 文件不存在: {path}")
            return
        if args.expect:
            b.ocr_verify(path, args.expect)
        else:
            text = b.ocr_get_text(path)
            print(f"OCR识别文本:\n{text[:500]}")
    elif args.action == "get_text":
        text = b.get_page_text()
        print(f"页面文本:\n{text[:500]}")
    elif args.action == "scroll":
        if not args.selector:
            print("❌ --selector 必须提供")
            return
        b.scroll_to(args.selector, by=args.by)

    b.stop()


if __name__ == "__main__":
    main()
