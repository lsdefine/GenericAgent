"""
env_detector.py — 环境探测模块

自动探测本机可用的数据库/工具服务，供 practical hooks 使用。
探测结果写入 ctx["env"]，Phase 5 据此决定是否执行真实实操测试。

规则：
  - 环境变量中有密码/密钥 → 自动连接测试
  - 端口开放但无凭据 → 记录为"需用户确认"
  - 既无端口也无凭据 → 标记为不可用
"""

import os
import socket
import subprocess
import json
from pathlib import Path

_GA_ROOT = Path(__file__).resolve().parents[2]


def _port_open(host: str, port: int, timeout: float = 2.0) -> bool:
    """检查端口是否开放"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        return s.connect_ex((host, port)) == 0
    finally:
        s.close()


def _check_env(name: str) -> str:
    """读取环境变量，返回 (值 or '')"""
    return os.environ.get(name, "")


def detect_neo4j() -> dict:
    """
    探测 Neo4j 环境
    返回: {"available": bool, "url": str, "auth": bool, "note": str}
    """
    result = {"available": False, "url": "", "auth": False, "note": ""}
    
    bolt_open = _port_open("127.0.0.1", 7687)
    http_open = _port_open("127.0.0.1", 7474)
    password = _check_env("neo4j_password")
    
    if not (bolt_open or http_open):
        result["note"] = "Neo4j 端口未开放"
        return result
    
    if password:
        result["available"] = True
        result["auth"] = True
        result["url"] = "bolt://localhost:7687"
        result["note"] = "Neo4j 就绪（已配置密码）"
    else:
        result["url"] = "bolt://localhost:7687"
        result["note"] = "Neo4j 端口开放，但未设置 neo4j_password 环境变量"
    
    return result


def detect_docker() -> dict:
    """探测 Docker (通过 WSL)"""
    result = {"available": False, "note": ""}
    try:
        r = subprocess.run(
            ["wsl.exe", "--exec", "bash", "-c", "docker info --format '{{.ServerVersion}}' 2>/dev/null"],
            capture_output=True, text=True, timeout=5
        )
        if r.returncode == 0 and r.stdout.strip():
            result["available"] = True
            result["note"] = f"Docker {r.stdout.strip()} (WSL)"
    except:
        result["note"] = "Docker 不可用"
    return result


def detect_sqlite() -> dict:
    """探测 SQLite CLI"""
    result = {"available": False, "note": ""}
    for path in [
        r"D:\ProgramData\miniconda3\Library\bin\sqlite3.exe",
        r"C:\Program Files\SQLite\sqlite3.exe",
    ]:
        if os.path.exists(path):
            try:
                r = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=3)
                if r.returncode == 0:
                    result["available"] = True
                    result["path"] = path
                    result["note"] = f"SQLite {r.stdout.strip()}"
                    break
            except:
                pass
    if not result["available"]:
        result["note"] = "SQLite CLI 未找到"
    return result


def detect_git() -> dict:
    """探测 Git"""
    result = {"available": False, "note": ""}
    try:
        r = subprocess.run(["git", "--version"], capture_output=True, text=True, timeout=3)
        if r.returncode == 0:
            result["available"] = True
            result["note"] = r.stdout.strip()
    except:
        result["note"] = "Git 不可用"
    return result


def detect_all() -> dict:
    """全量环境探测"""
    print("  [探测] 扫描本机可用环境...")
    env = {
        "neo4j": detect_neo4j(),
        "docker": detect_docker(),
        "sqlite": detect_sqlite(),
        "git": detect_git(),
        "paddle_ocr": detect_paddle_ocr(),
    }
    
    # 汇总
    available = [k for k, v in env.items() if v.get("available")]
    need_auth = [k for k, v in env.items() if v.get("url") and not v.get("auth")]
    
    print(f"  [探测] 可用: {', '.join(available) if available else '无'}")
    
    # 询问用户缺失的凭据（仅交互模式下）
    for item in need_auth:
        key = f"{item}_password"
        if key not in os.environ:
            try:
                from ga import ask_user
                pw = ask_user(f"检测到 {item} 服务（端口开放），请输入密码\n（设置环境变量 {key} 可跳过此提示）")
                if pw and pw.strip():
                    os.environ[key] = pw.strip()
                    env[item]["auth"] = True
                    print(f"  [探测] ✅ {item} 密码已通过用户提供")
            except ImportError:
                print(f"  [探测] ⚠ {item}: 端口已开放，需要密码（设置 {key} 环境变量）")
    
    return env


if __name__ == "__main__":
    # 独立测试
    print(json.dumps(detect_all(), indent=2, ensure_ascii=False))


def detect_paddle_ocr() -> dict:
    """探测 PaddleOCR-VL (llama-server on :8090)"""
    if not _port_open("127.0.0.1", 8090):
        return {"available": False}
    try:
        import urllib.request, json
        req = urllib.request.Request("http://localhost:8090/v1/models")
        with urllib.request.urlopen(req, timeout=3) as resp:
            models = json.loads(resp.read())
        for m in models.get("models", []):
            name = m.get("name", "")
            if "ocr" in name.lower() or "Paddle" in name:
                return {"available": True, "url": "http://localhost:8090/v1/chat/completions", "model": "PaddleOCR-VL-1.5-GGUF", "auth": True, "note": f"PaddleOCR-VL: {name}"}
        return {"available": True, "url": "http://localhost:8090/v1/chat/completions", "note": "llama-server running"}
    except:
        return {"available": False}
