#!/usr/bin/env python3
"""
DingTalk notification sender for GA (Generic Agent).

Usage:
    python scripts/dingtalk_notifier.py send <chat_id> <message>
    python scripts/dingtalk_notifier.py send-group <open_conversation_id> <message>

Requires: dingtalk_client_id & dingtalk_client_secret configured in mykeys.
Run `python assets/configure_mykey.py` to set up DingTalk credentials.

For the full interactive DingTalk bot, use: python frontends/dingtalkapp.py
"""

import asyncio
import json
import os
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from llmcore import mykeys


CLIENT_ID = str(mykeys.get("dingtalk_client_id", "") or "").strip()
CLIENT_SECRET = str(mykeys.get("dingtalk_client_secret", "") or "").strip()
CONFIGURED = bool(CLIENT_ID and CLIENT_SECRET)


class DingTalkNotifier:
    """Send-only DingTalk notifier. Does NOT require dingtalk-stream package."""

    def __init__(self):
        self.access_token = None
        self.token_expiry = 0

    def _get_access_token(self):
        """Fetch OAuth2 access token from DingTalk API."""
        if not CONFIGURED:
            raise RuntimeError(
                "DingTalk not configured. Run: python assets/configure_mykey.py\n"
                "Set dingtalk_client_id (AppKey) and dingtalk_client_secret (AppSecret)."
            )
        if self.access_token and time.time() < self.token_expiry:
            return self.access_token

        resp = requests.post(
            "https://api.dingtalk.com/v1.0/oauth2/accessToken",
            json={"appKey": CLIENT_ID, "appSecret": CLIENT_SECRET},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        self.access_token = data.get("accessToken")
        self.token_expiry = time.time() + int(data.get("expireIn", 7200)) - 60
        return self.access_token

    def send_text(self, chat_id: str, text: str) -> bool:
        """Send text message. chat_id: user StaffID or 'group:{openConversationId}'."""
        token = self._get_access_token()
        headers = {"x-acs-dingtalk-access-token": token}

        if chat_id.startswith("group:"):
            url = "https://api.dingtalk.com/v1.0/robot/groupMessages/send"
            payload = {
                "robotCode": CLIENT_ID,
                "openConversationId": chat_id[6:],
                "msgKey": "sampleMarkdown",
                "msgParam": json.dumps({"text": text, "title": "GA Notification"}, ensure_ascii=False),
            }
        else:
            url = "https://api.dingtalk.com/v1.0/robot/oToMessages/batchSend"
            payload = {
                "robotCode": CLIENT_ID,
                "userIds": [chat_id],
                "msgKey": "sampleMarkdown",
                "msgParam": json.dumps({"text": text, "title": "GA Notification"}, ensure_ascii=False),
            }

        resp = requests.post(url, json=payload, headers=headers, timeout=20)
        body = resp.text
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code}: {body[:300]}")
        result = resp.json() if "json" in resp.headers.get("content-type", "") else {}
        errcode = result.get("errcode")
        if errcode not in (None, 0):
            raise RuntimeError(f"API errcode={errcode}: {body[:300]}")
        return True

    def send_group(self, open_conversation_id: str, text: str) -> bool:
        """Convenience: send to group by openConversationId."""
        return self.send_text(f"group:{open_conversation_id}", text)


def main():
    if not CONFIGURED:
        print("[DingTalk] ⚠️  Not configured. Set dingtalk_client_id & dingtalk_client_secret in mykeys.")
        print("  Run: python assets/configure_mykey.py")
        return 1

    if len(sys.argv) < 3:
        print("Usage:")
        print(f"  {sys.argv[0]} send <user_staff_id> <message>")
        print(f"  {sys.argv[0]} send-group <open_conversation_id> <message>")
        return 1

    cmd = sys.argv[1]
    target = sys.argv[2]
    message = " ".join(sys.argv[3:]) if len(sys.argv) > 3 else ""

    if not message:
        # Read from stdin if no message arg
        message = sys.stdin.read().strip()

    if not message:
        print("Error: no message provided")
        return 1

    notifier = DingTalkNotifier()
    try:
        if cmd == "send":
            notifier.send_text(target, message)
            print(f"[DingTalk] ✅ Message sent to user {target}")
        elif cmd == "send-group":
            notifier.send_group(target, message)
            print(f"[DingTalk] ✅ Message sent to group {target}")
        else:
            print(f"Unknown command: {cmd}")
            return 1
    except Exception as e:
        print(f"[DingTalk] ❌ Failed: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
