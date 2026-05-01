import os
import re
import unittest


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTENDS_DIR = os.path.join(PROJECT_ROOT, 'frontends')

# stapp has dedicated auto-routing wiring; chatapp_common intentionally patches GeneraticAgent.
SKIP_FILES = {'stapp.py', 'chatapp_common.py'}
TARGET_FILES = {
    'dingtalkapp.py',
    'fsapp.py',
    'qqapp.py',
    'qtapp.py',
    'stapp2.py',
    'tgapp.py',
    'wechatapp.py',
    'wecomapp.py',
}


class TestFrontendAgentFactoryGuard(unittest.TestCase):
    def test_target_frontends_use_agent_factory(self):
        missing = []
        direct_ctor = []
        untracked = []

        for name in sorted(os.listdir(FRONTENDS_DIR)):
            if not name.endswith('.py') or name in SKIP_FILES:
                continue
            path = os.path.join(FRONTENDS_DIR, name)
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()

            if name in TARGET_FILES:
                if 'from agent_factory import create_agent' not in content:
                    missing.append(name)
                # guard against direct construction regression
                if re.search(r'\bGeneraticAgent\s*\(', content):
                    direct_ctor.append(name)
            else:
                # Newly added frontend modules should be reviewed for routing scope.
                if 'from agentmain import GeneraticAgent' in content:
                    untracked.append(name)

        self.assertFalse(
            missing,
            f'Frontend modules missing create_agent import: {missing}',
        )
        self.assertFalse(
            direct_ctor,
            f'Frontend modules regressed to direct GeneraticAgent() usage: {direct_ctor}',
        )
        self.assertFalse(
            untracked,
            f'New frontend modules using GeneraticAgent need agent_factory review: {untracked}',
        )


if __name__ == '__main__':
    unittest.main()
