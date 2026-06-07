#!/usr/bin/env python3
"""
nanobot_wrapper.py — Nanobot API CLI Wrapper (v111#2)

将本地 Nanobot serve (8900) / gateway (18790) API 暴露为命令行工具。
用法:
    python3 scripts/nanobot_wrapper.py status          # API状态检查
    python3 scripts/nanobot_wrapper.py chat "你好"     # 简单对话
    python3 scripts/nanobot_wrapper.py summarize < file.txt  # 摘要
    python3 scripts/nanobot_wrapper.py analyze-sys      # 系统状态分析
"""

import sys, json, os, subprocess
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / 'memory/tools'))
sys.path.insert(0, str(BASE / 'memory'))

from nanobot_api import NanobotClient


def cmd_status():
    """API 状态检查"""
    client = NanobotClient()
    try:
        models = client.list_models()
        model_ids = [m['id'] for m in models]
        print(f"✅ Nanobot Serve (8900): 可用")
        print(f"   Models: {', '.join(model_ids)}")
    except Exception as e:
        print(f"❌ Nanobot Serve (8900): {e}")
        return
    
    try:
        import requests
        r = requests.get("http://127.0.0.1:18790/health", timeout=5)
        print(f"✅ Nanobot Gateway (18790): HTTP {r.status_code}")
        if r.text:
            print(f"   Response: {r.text[:100]}")
    except Exception as e:
        print(f"❌ Nanobot Gateway (18790): {e}")
    
    # Process info
    try:
        ps = subprocess.run(["ps", "-o", "pid,user,%mem,%cpu,lstart", "-p", "732205,732218"],
                          capture_output=True, text=True, timeout=3)
        print(f"📊 进程状态:\n{ps.stdout}")
    except:
        pass


def cmd_chat(text: str):
    """简单对话"""
    if not text:
        print("❌ 请提供聊天内容")
        return
    client = NanobotClient()
    try:
        resp = client.chat(
            messages=[{"role": "user", "content": text}],
            max_tokens=512,
            temperature=0.7,
        )
        content = resp.get("choices", [{}])[0].get("message", {}).get("content", "N/A")
        print(f"🟢 Nanobot: {content}")
    except Exception as e:
        print(f"❌ 调用失败: {e}")


def cmd_summarize():
    """从 stdin 读取文本并总结"""
    text = sys.stdin.read().strip()
    if not text:
        print("❌ 请通过 stdin 输入文本")
        print("   用法: cat file.txt | python3 scripts/nanobot_wrapper.py summarize")
        return
    if len(text) > 8000:
        text = text[:8000] + "\n...[截断]"
    
    client = NanobotClient()
    try:
        resp = client.chat(
            messages=[
                {"role": "system", "content": "你是一个摘要助手。请用3-5句话总结以下内容，中文回复。"},
                {"role": "user", "content": text},
            ],
            max_tokens=512,
            temperature=0.3,
        )
        content = resp.get("choices", [{}])[0].get("message", {}).get("content", "N/A")
        print(f"📝 摘要结果:\n{content}")
    except Exception as e:
        print(f"❌ 摘要失败: {e}")


def cmd_analyze_sys():
    """分析当前系统状态，利用 Nanobot 给出健康建议"""
    # 收集系统信息
    info = {}
    try:
        free = subprocess.run(["free", "-h"], capture_output=True, text=True, timeout=5)
        info["memory"] = free.stdout.splitlines()[1] if free.stdout else "N/A"
    except:
        info["memory"] = "N/A"
    
    try:
        df = subprocess.run(["df", "-h", "/"], capture_output=True, text=True, timeout=5)
        info["disk"] = df.stdout.splitlines()[1] if df.stdout else "N/A"
    except:
        info["disk"] = "N/A"
    
    try:
        load = subprocess.run(["uptime"], capture_output=True, text=True, timeout=5)
        info["load"] = load.stdout.strip()
    except:
        info["load"] = "N/A"
    
    try:
        procs = subprocess.run(
            ["pgrep", "-f", "python3.*frontends/fsapp|agentmain.*reflect|nanobot|openllm", "-c"],
            capture_output=True, text=True, timeout=3
        )
        info["processes"] = procs.stdout.strip()
    except:
        info["processes"] = "N/A"
    
    prompt = f"""你是一个系统健康分析助手。分析以下系统数据并给出3条具体建议：

系统内存: {info.get('memory', 'N/A')}
磁盘: {info.get('disk', 'N/A')}
负载: {info.get('load', 'N/A')}
GA进程数: {info.get('processes', 'N/A')}
当前时间: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

请用中文回复，每条建议一行带序号。"""
    
    client = NanobotClient()
    try:
        resp = client.chat(
            messages=[
                {"role": "system", "content": "你是系统运维专家，分析数据并给出简洁建议。"},
                {"role": "user", "content": prompt},
            ],
            max_tokens=512,
            temperature=0.3,
        )
        content = resp.get("choices", [{}])[0].get("message", {}).get("content", "N/A")
        print(f"🤖 系统分析:\n{content}")
    except Exception as e:
        print(f"❌ 分析失败: {e}")


def cmd_interactive():
    """交互式对话模式"""
    print("🟢 Nanobot 交互模式 (输入 'quit' 退出)")
    print("=" * 40)
    client = NanobotClient()
    history = []
    while True:
        try:
            user = input("\n你: ")
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break
        if user.lower() in ("quit", "exit", "q"):
            break
        if not user:
            continue
        history.append({"role": "user", "content": user})
        try:
            resp = client.chat(messages=history[-6:], max_tokens=512)
            reply = resp.get("choices", [{}])[0].get("message", {}).get("content", "N/A")
            print(f"🤖 Nanobot: {reply}")
            history.append({"role": "assistant", "content": reply})
        except Exception as e:
            print(f"❌ {e}")


def cmd_gateway():
    """查询 Gateway API"""
    import requests
    try:
        r = requests.get("http://127.0.0.1:18790/health", timeout=5)
        print(f"Gateway /health: {r.status_code}")
        if r.text:
            try:
                data = r.json()
                print(json.dumps(data, indent=2, ensure_ascii=False))
            except:
                print(r.text[:500])
    except Exception as e:
        print(f"❌ Gateway 不可用: {e}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    
    cmd = sys.argv[1]
    
    if cmd == "status":
        cmd_status()
    elif cmd == "chat":
        text = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else ""
        cmd_chat(text)
    elif cmd == "summarize":
        cmd_summarize()
    elif cmd == "analyze-sys":
        cmd_analyze_sys()
    elif cmd == "interactive":
        cmd_interactive()
    elif cmd == "gateway":
        cmd_gateway()
    else:
        print(f"❌ 未知命令: {cmd}")
        print(__doc__)


if __name__ == "__main__":
    main()
