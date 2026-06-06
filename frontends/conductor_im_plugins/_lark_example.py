"""飞书：lark-cli 轮询 config.local.json {"lark_chat_ids": [...]} 中的会话，INTERVAL 内有新消息 → 触发。"""
import glob, json, os, subprocess, time

INTERVAL = 300

PROMPT = """\
你是飞书采集subagent。先读记忆中用户画像，再用 lark-cli 查看最近消息（详见 lark_cli_sop；会话ID取本插件目录 config.local.json 的 lark_chat_ids，逐个 `lark-cli im +chat-messages-list --as user --chat-id <id> --sort desc --page-size 10`），挑出刚出现的新消息，过滤后汇报值得关注项并补全上下文。
不执行外部动作；无值得关注的就一句话说明。"""

_CFG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.local.json")
_NODE = glob.glob(os.path.expandvars(r"%APPDATA%\fnm\node-versions\*\installation"))  # lark-cli在fnm node下


def check() -> bool:
    cfg = json.load(open(_CFG, encoding="utf-8")) if os.path.exists(_CFG) else {}
    env = {**os.environ, "PATH": os.pathsep.join(_NODE + [os.environ.get("PATH", "")])}
    start = int(time.time()) - INTERVAL - 5
    for cid in cfg.get("lark_chat_ids", []):
        r = subprocess.run(
            f"lark-cli im +chat-messages-list --as user --chat-id {cid} --start {start} --page-size 1",
            shell=True, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
        try:
            if json.loads(r.stdout)["data"]["total"]:
                return True
        except Exception:
            pass
    return False
