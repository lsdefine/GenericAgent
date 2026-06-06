#!/usr/bin/env python3
"""
ai — 轻量级 AI-native CLI 工具
类似 fabric/shell-gpt/llm，对接本地 OpenLLM API

用法:
  ai ask "问题"              → 问答模式
  echo "文本" | ai sum       → 管道总结
  ai shell "描述"            → 生成Shell命令
  ai code "需求"             → 生成代码
  ai chat                    → 交互式对话
  ai list                    → 列出可用模型

配置:
  export OPENLLM_BASE=http://127.0.0.1:11343
  export AI_MODEL=deepseek/deepseek-v4-flash
"""

import os, sys, json, argparse, subprocess
from urllib.request import Request, urlopen
from urllib.error import HTTPError

OPENLLM_BASE = os.environ.get("OPENLLM_BASE", "http://127.0.0.1:11343")
AI_MODEL = os.environ.get("AI_MODEL", "deepseek/deepseek-v4-flash")

# 孤儿工具整合: 使用model_router的智能路由
try:
    from scripts.model_router import route as model_route
    _has_router = True
except ImportError:
    _has_router = False

def api_chat(model, messages, max_tokens=1024, temperature=0.7, timeout=30):
    url = f"{OPENLLM_BASE}/v1/chat/completions"
    body = json.dumps({
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }).encode()
    req = Request(url, data=body, headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode())
    return data["choices"][0]["message"]["content"].strip()

def cmd_ask(args):
    prompt = " ".join(args.prompt) if args.prompt else sys.stdin.read().strip()
    if not prompt:
        print("⚠️  请输入问题")
        return
    try:
        resp = api_chat(args.model or AI_MODEL, [
            {"role": "system", "content": "You are a helpful AI assistant. Answer concisely."},
            {"role": "user", "content": prompt}
        ])
        print(resp)
    except HTTPError as e:
        print(f"❌ API错误: {e.code} {e.reason}")
    except Exception as e:
        print(f"❌ {e}")

def cmd_sum(args):
    text = sys.stdin.read().strip()
    if not text:
        print("⚠️  请通过管道输入文本: echo '...' | ai sum")
        return
    style = args.style or "concise"
    try:
        resp = api_chat(args.model or AI_MODEL, [
            {"role": "system", "content": f"Summarize the following text. Style: {style}. Keep key points."},
            {"role": "user", "content": text[:4000]}
        ])
        print(resp)
    except Exception as e:
        print(f"❌ {e}")

def cmd_shell(args):
    desc = " ".join(args.desc)
    if not desc:
        print("⚠️  请输入命令描述")
        return
    try:
        resp = api_chat(args.model or AI_MODEL, [
            {"role": "system", "content": "You are a shell command generator. Output ONLY the shell command, no explanation."},
            {"role": "user", "content": f"Generate a shell command to: {desc}"}
        ])
        # Remove markdown code fences if present
        resp = resp.strip()
        if resp.startswith("```"):
            resp = resp.split("\n", 1)[-1]
            resp = resp.rsplit("```", 1)[0]
        print(resp.strip())
    except Exception as e:
        print(f"❌ {e}")

def cmd_code(args):
    req = " ".join(args.req)
    if not req:
        print("⚠️  请输入代码需求")
        return
    lang = args.lang or "python"
    try:
        resp = api_chat(args.model or AI_MODEL, [
            {"role": "system", "content": f"You are a code generator. Output only {lang} code."},
            {"role": "user", "content": f"Write {lang} code to: {req}"}
        ])
        print(resp)
    except Exception as e:
        print(f"❌ {e}")

def cmd_chat(args):
    """交互式对话"""
    print(f"🤖 AI Chat (model: {args.model or AI_MODEL})")
    print("输入 exit 退出, clear 清屏\n")
    history = []
    while True:
        try:
            user = input(">>> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user:
            continue
        if user.lower() == "exit":
            break
        if user.lower() == "clear":
            os.system("clear" if os.name == "posix" else "cls")
            continue
        history.append({"role": "user", "content": user})
        try:
            messages = [{"role": "system", "content": "You are a helpful AI."}] + history[-10:]
            resp = api_chat(args.model or AI_MODEL, messages)
            print(f"\n🤖 {resp}\n")
            history.append({"role": "assistant", "content": resp})
        except Exception as e:
            print(f"❌ {e}")

def cmd_list(args):
    """列出可用模型"""
    url = f"{OPENLLM_BASE}/v1/models"
    req = Request(url)
    with urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())
    print(f"📋 可用模型 ({len(data.get('data', []))}):")
    for m in data.get("data", []):
        print(f"  {m.get('id', m.get('name', '?'))}")

def main():
    parser = argparse.ArgumentParser(description="ai — AI-native CLI tool")
    parser.add_argument("--model", "-m", help="模型ID (默认: $AI_MODEL)")
    sub = parser.add_subparsers(dest="command")

    p_ask = sub.add_parser("ask", help="问答模式")
    p_ask.add_argument("prompt", nargs="*", help="问题")

    p_sum = sub.add_parser("sum", help="管道总结")
    p_sum.add_argument("--style", "-s", default="concise", help="总结风格")

    p_shell = sub.add_parser("shell", help="生成Shell命令")
    p_shell.add_argument("desc", nargs="*", help="命令描述")

    p_code = sub.add_parser("code", help="生成代码")
    p_code.add_argument("req", nargs="*", help="代码需求")
    p_code.add_argument("--lang", "-l", default="python", help="编程语言")

    sub.add_parser("chat", help="交互式对话")
    sub.add_parser("list", help="列出模型")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    cmds = {
        "ask": cmd_ask,
        "sum": cmd_sum,
        "shell": cmd_shell,
        "code": cmd_code,
        "chat": cmd_chat,
        "list": cmd_list,
    }
    cmds[args.command](args)

if __name__ == "__main__":
    main()
