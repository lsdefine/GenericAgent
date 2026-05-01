import queue
import unittest


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
            FakeClient('copilot-gemini', 'gemini-2.5-pro'),
        ]
        self.llm_no = 0
        self.llmclient = self.llmclients[0]
        self.forwarded = []

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

    def put_task(self, query, source='user', images=None):
        self.forwarded.append({
            'llm_no': self.llm_no,
            'query': query,
            'source': source,
            'images': images or [],
        })
        out = queue.Queue()
        out.put({'done': f'dispatched:{self.llm_no}'})
        return out


class TestAutoRoutingAgent(unittest.TestCase):
    def _build_agent(self):
        from auto_routing_agent import AutoRoutingAgent

        config = {
            'enabled': True,
            'default_model': 'copilot-gpt4',
            'route_targets': {
                'multimodal': 'copilot-gemini',
                'long_context': 'copilot-claude',
                'coding': 'copilot-gpt4',
                'fast': 'opencode-minimax',
            },
            'thresholds': {
                'long_query_chars': 800,
                'long_history_entries': 12,
            },
        }
        return AutoRoutingAgent(base_agent=FakeBaseAgent(), router_config=config)

    def test_auto_routes_before_forwarding_task(self):
        agent = self._build_agent()

        result_q = agent.put_task('请帮我修复这个 Python 报错', images=[])
        done = result_q.get(timeout=1)

        self.assertEqual(done['done'], 'dispatched:1')
        self.assertEqual(agent.base_agent.forwarded[-1]['llm_no'], 1)
        self.assertEqual(agent.last_route['target_name'], 'copilot-gpt4')
        self.assertEqual(agent.last_route['previous_model'], 'opencode-minimax')
        self.assertEqual(agent.last_route['executed_model'], 'copilot-gpt4')
        agent.shutdown()

    def test_manual_llm_override_blocks_auto_routing_until_cleared(self):
        agent = self._build_agent()
        agent.next_llm(2)

        result_q = agent.put_task('帮我润色一句周报', images=[])
        done = result_q.get(timeout=1)

        self.assertEqual(done['done'], 'dispatched:2')
        self.assertEqual(agent.base_agent.forwarded[-1]['llm_no'], 2)

        agent.enable_auto_route(True, clear_manual_override=True)
        result_q = agent.put_task('帮我润色一句周报', images=[])
        done = result_q.get(timeout=1)

        self.assertEqual(done['done'], 'dispatched:0')
        self.assertEqual(agent.base_agent.forwarded[-1]['llm_no'], 0)
        agent.shutdown()

    def test_unknown_route_target_falls_back_to_default_model(self):
        agent = self._build_agent()
        agent.router.config['route_targets']['coding'] = 'missing-model'

        result_q = agent.put_task('请修复这个异常', images=[])
        done = result_q.get(timeout=1)

        self.assertEqual(done['done'], 'dispatched:1')
        self.assertEqual(agent.last_route['selected_name'], 'copilot-gpt4')
        self.assertEqual(agent.last_route['fallback_reason'], 'target_not_found')
        self.assertEqual(agent.last_route['executed_model'], 'copilot-gpt4')
        agent.shutdown()

    def test_manual_override_auto_unlock(self):
        agent = self._build_agent()
        agent.next_llm(2)  # 手动切换到 copilot-claude
        # 3轮后应自动解锁
        for i in range(3):
            result_q = agent.put_task(f'轮次{i+1}', images=[])
            done = result_q.get(timeout=1)
            if i < 2:
                self.assertEqual(agent.manual_override, True)
            else:
                self.assertEqual(agent.manual_override, False)
        agent.shutdown()


if __name__ == '__main__':
    unittest.main()