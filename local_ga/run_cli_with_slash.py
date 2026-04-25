from __future__ import annotations

import argparse
import os
import queue
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from slash_adapter import available_commands, transform


def _run_once(agent, raw: str) -> bool:
    prompt = transform(raw) or raw
    dq = agent.put_task(prompt, source="slash-cli")
    while True:
        try:
            item = dq.get(timeout=120)
        except queue.Empty:
            print("[slash-cli] timeout waiting for agent output")
            agent.abort()
            return False
        if "next" in item:
            print(item["next"], end="", flush=True)
        if "done" in item:
            print(item["done"])
            return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Run GenericAgent with local slash command expansion.")
    parser.add_argument("--input", help="single prompt to run")
    parser.add_argument("--llm_no", type=int, default=0)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--commands", action="store_true", help="list supported slash commands")
    args = parser.parse_args()

    if args.commands:
        print("\n".join(f"/{name}" for name in available_commands()))
        return 0

    from agentmain import GeneraticAgent

    agent = GeneraticAgent()
    if not agent.llmclients:
        print("[slash-cli] no usable LLM backend found in mykey.py or mykey.json", file=sys.stderr)
        return 1
    agent.next_llm(args.llm_no)
    agent.verbose = args.verbose
    agent.inc_out = True
    threading.Thread(target=agent.run, daemon=True).start()

    if args.input is not None:
        return 0 if _run_once(agent, args.input) else 1

    print("[slash-cli] commands:", ", ".join(f"/{name}" for name in available_commands()))
    print("[slash-cli] type /exit to quit")
    while True:
        try:
            raw = input("> ").strip()
        except EOFError:
            return 0
        if raw in {"/exit", "exit", "quit"}:
            return 0
        if raw:
            _run_once(agent, raw)


if __name__ == "__main__":
    raise SystemExit(main())
