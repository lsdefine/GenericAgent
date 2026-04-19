import os
import sys
import threading

script_dir = os.path.dirname(__file__)
repo_dir = os.path.abspath(os.path.join(script_dir, ".."))
if repo_dir not in sys.path:
    sys.path.append(repo_dir)

from agentmain import GeneraticAgent
from ga_switch import get_service

_runtime_lock = threading.Lock()
_runtime = None
_worker_started = False


def get_shared_runtime():
    global _runtime, _worker_started
    with _runtime_lock:
        if _runtime is None:
            service = get_service()
            agent = GeneraticAgent()
            _runtime = (service, agent)
        service, agent = _runtime
        if agent.llmclient is not None and not _worker_started:
            threading.Thread(target=agent.run, daemon=True, name="ga-shared-agent").start()
            _worker_started = True
        return service, agent
