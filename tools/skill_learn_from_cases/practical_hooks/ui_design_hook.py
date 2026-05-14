#!/usr/bin/env python3
"""
ui_design_hook.py — UI/UX 设计实操测试

检测本机设计工具(浏览器DevTools/设计资源/Figma等)。
统一接口: run(env) -> dict
"""
import json, sys, os, subprocess, shutil

def run(env: dict = None) -> dict:
    score = 0
    notes = []
    detail = {}
    
    # 1. 检测浏览器 DevTools
    for browser, path in [("Chrome", r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
                          ("Edge", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")]:
        detail[browser.lower()] = os.path.exists(path)
        if os.path.exists(path):
            score += 15
            notes.append(f"{browser}可用")
    
    # 2. 检测 Node.js/npm (前端工具链)
    for tool in ["node", "npm", "npx"]:
        p = shutil.which(tool)
        detail[tool] = p is not None
        if p:
            score += 8
    
    # 3. 检测 Figma (via npm package)
    has_figma = False
    try:
        r = subprocess.run(["npx", "--yes", "figma", "--version"], capture_output=True, text=True, timeout=5)
        has_figma = r.returncode == 0
    except:
        pass
    detail["figma_cli"] = has_figma
    if has_figma:
        score += 10
        notes.append("Figma CLI可用")
    
    # 4. 检测设计资源目录
    design_dirs = [
        os.path.expanduser("~/Documents/Figma"),
        os.path.expanduser("~/Desktop/设计"),
        os.path.expanduser("~/设计资源"),
    ]
    found_dirs = [d for d in design_dirs if os.path.isdir(d)]
    detail["design_dirs"] = found_dirs
    if found_dirs:
        score += 8
        notes.append("设计资源文件存在")
    
    return {
        "score": min(score, 100),
        "passed": score >= 30,
        "note": "; ".join(notes) if notes else "未检测到设计工具",
        "detail": detail
    }

if __name__ == "__main__":
    result = run()
    print(json.dumps(result, ensure_ascii=False))
