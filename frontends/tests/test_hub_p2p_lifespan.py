"""FastAPI lifespan integration; no real pairing records or network access."""
import ast
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from fastapi import FastAPI

FRONTENDS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FRONTENDS))
import hub_p2p


class FakeGroup:
    def __init__(self, *args, **kwargs):
        self._out, self._in = {}, {}
        self.members, self._ws = set(), None
        self.ran = self.closed = False

    async def run(self):
        self.ran = True
        try:
            await asyncio.Event().wait()
        finally:
            for task in [*self._out.values(), *self._in.values()]:
                task.cancel()
            self.closed = True


class LifespanTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.loader = self.enterContext(patch.object(hub_p2p, 'load_room', return_value={
            'signal_url': 'ws://unused.invalid/ws', 'room': 'test-only',
        }))
        self.enterContext(patch.object(hub_p2p, 'Group', FakeGroup))
        # Exactly the same explicit FastAPI lifespan delegation as hub.py.
        @asynccontextmanager
        async def lifespan(app):
            async with self.state['lifespan'](app):
                yield
        self.app = FastAPI(lifespan=lifespan)
        self.state = hub_p2p.install(self.app, web_port=1, token='test-only', here=FRONTENDS)

    @asynccontextmanager
    async def running(self):
        incoming, outgoing = asyncio.Queue(), asyncio.Queue()
        scope = {'type': 'lifespan', 'asgi': {'version': '3.0', 'spec_version': '2.0'}, 'state': {}}
        task = asyncio.create_task(self.app(scope, incoming.get, outgoing.put))
        try:
            await incoming.put({'type': 'lifespan.startup'})
            result = await asyncio.wait_for(outgoing.get(), 2)
            if result['type'] != 'lifespan.startup.complete':
                await task  # Propagate the original startup exception.
                self.fail(result)
            yield
            await incoming.put({'type': 'lifespan.shutdown'})
            result = await asyncio.wait_for(outgoing.get(), 2)
            self.assertEqual(result['type'], 'lifespan.shutdown.complete')
            await task
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_saved_pairing_auto_starts_and_can_restart(self):
        for _ in range(2):
            async with self.running():
                group = self.state['group']
                self.assertIsInstance(group, FakeGroup)
                await asyncio.sleep(0)
                self.assertTrue(group.ran)
                self.assertTrue(self.state['started'])
            self.assertTrue(group.closed)
            self.assertFalse(self.state['started'])
            self.assertIsNone(self.state['group'])

    async def test_unpaired_starts_without_creating_pairing(self):
        self.loader.side_effect = KeyError('unpaired')
        async with self.running():
            self.assertIsNone(self.state['group'])
            self.assertIsNone(self.state['task'])
            self.assertEqual(self.state['status'], 'idle')

    async def test_startup_error_is_not_silently_ignored(self):
        self.loader.side_effect = ValueError('invalid pairing configuration')
        with self.assertRaisesRegex(ValueError, 'invalid pairing'):
            async with self.running():
                self.fail('Startup must fail')
        self.assertFalse(self.state['started'])

    async def test_shutdown_awaits_links_pairing_and_legacy(self):
        closed = set()
        async def worker(name):
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)  # Cleanup must finish, not just receive cancel.
                closed.add(name)
        async with self.running():
            group = self.state['group']
            group._out['a'] = asyncio.create_task(worker('out'))
            group._in['b'] = asyncio.create_task(worker('in'))
            self.state['task'] = asyncio.create_task(worker('pair'))
            self.state['legacy'] = asyncio.create_task(worker('legacy'))
            await asyncio.sleep(0)
        self.assertEqual(closed, {'out', 'in', 'pair', 'legacy'})
        self.assertFalse([t for t in asyncio.all_tasks() if t is not asyncio.current_task()])

    async def test_duplicate_lifespan_rejected_without_stopping_owner(self):
        async with self.running():
            group = self.state['group']
            with self.assertRaisesRegex(RuntimeError, 'already running'):
                async with self.state['lifespan'](self.app):
                    self.fail('Duplicate startup')
            self.assertIs(self.state['group'], group)
            self.assertTrue(self.state['started'])

    def test_only_web_server_owns_lifespan(self):
        tree = ast.parse((FRONTENDS / 'hub.py').read_text())
        configs = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'Config':
                kw = {k.arg: k.value for k in node.keywords}
                configs[kw['port'].id] = ast.literal_eval(kw['lifespan'])
        self.assertEqual(configs, {'WEB_PORT': 'on', 'PORT': 'off'})


if __name__ == '__main__':
    unittest.main()
