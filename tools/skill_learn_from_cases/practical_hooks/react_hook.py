#!/usr/bin/env python3
"""
react_hook.py — React/Frontend 实操测试

检测本机 Node.js/npm 可用性，验证 React 开发环境。
统一接口: run(env) -> dict
降级: 检测前端构建工具链
"""
import json, sys, os, subprocess


def run(env: dict = None) -> dict:
    """统一入口"""
    score = 0
    notes = []
    detail = {"node": False, "npm": False, "npx": False, "browsers": []}
    
    # 1. 检测 Node.js
    try:
        r = subprocess.run(["node", "--version"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            ver = r.stdout.strip()
            detail["node"] = True
            score += 25
            notes.append(f"Node.js {ver}")
    except:
        pass
    
    # 2. 检测 npm
    try:
        r = subprocess.run(["npm", "--version"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            ver = r.stdout.strip()
            detail["npm"] = True
            score += 25
            notes.append(f"npm {ver}")
    except:
        pass
    
    # 3. 检测 npx (create-react-app)
    try:
        r = subprocess.run(["npx", "--version"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            ver = r.stdout.strip()
            detail["npx"] = True
            score += 25
            notes.append(f"npx {ver}")
    except:
        pass
    
    # 4. 检测浏览器 (Chrome/Edge)
    browser_paths = [
        ("Chrome", r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        ("Edge", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    ]
    for name, path in browser_paths:
        if os.path.exists(path):
            detail["browsers"].append(name)
            score += 12
    if detail["browsers"]:
        notes.append(f"浏览器: {','.join(detail['browsers'])}")
    
    return {
        "score": min(score, 100),
        "passed": score >= 40,
        "note": "; ".join(notes) if notes else "未检测到前端工具链",
        "detail": detail
    }


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, ensure_ascii=False))
