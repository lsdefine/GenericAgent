#!/usr/bin/env python3
"""
Hermes Tool — GA↔Hermes Agent 桥接工具（增强版）
================================================

功能:
  chat       发送查询（支持 stream / 模板注入 / 多轮对话）
  sessions   管理会话
  status     Hermes 状态
  memory     记忆状态

增强:
  ✅ stream 输出 — 实时显示 token（--stream）
  ✅ 多轮对话 — --resume / --continue / --name 管理会话
  ✅ 模板注入 — ${variable} 替换 + --set key=value + --file 加载
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from shutil import which
from string import Template

HERMES_CMD = "/home/admin/.local/bin/hermes"
CONFIG_DIR = Path.home() / ".config" / "hermes_tool"
SESSION_FILE = CONFIG_DIR / "last_session.txt"

def _ensure_config():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

def _run(cmd, timeout=120, stream=False):
    """Run hermes command, optionally streaming output."""
    try:
        if stream:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, bufsize=1)
            output_parts = []
            for line in p.stdout:
                print(line, end='', flush=True)
                output_parts.append(line)
            p.wait()
            rc = p.returncode
            out = ''.join(output_parts)
            return rc, out, ""
        else:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT"
    except FileNotFoundError:
        return -2, "", f"hermes not found at {HERMES_CMD}"

def extract_response(text):
    """Extract the actual response text from hermes chat output."""
    lines = text.split('\n')
    result_lines = []
    in_response = False
    for line in lines:
        if '╰' in line and '─' in line:
            in_response = True
            continue
        if in_response:
            if line.startswith('Resume this session') or line.startswith('Session:'):
                break
            result_lines.append(line)
    r = '\n'.join(result_lines).strip()
    if r:
        return r
    non_empty = [l for l in text.split('\n') if l.strip() and not l.startswith('╭') and not l.startswith('╰')]
    return '\n'.join(non_empty[-10:]) if non_empty else text

def extract_session_id(text):
    """Extract session ID from hermes output."""
    m = re.search(r'Session:\s*(\S+)', text)
    return m.group(1) if m else None

def apply_template(query, variables):
    """Apply ${variable} template substitution."""
    if not variables:
        return query
    try:
        result = query
        for key, val in variables.items():
            result = result.replace(f"${{{key}}}", val)
            result = result.replace(f"${key}", val)
        return result
    except Exception as e:
        print(f"⚠ 模板替换警告: {e}", file=sys.stderr)
        return query

def load_query(args):
    """Load query from args, supporting file and template injection."""
    query = args.query
    if args.file:
        try:
            with open(args.file, 'r') as f:
                query = f.read()
        except FileNotFoundError:
            print(f"❌ 文件未找到: {args.file}", file=sys.stderr)
            sys.exit(1)
    
    # Template injection
    if args.set:
        variables = dict(kv.split('=', 1) for kv in args.set)
        query = apply_template(query, variables)
    
    return query

# ── Commands ─────────────────────────────

def cmd_chat(args):
    """Send query with stream / multi-turn / template support."""
    query = load_query(args)
    
    cmd = [HERMES_CMD, "chat", "-q", query]
    
    # Multi-turn: resume or continue
    if args.resume:
        cmd.extend(["--resume", args.resume])
    if args.cont:
        cmd.extend(["--continue", args.cont])
    
    # Model
    if args.model:
        cmd.extend(["-m", args.model])
    
    # Stream or quiet?
    if args.stream:
        # No -Q → stream output to terminal
        pass
    else:
        cmd.append("-Q")  # Quiet mode for programmatic use
    
    rc, out, err = _run(cmd, timeout=args.timeout, stream=args.stream)
    if rc != 0:
        print(f"❌ Error (code {rc}): {err[:500] if err else out[-500:]}", file=sys.stderr)
        sys.exit(1)
    
    if args.stream:
        # Output already printed, extract session ID from what we captured
        session_id = extract_session_id(out)
    else:
        response = extract_response(out)
        if args.json:
            session_id = extract_session_id(out)
            print(json.dumps({
                "success": True, "response": response,
                "session_id": session_id, 
                "raw_suffix": out[-500:]
            }, ensure_ascii=False))
        else:
            print(response)
            session_id = extract_session_id(out)
    
    # Save session ID for easy resume
    if session_id:
        _ensure_config()
        SESSION_FILE.write_text(session_id)
        # Also save with name if provided
        if args.name:
            name_file = CONFIG_DIR / f"session_{args.name}.txt"
            name_file.write_text(session_id)

def cmd_status(args):
    rc, out, err = _run([HERMES_CMD, "status"], timeout=15)
    print(out if rc == 0 else err)

def cmd_sessions(args):
    subcmd = args.subcommand or "list"
    cmd = [HERMES_CMD, "sessions", subcmd]
    
    if subcmd == "delete" and args.session_id:
        cmd.append(args.session_id)
    if subcmd == "rename" and args.session_id and args.name:
        cmd.extend([args.session_id, args.name])
    
    rc, out, err = _run(cmd, timeout=15)
    print(out if rc == 0 else err)

def cmd_memory(args):
    rc, out, err = _run([HERMES_CMD, "memory", "status"], timeout=15)
    print(out if rc == 0 else err)

def cmd_last(args):
    """Show last session ID."""
    _ensure_config()
    if SESSION_FILE.exists():
        session_id = SESSION_FILE.read_text().strip()
        print(session_id)
    else:
        print("❌ No saved session", file=sys.stderr)
        sys.exit(1)

# ── CLI ──────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Hermes Tool - GA bridge (enhanced)")
    sp = p.add_subparsers(dest="command")
    
    # chat
    chat_p = sp.add_parser("chat", help="Send a query")
    chat_p.add_argument("query", nargs="?", default="", help="Query text (omit if using --file)")
    chat_p.add_argument("-m", "--model", help="Model name")
    chat_p.add_argument("--json", action="store_true", help="JSON output")
    chat_p.add_argument("--timeout", type=int, default=120)
    # Stream
    chat_p.add_argument("--stream", action="store_true", help="Stream output tokens in real-time")
    # Multi-turn
    chat_p.add_argument("-r", "--resume", help="Resume session by ID")
    chat_p.add_argument("--continue", dest="cont", help="Continue session by name")
    chat_p.add_argument("--name", help="Save session with a friendly name")
    # Template
    chat_p.add_argument("--file", "-f", help="Load query from file (supports ${var})")
    chat_p.add_argument("--set", action="append", help="Set template variable key=value (repeatable)")
    
    # sessions
    sessions_p = sp.add_parser("sessions", help="Manage sessions")
    sessions_p.add_argument("subcommand", nargs="?", default="list",
                           choices=["list", "delete", "rename", "export", "stats"])
    sessions_p.add_argument("session_id", nargs="?", help="Session ID")
    sessions_p.add_argument("--name", "-n", help="Session name (for rename)")
    
    sp.add_parser("status", help="Hermes status")
    sp.add_parser("memory", help="Memory status")
    sp.add_parser("last", help="Show last session ID")
    
    args = p.parse_args()
    if not args.command:
        p.print_help()
        sys.exit(1)
    
    globals()[f"cmd_{args.command}"](args)

if __name__ == "__main__":
    main()
