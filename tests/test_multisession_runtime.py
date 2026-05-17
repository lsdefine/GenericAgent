import os
import unittest

from agentmain import GenericAgentRuntime


class MultiSessionRuntimeTests(unittest.TestCase):
    def test_runtime_isolates_session_state(self):
        runtime = GenericAgentRuntime()
        a = runtime.get_or_create("chat:root-a", metadata={"chat_id": "chat", "root_message_id": "root-a"})
        b = runtime.get_or_create("chat:root-b", metadata={"chat_id": "chat", "root_message_id": "root-b"})

        self.assertIs(a, runtime.get_or_create("chat:root-a"))
        self.assertIsNot(a, b)

        a.agent.history.append("A only")
        b.agent.history.append("B only")
        a.add_document(__file__)

        self.assertEqual(a.agent.history, ["A only"])
        self.assertEqual(b.agent.history, ["B only"])
        self.assertEqual(len(a.documents), 1)
        self.assertEqual(b.documents, [])

    def test_runtime_uses_same_ga_installation_assets(self):
        runtime = GenericAgentRuntime()
        session = runtime.get_or_create("chat:root")
        root = os.path.dirname(os.path.dirname(__file__))
        self.assertTrue(os.path.isdir(os.path.join(root, "memory")))
        self.assertIsNotNone(session.agent.task_queue)


if __name__ == "__main__":
    unittest.main()
