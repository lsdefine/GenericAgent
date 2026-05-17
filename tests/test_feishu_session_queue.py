
import json
import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontends")))

import frontends.fsapp as fsapp


class _Obj:
    pass


def _event(message_id, text):
    data = _Obj()
    data.event = _Obj()
    data.event.message = _Obj()
    data.event.sender = _Obj()
    data.event.sender.sender_id = _Obj()
    data.event.sender.sender_id.open_id = "user-1"
    msg = data.event.message
    msg.chat_id = "chat-1"
    msg.message_id = message_id
    msg.message_type = "text"
    msg.content = json.dumps({"text": text})
    msg.root_id = "root-1"
    msg.parent_id = "root-1"
    msg.thread_id = "root-1"
    return data


class _FakeAgent:
    def __init__(self):
        self._turn_end_hooks = {}
        self.abort_count = 0

    def abort(self):
        self.abort_count += 1


class _FakeSession:
    def __init__(self, records):
        self.session_id = "chat:root-1"
        self.metadata = {"chat_id": "chat-1", "root_message_id": "root-1"}
        self.agent = _FakeAgent()
        self.records = records
        self.calls = 0

    def put_task(self, query, source="feishu", images=None):
        self.calls += 1
        call_no = self.calls
        self.records.append(("put_task", call_no, query))

        def complete():
            time.sleep(0.2 if call_no == 1 else 0.02)
            hook = self.agent._turn_end_hooks.get("fs_chat:root-1")
            if hook:
                response = type("Resp", (), {"content": f"final {call_no}"})()
                hook({"exit_reason": "done", "response": response})

        threading.Thread(target=complete, daemon=True).start()
        return None


class _FakeCard:
    counter = 0

    def __init__(self, receive_id, rid_type, reply_to_message_id=None):
        type(self).counter += 1
        self.msg_id = f"card-{type(self).counter}"
        self.reply_to_message_id = reply_to_message_id
        self.records.append(("card_init", self.msg_id, reply_to_message_id))

    def start(self):
        self.records.append(("card_start", self.msg_id, self.reply_to_message_id))

    def step(self, summary, detail=""):
        self.records.append(("card_step", self.msg_id, summary))

    def done(self, text):
        self.records.append(("card_done", self.msg_id, text))

    def fail(self, msg):
        self.records.append(("card_fail", self.msg_id, msg))


class FeishuSessionQueueTests(unittest.TestCase):
    def setUp(self):
        self.records = []
        fsapp.PUBLIC_ACCESS = True
        fsapp.user_tasks.clear()
        fsapp.session_aliases.clear()
        self.session = _FakeSession(self.records)
        self.originals = {
            "resolve_feishu_session": fsapp.resolve_feishu_session,
            "_reply_text": fsapp._reply_text,
            "_TaskCard": fsapp._TaskCard,
            "bind_feishu_session_message": fsapp.bind_feishu_session_message,
            "_send_generated_files": fsapp._send_generated_files,
        }
        fsapp.resolve_feishu_session = lambda open_id, chat_id, message: (self.session, self.session.calls == 0)
        fsapp._reply_text = lambda message_id, content: self.records.append(("ack", message_id, content))
        fsapp.bind_feishu_session_message = lambda session, message_id: self.records.append(("bind", message_id))
        fsapp._send_generated_files = lambda *args, **kwargs: None
        _FakeCard.counter = 0
        _FakeCard.records = self.records
        fsapp._TaskCard = _FakeCard

    def tearDown(self):
        for name, value in self.originals.items():
            setattr(fsapp, name, value)
        fsapp.user_tasks.clear()
        fsapp.session_aliases.clear()

    def test_active_topic_message_waits_for_current_card(self):
        fsapp.handle_message(_event("msg-1", "first task"))
        time.sleep(0.05)
        fsapp.handle_message(_event("msg-2", "second task"))
        time.sleep(0.5)

        self.assertIn(("ack", "root-1", "\u5df2\u653e\u5165\u672c\u8bdd\u9898\u961f\u5217\uff0c\u5f53\u524d\u4efb\u52a1\u5b8c\u6210\u540e\u4f1a\u7ee7\u7eed\u5904\u7406\u3002"), self.records)
        self.assertEqual(
            [record for record in self.records if record[0] == "put_task"],
            [("put_task", 1, "first task"), ("put_task", 2, "second task")],
        )
        self.assertLess(self.records.index(("card_done", "card-1", "final 1")), self.records.index(("card_start", "card-2", "root-1")))
        self.assertEqual([record for record in self.records if record[0] == "card_start"], [("card_start", "card-1", "root-1"), ("card_start", "card-2", "root-1")])


if __name__ == "__main__":
    unittest.main()
