import os

from agentmain import GeneraticAgent


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_AUTO_ROUTE_CONFIG_PATH = os.path.join(SCRIPT_DIR, 'auto_route_config.json')


def _to_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ('1', 'true', 'yes', 'on'):
        return True
    if text in ('0', 'false', 'no', 'off'):
        return False
    return default


def create_agent(enable_auto_route=None, config_path=DEFAULT_AUTO_ROUTE_CONFIG_PATH):
    base_agent = GeneraticAgent()

    if enable_auto_route is None:
        # Global switch for non-stapp frontends.
        enable_auto_route = _to_bool(os.getenv('GA_AUTO_ROUTE_ALL_FRONTENDS'), default=False)

    if not enable_auto_route:
        return base_agent

    from auto_routing_agent import AutoRoutingAgent

    return AutoRoutingAgent(base_agent=base_agent, config_path=config_path)
