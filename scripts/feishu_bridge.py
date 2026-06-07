#!/usr/bin/env python3
"""
feishu_bridge.py — 飞书/Lark 消息桥接模块

为 GA 各模块提供飞书通知能力：
  - send_message()      — 发送文本消息到指定会话
  - send_alert()        — 发送告警消息（供 auto_repair 等调用，与 agentmail_bridge 接口对齐）
  - list_unread()       — 列出未读消息
  - list_chats()        — 列出可用会话
  - check_status()      — 检查 lark-cli 绑定状态

用法:
    from scripts.feishu_bridge import FeishuBridge
    bridge = FeishuBridge()
    bridge.send_alert("disk_usage", "磁盘使用率 85%")

依赖: lark-cli (https://github.com/larksuite/cli), 需先绑定身份
  lark-cli config bind  # 需要用户确认
"""

import os, sys, json, subprocess, logging, time
from datetime import datetime
from typing import Optional, List, Dict, Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("feishu_bridge")

# 默认告警接收会话ID（需用户设置）
DEFAULT_ALERT_CHAT_ID = os.environ.get("FEISHU_ALERT_CHAT_ID", "")

# lark-cli 路径
LARK_CLI = "/usr/local/bin/lark-cli"

# ── 飞书 Open API 直接模式（替代 lark-cli，无需用户交互绑定） ──
# 优先级: mykey.py > 环境变量 FEISHU_APP_ID/FEISHU_APP_SECRET > None
_FS_APP_ID = None
_FS_APP_SECRET = None
_FS_CHAT_ID = None

# 首选: mykey.py
try:
    _GA_HOME = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _sys_path_backup = list(sys.path)
    sys.path.insert(0, _GA_HOME)
    import mykey
    _FS_APP_ID = getattr(mykey, 'fs_app_id', None)
    _FS_APP_SECRET = getattr(mykey, 'fs_app_secret', None)
    if hasattr(mykey, 'agent_api_keys'):
        _FS_CHAT_ID = mykey.agent_api_keys.get("FEISHU_CHAT_ID", "")
    sys.path = _sys_path_backup
except Exception:
    pass

# 回退: 环境变量
if not _FS_APP_ID or not _FS_APP_SECRET:
    _FS_APP_ID = os.environ.get("FEISHU_APP_ID", _FS_APP_ID)
    _FS_APP_SECRET = os.environ.get("FEISHU_APP_SECRET", _FS_APP_SECRET)
if not _FS_CHAT_ID:
    _FS_CHAT_ID = os.environ.get("FEISHU_HOME_CHANNEL", _FS_CHAT_ID)

# Token 缓存
_DIRECT_TOKEN = None
_DIRECT_TOKEN_EXPIRY = 0  # Unix timestamp


class FeishuBridge:
    """飞书消息桥接 (支持 lark-cli + 直连 API 双模式)"""

    def __init__(self, chat_id: Optional[str] = None):
        self._chat_id = chat_id or DEFAULT_ALERT_CHAT_ID
        self._lark_cli = LARK_CLI
        self._direct_ok = False
        self._direct_error = None
        self._init_direct_api()

    # ── 底层调用 ──

    def _run_lark(self, args: List[str], timeout: int = 15) -> dict:
        """执行 lark-cli 命令并返回解析后的 JSON"""
        cmd = [self._lark_cli] + args
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               encoding="utf-8", errors="replace",
                               timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": {"type": "timeout", "message": f"lark-cli 超时 ({timeout}s)"}}
        except FileNotFoundError:
            return {"ok": False, "error": {"type": "not_found", "message": f"lark-cli 未找到: {self._lark_cli}"}}

        # 尝试解析 JSON
        try:
            result = json.loads(r.stdout)
        except json.JSONDecodeError:
            result = {"ok": False, "error": {"type": "parse_error",
                      "message": f"lark-cli 输出无法解析", "raw": r.stdout[:500]}}
        return result

    def _check_bound(self) -> bool:
        """检查 lark-cli 是否已绑定身份"""
        r = self._run_lark(["config", "show"])
        if r.get("ok"):
            return True
        error_msg = r.get("error", {}).get("message", "")
        if "not bound" in error_msg or "hermes context" in error_msg:
            return False
        # 其他错误也视为未就绪
        return False

    # ── 飞书 Open API 直接模式 ──

    def _init_direct_api(self) -> None:
        """初始化直接 API 模式所需凭证"""
        global _FS_APP_ID, _FS_APP_SECRET, _FS_CHAT_ID
        if _FS_APP_ID and _FS_APP_SECRET:
            # 如果未指定 chat_id，从 mykey 获取默认值
            if not self._chat_id and _FS_CHAT_ID:
                self._chat_id = _FS_CHAT_ID
            self._direct_ok = True
            log.info(f"直连 API 已就绪 (chat_id={self._chat_id})")
        else:
            self._direct_ok = False
            self._direct_error = "mykey.py 中未配置 fs_app_id/fs_app_secret"

    def _direct_api_get_token(self) -> Optional[str]:
        """获取 tenant_access_token（带缓存）

        Returns:
            token 字符串，失败返回 None
        """
        global _DIRECT_TOKEN, _DIRECT_TOKEN_EXPIRY
        now = time.time()

        # 如果缓存未过期，直接返回
        if _DIRECT_TOKEN and now < _DIRECT_TOKEN_EXPIRY - 60:
            return _DIRECT_TOKEN

        if not _FS_APP_ID or not _FS_APP_SECRET:
            self._direct_error = "fs_app_id 或 fs_app_secret 未配置"
            return None

        try:
            import requests
            resp = requests.post(
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": _FS_APP_ID, "app_secret": _FS_APP_SECRET},
                timeout=10
            )
            if resp.status_code != 200:
                self._direct_error = f"Token 接口 HTTP {resp.status_code}"
                return None
            data = resp.json()
            if data.get("code") != 0:
                self._direct_error = f"Token 接口返回错误: {data.get('msg', 'unknown')}"
                return None

            token = data.get("tenant_access_token", "")
            expire = data.get("expire", 7200)  # 默认 2 小时
            _DIRECT_TOKEN = token
            _DIRECT_TOKEN_EXPIRY = now + expire
            self._direct_error = None
            return token
        except Exception as e:
            self._direct_error = f"获取 Token 异常: {e}"
            return None

    def _direct_api_send_message(self, text: str,
                                  chat_id: Optional[str] = None,
                                  msg_type: str = "text") -> bool:
        """通过飞书 Open API 直接发送消息

        Args:
            text: 消息内容
            chat_id: 目标会话 ID，默认使用 self._chat_id
            msg_type: 消息类型 (text/post/interactive)

        Returns:
            True 表示发送成功
        """
        cid = chat_id or self._chat_id
        if not cid:
            log.error("直连发送: 未指定 chat_id")
            return False

        token = self._direct_api_get_token()
        if not token:
            log.error(f"直连发送: 获取 Token 失败 - {self._direct_error}")
            return False

        try:
            import requests
            # 消息内容需要 JSON 序列化的字符串
            content = json.dumps({"text": text})
            payload = {
                "receive_id": cid,
                "msg_type": msg_type,
                "content": content
            }
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=utf-8"
            }
            resp = requests.post(
                "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
                json=payload, headers=headers, timeout=15
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == 0:
                    log.info(f"直连发送成功 → {cid}")
                    return True
                else:
                    self._direct_error = f"发送接口返回错误: code={data.get('code')} msg={data.get('msg')}"
                    log.error(f"直连发送失败: {self._direct_error}")
                    return False
            else:
                self._direct_error = f"发送接口 HTTP {resp.status_code}: {resp.text[:200]}"
                log.error(f"直连发送失败: {self._direct_error}")
                return False
        except Exception as e:
            self._direct_error = f"发送消息异常: {e}"
            log.error(f"直连发送异常: {e}")
            return False

    # ── 公共 API ──

    def check_status(self) -> dict:
        """检查飞书通道状态

        Returns:
            {"bound": bool, "direct_api": bool, "chat_id": str,
             "lark_cli": str, "direct_error": str or None, "error": str or None}
        """
        bound = self._check_bound()
        direct_ready = self._direct_ok and bool(self._direct_api_get_token())

        # 测试直连发送
        direct_test = "未测试"
        if direct_ready:
            direct_test = "就绪"
        elif self._direct_ok:
            direct_test = f"Token 失败: {self._direct_error}"

        result = {
            "bound": bound,
            "direct_api": self._direct_ok,
            "direct_api_ready": direct_ready,
            "direct_test": direct_test,
            "chat_id": self._chat_id or "(未设置)",
            "lark_cli": self._lark_cli,
        }

        errors = []
        if not bound:
            errors.append("lark-cli 未绑定身份")
        if not self._direct_ok:
            errors.append(f"直连 API 未就绪: {self._direct_error or '未知'}")
        elif not direct_ready:
            errors.append(f"直连 Token 获取失败: {self._direct_error}")
        if not self._chat_id:
            errors.append("FEISHU_ALERT_CHAT_ID 未设置")

        if errors:
            result["error"] = "\n".join(errors)
        return result

    def list_chats(self, limit: int = 20) -> List[Dict]:
        """列出当前会话列表

        Returns:
            [{"chat_id": str, "name": str, ...}, ...]
            或 空列表 + log warning
        """
        r = self._run_lark(["im", "+chat-list", "--page-size", str(limit)])
        if not r.get("ok"):
            log.warning(f"list_chats 失败: {r.get('error', {}).get('message', 'unknown')}")
            return []
        items = r.get("data", {}).get("items", [])
        return items

    def send_message(self, text: str, chat_id: Optional[str] = None,
                     msg_type: str = "text") -> bool:
        """发送消息到指定会话

        Args:
            text: 消息内容（支持 markdown）
            chat_id: 目标会话ID，默认使用构造时或环境变量中的 chat_id
            msg_type: 消息类型 (text/markdown)

        Returns:
            True 表示发送成功, False 表示失败
        """
        cid = chat_id or self._chat_id
        if not cid:
            log.error("send_message: 未指定 chat_id，请设置 FEISHU_ALERT_CHAT_ID 或传入 chat_id")
            return False

        # ── 策略1: lark-cli ──
        data = json.dumps({
            "msg_type": msg_type,
            "content": json.dumps({"text": text}) if msg_type == "text" else json.dumps({"text": text})
        })

        r = self._run_lark([
            "im", "+messages-send",
            "--chat-id", cid,
            "--data", data
        ])
        if r.get("ok"):
            log.info(f"[lark-cli] 消息已发送到 {cid}")
            return True

        # lark-cli 失败，日志记录但不放弃
        error_msg = r.get("error", {}).get("message", "未知错误")
        log.warning(f"[lark-cli] 发送失败 [{error_msg}]，尝试直连 API...")

        # ── 策略2: 飞书 Open API 直连 ──
        if self._direct_ok:
            ok = self._direct_api_send_message(text, cid, msg_type)
            if ok:
                return True
            log.warning(f"[直连API] 也失败: {self._direct_error}")

        # 全部失败
        log.error(f"所有发送途径均失败 (lark-cli={error_msg}, direct={self._direct_error})")
        return False

    def send_alert(self, alert_type: str, message: str,
                   severity: str = "warning", **kwargs) -> bool:
        """发送告警消息（与 agentmail_bridge 接口对齐）

        Args:
            alert_type: 告警类型 (disk_usage, memory, oom, etc.)
            message: 告警内容
            severity: 严重级别 (info/warning/critical)

        Returns:
            True 表示发送成功
        """
        emoji_map = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}
        emoji = emoji_map.get(severity, "📢")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        text = (
            f"{emoji} *[{severity.upper()}] {alert_type}*\n"
            f"时间: {timestamp}\n"
            f"消息: {message}"
        )
        return self.send_message(text, msg_type="text")

    def list_unread(self, chat_id: Optional[str] = None,
                    limit: int = 10) -> List[Dict]:
        """列出会话中最近的未读消息

        Args:
            chat_id: 会话ID，默认使用 alert_chat_id
            limit: 最大消息数

        Returns:
            [{"message_id": str, "sender": str, "text": str, ...}, ...]
        """
        cid = chat_id or self._chat_id
        if not cid:
            log.error("list_unread: 未指定 chat_id")
            return []

        r = self._run_lark([
            "im", "+chat-messages-list",
            "--chat-id", cid,
            "--page-size", str(limit),
            "--sort", "desc"
        ])
        if not r.get("ok"):
            log.warning(f"list_unread 失败: {r.get('error', {}).get('message', 'unknown')}")
            return []
        items = r.get("data", {}).get("items", [])
        return items


# ── 快捷函数（供其他模块 import 直接使用） ──

def send_alert(alert_type: str, message: str, severity: str = "warning") -> bool:
    """快捷发送告警"""
    bridge = FeishuBridge()
    return bridge.send_alert(alert_type, message, severity)


def send_message(text: str, chat_id: Optional[str] = None) -> bool:
    """快捷发送消息"""
    bridge = FeishuBridge(chat_id=chat_id)
    return bridge.send_message(text)


def check_status() -> dict:
    """快捷检查状态"""
    bridge = FeishuBridge()
    return bridge.check_status()


if __name__ == "__main__":
    # 命令行使用
    import sys as _sys
    if len(_sys.argv) < 2:
        print("用法: python3 feishu_bridge.py <status|send|alert|chats> [args...]")
        print("  status              → 检查飞书通道状态")
        print("  send <text>         → 发送文本消息")
        print("  alert <type> <msg>  → 发送告警")
        print("  chats               → 列出会话")
        _sys.exit(0)

    cmd = _sys.argv[1]
    bridge = FeishuBridge()

    if cmd == "status":
        s = bridge.check_status()
        print(json.dumps(s, indent=2, ensure_ascii=False))
    elif cmd == "send":
        if len(_sys.argv) < 3:
            print("请提供消息内容")
            _sys.exit(1)
        ok = bridge.send_message(" ".join(_sys.argv[2:]))
        print("✅ 发送成功" if ok else "❌ 发送失败")
    elif cmd == "alert":
        if len(_sys.argv) < 4:
            print("用法: feishu_bridge.py alert <type> <message>")
            _sys.exit(1)
        ok = bridge.send_alert(_sys.argv[2], " ".join(_sys.argv[3:]))
        print("✅ 告警已发送" if ok else "❌ 告警发送失败")
    elif cmd == "chats":
        chats = bridge.list_chats()
        print(json.dumps(chats, indent=2, ensure_ascii=False) if chats else "无会话或未绑定")
    elif cmd == "unread":
        msgs = bridge.list_unread()
        print(json.dumps(msgs, indent=2, ensure_ascii=False) if msgs else "无消息或未绑定")
    else:
        print(f"未知命令: {cmd}")
