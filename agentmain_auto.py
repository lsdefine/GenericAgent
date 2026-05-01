import argparse
import os
import queue
import sys
import threading

from auto_routing_agent import AutoRoutingAgent


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG_PATH = os.path.join(SCRIPT_DIR, 'auto_route_config.json')


def build_agent(config_path=DEFAULT_CONFIG_PATH):
    from agentmain import GeneraticAgent

    base_agent = GeneraticAgent()
    return AutoRoutingAgent(base_agent=base_agent, config_path=config_path)


def handle_cli_command(agent, raw):
    parts = (raw or '').strip().split()
    op = (parts[0] if parts else '').lower()
    if not op.startswith('/'):
        return False, None

    if op == '/route_status':
        status = agent.route_status()
        last_route = status.get('last_route') or {}
        lines = [
            f"auto_route: {'on' if status.get('auto_route_enabled') else 'off'}",
            f"manual_override: {'on' if status.get('manual_override') else 'off'}",
            f"current_model: {status.get('current_model')}",
        ]
        if last_route:
            lines.append(f"last_reason: {last_route.get('reason')}")
            lines.append(f"last_selected: {last_route.get('selected_name')}")
        return True, '\n'.join(lines)

    if op == '/auto_route':
        arg = parts[1].lower() if len(parts) > 1 else ''
        if arg in ('on', '1', 'true'):
            agent.enable_auto_route(True, clear_manual_override=True)
            return True, 'auto route disabled override cleared; auto route enabled'
        if arg in ('off', '0', 'false'):
            agent.enable_auto_route(False)
            return True, 'auto route disabled'
        return True, 'usage: /auto_route on|off'

    if op == '/llm':
        if len(parts) == 1:
            lines = [f"{'->' if cur else '  '} [{i}] {name}" for i, name, cur in agent.list_llms()]
            return True, 'LLMs:\n' + '\n'.join(lines)
        try:
            target = int(parts[1])
            agent.next_llm(target)
            return True, f'[{agent.llm_no}] {agent.get_llm_name()}'
        except Exception:
            return True, f'usage: /llm <0-{len(agent.list_llms()) - 1}>'

    return False, None


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--task', metavar='IODIR', help='一次性任务模式(文件IO)')
    parser.add_argument('--input', help='prompt')
    parser.add_argument('--llm_no', type=int, default=-1)
    parser.add_argument('--verbose', action='store_true')
    parser.add_argument('--config', default=DEFAULT_CONFIG_PATH)
    args = parser.parse_args(argv)

    agent = build_agent(config_path=args.config)
    if args.llm_no >= 0:
        agent.next_llm(args.llm_no)
    agent.verbose = args.verbose
    threading.Thread(target=agent.base_agent.run, daemon=True).start()

    if args.task:
        task_dir = os.path.join(SCRIPT_DIR, f'temp/{args.task}')
        os.makedirs(task_dir, exist_ok=True)
        infile = os.path.join(task_dir, 'input.txt')
        if args.input:
            with open(infile, 'w', encoding='utf-8') as f:
                f.write(args.input)
        with open(infile, 'r', encoding='utf-8') as f:
            query = f.read()
        dq = agent.put_task(query, source='task')
        item = dq.get(timeout=120)
        while 'done' not in item:
            item = dq.get(timeout=120)
        output_path = os.path.join(task_dir, 'output.txt')
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(item['done'])
        print(output_path)
        return 0

    while True:
        try:
            query = input('auto> ').strip()
            if not query:
                continue
            handled, text = handle_cli_command(agent, query)
            if handled:
                print(text)
                continue
            dq = agent.put_task(query, source='user')
            while True:
                item = dq.get()
                if 'next' in item:
                    print(item['next'], end='', flush=True)
                if 'done' in item:
                    print()
                    break
        except KeyboardInterrupt:
            agent.shutdown()
            print('\n[Interrupted]')
            return 0
        except queue.Empty:
            print('[Timeout]')
            return 1


if __name__ == '__main__':
    sys.exit(main())