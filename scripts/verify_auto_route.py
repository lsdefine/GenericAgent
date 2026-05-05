import sys, os
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from agentmain_auto import build_agent
import time, queue


def drain_queue(q, timeout=1):
    out = ''
    try:
        while True:
            item = q.get(timeout=timeout)
            if 'next' in item:
                out += item['next']
            if 'done' in item:
                out += item['done']
                break
    except queue.Empty:
        pass
    return out


def run():
    agent = build_agent()
    print('Initial route_status:', agent.route_status())

    # 1) Ensure auto_route enabled state
    agent.enable_auto_route(True, clear_manual_override=True)
    print('After enable_auto_route(True):', agent.route_status())

    # 2) Simulate manual selection -> sets manual_override
    print('Calling next_llm(0) to simulate manual selection...')
    try:
        agent.next_llm(0)
    except Exception as e:
        print('next_llm raised:', e)
    print('After manual next_llm:', agent.route_status())

    # 3) Submit a task while manual_override=True
    dq = agent.put_task('test manual override query', source='test')
    print('Submitted task during manual_override; draining queue...')
    print('Task response:', drain_queue(dq, timeout=0.5))
    print('Status after task 1:', agent.route_status())

    # 4) Submit tasks to trigger auto-unlock (default _auto_unlock_turns=3)
    for i in range(4):
        dq = agent.put_task(f'task to advance unlock {i}', source='test')
        print(f'Draining task {i}...')
        drain_queue(dq, timeout=0.5)
        print('Status:', agent.route_status())
        time.sleep(0.1)

    # 5) Disable auto_route and check status
    agent.enable_auto_route(False)
    print('After enable_auto_route(False):', agent.route_status())


if __name__ == '__main__':
    run()
