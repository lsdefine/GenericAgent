import unittest

from auto_routing_agent import AutoRoutingAgent


class FakeBackend:
    def __init__(self, name, model):
        self.name = name
        self.model = model


class FakeClient:
    def __init__(self, name, model):
        self.backend = FakeBackend(name, model)
        self.last_tools = ''


class FakeBaseAgent:
    def __init__(self):
        self.llmclients = [
            FakeClient('opencode-minimax', 'minimax-m2.5-free'),
            FakeClient('copilot-gpt4', 'gpt-4'),
            FakeClient('copilot-claude', 'claude-sonnet-4.5'),
        ]
        self.llm_no = 0
        self.llmclient = self.llmclients[0]

    def next_llm(self, n=-1):
        self.llm_no = n if n >= 0 else (self.llm_no + 1) % len(self.llmclients)
        self.llmclient = self.llmclients[self.llm_no]

    def list_llms(self):
        return [
            (i, f'{type(c.backend).__name__}/{c.backend.name}', i == self.llm_no)
            for i, c in enumerate(self.llmclients)
        ]

    def get_llm_name(self, b=None, model=False):
        client = self.llmclient if b is None else b
        return client.backend.model if model else client.backend.name


class TestAutoRouteCliCommands(unittest.TestCase):
    def _build_agent(self):
        config = {
            'enabled': True,
            'default_model': 'copilot-gpt4',
            'route_targets': {
                'multimodal': 'copilot-claude',
                'long_context': 'copilot-claude',
                'coding': 'copilot-gpt4',
                'fast': 'opencode-minimax',
            },
        }
        return AutoRoutingAgent(base_agent=FakeBaseAgent(), router_config=config)

    def test_route_status_command_reports_current_state(self):
        from agentmain_auto import handle_cli_command

        agent = self._build_agent()

        handled, text = handle_cli_command(agent, '/route_status')

        self.assertTrue(handled)
        self.assertIn('auto_route: on', text)
        self.assertIn('manual_override: off', text)

    def test_auto_route_off_command_disables_routing(self):
        from agentmain_auto import handle_cli_command

        agent = self._build_agent()

        handled, text = handle_cli_command(agent, '/auto_route off')

        self.assertTrue(handled)
        self.assertIn('auto route disabled', text.lower())
        self.assertFalse(agent.auto_route_enabled)

    def test_llm_command_switches_model_and_sets_manual_override(self):
        from agentmain_auto import handle_cli_command

        agent = self._build_agent()

        handled, text = handle_cli_command(agent, '/llm 2')

        self.assertTrue(handled)
        self.assertIn('[2] copilot-claude', text)
        self.assertTrue(agent.manual_override)


if __name__ == '__main__':
    unittest.main()