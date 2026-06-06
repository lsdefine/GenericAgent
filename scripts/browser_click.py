#!/usr/bin/env python3
"""
browser_click.py — 浏览器视觉闭环: 截图→OCR定位→模拟点击→验证
================================================================
基于 BrowserInteract (browser_interact.py) 的视觉点击闭环工具。

核心能力:
  1. click_by_text(text) — 在页面上找到文字并点击
  2. wait_for_text(text, timeout) — 等待文字出现
  3. click_verify_loop(text, timeout) — 不断检查直到文字出现/消失
  4. health_dashboard_demo() — health_dashboard 演示

依赖: scripts/browser_interact.py, rapidocr-onnxruntime, Pillow, selenium
"""

import argparse, os, sys, time, json
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPTS_DIR.parent
sys.path.insert(0, str(SCRIPTS_DIR))

from browser_interact import BrowserInteract


class BrowserClick(BrowserInteract):
    """扩展 BrowserInteract，添加视觉点击闭环能力"""

    def find_text_coordinates(self, image_path: str, target_text: str, min_conf: float = 0.3):
        """
        在截图中搜索目标文字，返回包含该文字的 bbox 中心坐标。
        返回: [(cx, cy, text, conf), ...] 按置信度降序
        """
        items = self.ocr_image(image_path)
        if not items:
            return []

        matches = []
        for item in items:
            if target_text.lower() in item["text"].lower() and item["confidence"] >= min_conf:
                bbox = item["bbox"]  # [[x1,y1],[x2,y1],[x2,y2],[x1,y2]]
                xs = [p[0] for p in bbox]
                ys = [p[1] for p in bbox]
                cx = sum(xs) / len(xs)
                cy = sum(ys) / len(ys)
                matches.append((int(cx), int(cy), item["text"], item["confidence"]))

        matches.sort(key=lambda x: -x[3])  # 按置信度降序
        return matches

    def click_by_text(self, target_text: str, click_offset: tuple = (0, 0),
                      timeout: float = 10, check_interval: float = 1.0) -> bool:
        """
        核心方法: 截图 → OCR定位 → 计算坐标 → JS点击 → 验证

        流程:
          1. 截图当前页面
          2. OCR识别寻找 target_text
          3. 找到后计算元素中心坐标
          4. 用 JS click 点击该位置
          5. 可选: 重新截图验证文字是否变化

        返回: True 如果成功找到并点击
        """
        deadline = time.time() + timeout
        attempt = 0
        while time.time() < deadline:
            attempt += 1
            print(f"  [{attempt}] 截图搜索 \"{target_text}\"...")
            path = self.screenshot()
            if not path:
                time.sleep(check_interval)
                continue

            matches = self.find_text_coordinates(path, target_text)
            if matches:
                cx, cy, found_text, conf = matches[0]
                print(f"  ✅ 找到文字 \"{found_text}\" (conf={conf:.2f}) at ({cx}, {cy})")

                # 尝试用JS点击该坐标处元素
                try:
                    clicked = self.driver.execute_script("""
                        const x = arguments[0], y = arguments[1];
                        const el = document.elementFromPoint(x, y);
                        if (el) {
                            el.click();
                            return true;
                        }
                        return false;
                    """, cx, cy)
                    if clicked:
                        print(f"  ✅ JS点击 (x={cx}, y={cy})")
                        return True
                except Exception as e:
                    print(f"  ⚠️ JS点击失败: {e}")

                # 兜底: 用Selenium ActionChains
                try:
                    from selenium.webdriver.common.action_chains import ActionChains
                    from selenium.webdriver.common.actions.interaction import KEY_OR_KEY_CODE
                    body = self.driver.find_element("tag name", "body")
                    actions = ActionChains(self.driver)
                    actions.move_to_element_with_offset(body, cx, cy - body.location['y']).click().perform()
                    print(f"  ✅ ActionChains点击 (x={cx}, y={cy})")
                    return True
                except Exception as e:
                    print(f"  ⚠️ ActionChains失败: {e}")

                print(f"  ❌ 点击执行失败")
                return False

            # 等待后重试
            print(f"  未找到 \"{target_text}\", 等待{check_interval}s...")
            time.sleep(check_interval)

        print(f"  ❌ 超时: {timeout}s内未找到 \"{target_text}\"")
        return False

    def wait_for_text(self, target_text: str, timeout: float = 10,
                      check_interval: float = 1.0, disappear: bool = False) -> bool:
        """
        等待页面文字出现(或消失)。
        disappear=True 则等待文字消失
        """
        deadline = time.time() + timeout
        attempt = 0
        while time.time() < deadline:
            attempt += 1
            path = self.screenshot()
            if not path:
                time.sleep(check_interval)
                continue

            items = self.ocr_image(path)
            found = any(target_text.lower() in item["text"].lower()
                       for item in items if item["confidence"] > 0.3)

            if disappear and not found:
                print(f"  ✅ \"{target_text}\" 已消失")
                return True
            elif not disappear and found:
                print(f"  ✅ \"{target_text}\" 已出现")
                return True

            status = "仍在" if found else "未出现"
            print(f"  [{attempt}] \"{target_text}\" {status}，等待...")
            time.sleep(check_interval)

        print(f"  ❌ 超时: {timeout}s")
        return False

    def click_verify_loop(self, target_text: str, verify_text: str = None,
                          timeout: float = 15) -> dict:
        """
        完整闭环: 点击 → 验证 → 报告

        流程:
          1. 截取当前页面截图
          2. OCR找到target_text并点击
          3. 点击后截图验证verify_text是否出现(或target_text是否消失)

        返回: {"success": bool, "step": str, "detail": str}
        """
        print(f"\n{'=' * 50}")
        print(f"🖱️  点击闭环: 找 \"{target_text}\" → 点击 → 验证")
        print(f"{'=' * 50}")

        # Step 1: 截图+OCR定位+点击
        clicked = self.click_by_text(target_text, timeout=timeout)
        if not clicked:
            return {"success": False, "step": "click", "detail": f"未找到或点击失败: {target_text}"}

        time.sleep(1)  # 等待页面响应

        # Step 2: 验证
        verify = verify_text or target_text
        verified = self.wait_for_text(verify, timeout=5, disappear=(verify_text is None))

        # Step 3: 报告
        if verified:
            print(f"  ✅ 闭环完成: 点击 \"{target_text}\" → 验证通过")
            return {"success": True, "step": "verify", "detail": f"点击+验证成功"}
        else:
            print(f"  ⚠️ 点击已执行但验证未通过(可能页面还未更新)")
            return {"success": True, "step": "click_only", "detail": f"已点击但验证超时"}


def health_dashboard_demo(url: str = None, headless: bool = False):
    """
    演示: 打开health_dashboard → 截图 → OCR验证关键数据

    流程:
      1. 启动浏览器
      2. 导航到health_dashboard URL
      3. 截图并OCR提取数据面板内容
      4. 识别关键指标(CPU/内存/磁盘)
      5. 验证页面正常加载
    """
    from browser_interact import run_demo

    default_url = url or "http://localhost:9090"  # health_dashboard默认端口
    bc = BrowserClick(headless=headless)

    print("=" * 60)
    print("🏥 health_dashboard 视觉闭环演示")
    print("=" * 60)

    # 1. 启动
    print("\n[1/5] 启动浏览器...")
    if not bc.start():
        print("❌ 启动失败")
        return {"success": False, "error": "浏览器启动失败"}

    # 2. 导航
    print(f"\n[2/5] 导航到: {default_url}")
    if not bc.navigate(default_url):
        print("❌ 导航失败，尝试使用默认演示url")
        bc.stop()
        return {"success": False, "error": f"导航失败: {default_url}"}
    print(f"   页面标题: {bc.driver.title[:60]}")
    bc.wait(2)

    # 3. 截图
    print("\n[3/5] 截取仪表盘...")
    screenshot_path = bc.screenshot()
    if not screenshot_path:
        bc.stop()
        return {"success": False, "error": "截图失败"}

    # 4. OCR数据提取
    print("\n[4/5] OCR数据面板识别...")
    items = bc.ocr_image(screenshot_path)

    # 提取关键指标
    indicators = ["CPU", "内存", "磁盘", "Memory", "Disk", "Swap", "Load"]
    found_indicators = []
    for item in items:
        for ind in indicators:
            if ind.lower() in item["text"].lower():
                found_indicators.append((item["text"], item["confidence"]))

    if found_indicators:
        print(f"   📊 识别到 {len(found_indicators)} 个指标:")
        for text, conf in found_indicators:
            print(f"      - {text} (conf={conf:.2f})")
    else:
        print("   ⚠️ 未识别到关键指标")

    # 5. 全文验证
    print("\n[5/5] 页面文本验证...")
    page_text = bc.get_page_text()
    print(f"   页面文本(前200字): {page_text[:200]}")
    dashboard_ok = "dashboard" in page_text.lower() or "health" in page_text.lower()

    print(f"\n{'=' * 40}")
    if dashboard_ok:
        print("✅ health_dashboard 演示完成")
    else:
        print("⚠️ 页面可访问但可能不是health_dashboard")
    print(f"   截图: {screenshot_path}")
    print(f"   识别指标: {len(found_indicators)} 个")
    print(f"{'=' * 40}")

    bc.stop()
    return {
        "success": True,
        "dashboard_ok": dashboard_ok,
        "screenshot": screenshot_path,
        "found_indicators": [t for t, c in found_indicators],
    }


def main():
    parser = argparse.ArgumentParser(description="浏览器视觉点击闭环工具")
    parser.add_argument("action", nargs="?", default="demo",
                        choices=["demo", "health", "click", "verify", "find"],
                        help="执行动作")
    parser.add_argument("--text", help="目标文字")
    parser.add_argument("--verify", help="验证文字(默认同--text)")
    parser.add_argument("--url", default="http://localhost:9090", help="目标URL")
    parser.add_argument("--timeout", type=float, default=15, help="超时秒数")
    parser.add_argument("--headless", action="store_true", help="无头模式")

    args = parser.parse_args()

    if args.action == "health":
        result = health_dashboard_demo(url=args.url, headless=args.headless)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    bc = BrowserClick(headless=args.headless)
    if not bc.start():
        print("❌ 浏览器启动失败")
        return

    if args.action == "demo":
        # 默认: 导航到URL + 截图 + OCR + click_by_text demo
        if args.url:
            bc.navigate(args.url)
            bc.wait(1)

        if args.text:
            result = bc.click_verify_loop(args.text, verify_text=args.verify, timeout=args.timeout)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            path = bc.screenshot()
            print(f"📸 截图: {path}")
            text = bc.ocr_get_text(path)
            print(f"📝 识别文本:\n{text[:500]}")

    elif args.action == "click":
        if not args.text:
            print("❌ --text 必须提供")
            bc.stop()
            return
        result = bc.click_verify_loop(args.text, verify_text=args.verify, timeout=args.timeout)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif args.action == "verify":
        if not args.text:
            print("❌ --text 必须提供")
            bc.stop()
            return
        path = bc.screenshot()
        if path:
            matches = bc.find_text_coordinates(path, args.text)
            print(f"找到 {len(matches)} 个匹配:")
            for cx, cy, text, conf in matches:
                print(f"  ({cx}, {cy}): \"{text}\" conf={conf:.2f}")

    elif args.action == "find":
        # 先截图，再OCR搜索文字
        path = bc.screenshot()
        if not path:
            bc.stop()
            return
        items = bc.ocr_image(path)
        print(f"OCR识别到 {len(items)} 个文本块:")
        for item in sorted(items, key=lambda x: -x["confidence"])[:20]:
            bbox = item["bbox"]
            xs = [p[0] for p in bbox]
            ys = [p[1] for p in bbox]
            cx, cy = int(sum(xs)/len(xs)), int(sum(ys)/len(ys))
            print(f"  ({cx:4d},{cy:4d}) conf={item['confidence']:.2f} | {item['text'][:60]}")

    bc.stop()


if __name__ == "__main__":
    main()
