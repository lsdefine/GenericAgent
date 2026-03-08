import os, sys, threading, asyncio, time, re, json
import queue as Q
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT); os.chdir(PROJECT_ROOT)
import lark_oapi as lark
from lark_oapi.api.im.v1 import *
from lark_oapi.api.contact.v3 import *
from agentmain import GeneraticAgent
import mykey
_TAG_PATS = [r'<' + t + r'>.*?</' + t + r'>' for t in ('thinking', 'summary', 'tool_use', 'file_content')]
def _clean(t):
    for p in _TAG_PATS: t = re.sub(p, '', t, flags=re.DOTALL)
    return re.sub(r'\n{3,}', '\n\n', t).strip() or '...'
APP_ID, APP_SECRET = getattr(mykey, 'fs_app_id', None), getattr(mykey, 'fs_app_secret', None)
ALLOWED_USERS = set(getattr(mykey, 'fs_allowed_users', []))
agent = GeneraticAgent()
threading.Thread(target=agent.run, daemon=True).start()
client, user_tasks = None, {}
def create_client():
    return lark.Client.builder().app_id(APP_ID).app_secret(APP_SECRET).log_level(lark.LogLevel.INFO).build()
_card = lambda t: json.dumps({"config": {"wide_screen_mode": True}, "elements": [{"tag": "markdown", "content": t}]})
def send_message(open_id, content, msg_type="text", use_card=False):
    ct, mt = (_card(content), "interactive") if use_card else (json.dumps({"text": content}), "text")
    body = CreateMessageRequest.builder().receive_id_type("open_id").request_body(
        CreateMessageRequestBody.builder().receive_id(open_id).msg_type(mt).content(ct).build()).build()
    r = client.im.v1.message.create(body)
    return r.data.message_id if r.success() else (print(f"发送失败: {r.code}, {r.msg}"), None)[1]
def update_message(message_id, content):
    body = PatchMessageRequest.builder().message_id(message_id).request_body(
        PatchMessageRequestBody.builder().content(_card(content)).build()).build()
    r = client.im.v1.message.patch(body)
    if not r.success(): print(f"[ERROR] update_message 失败: {r.code}, {r.msg}")
    return r.success()
def handle_message(data):
    event, message, sender = data.event, data.event.message, data.event.sender
    open_id, msg_type = sender.sender_id.open_id, message.message_type
    if ALLOWED_USERS and open_id not in ALLOWED_USERS: return print(f"未授权用户: {open_id}")
    if msg_type != "text": return send_message(open_id, "⚠️ 目前只支持文本消息")
    text = json.loads(message.content).get("text", "").strip()
    if not text: return
    print(f"收到消息 [{open_id}]: {text}")
    if text.startswith("/"): return handle_command(open_id, text)
    def run_agent():
        user_tasks[open_id] = {'running': True}
        try:
            msg_id, dq, last_text = send_message(open_id, "思考中...", use_card=True), agent.put_task(text, source='feishu'), ""
            while user_tasks.get(open_id, {}).get('running', False):
                time.sleep(3)
                item = None
                try:
                    while True: item = dq.get_nowait()
                except: pass
                if item is None: continue
                raw, done = item.get("done") or item.get("next", ""), "done" in item
                show = _clean(raw)
                if len(show) > 3500:
                    # 智能截断：避免切断代码块
                    cut = show[-3000:]
                    if cut.count('```') % 2 == 1: cut = '```\n' + cut  # 补开头
                    msg_id, last_text, show = send_message(open_id, "(继续...)", use_card=True), "", cut
                display = show if done else show + " ⏳"
                if display != last_text and msg_id: update_message(msg_id, display); last_text = display
                if done: break
            if not user_tasks.get(open_id, {}).get('running', True): send_message(open_id, "⏹️ 已停止")
        except Exception as e:
            import traceback; print(f"[ERROR] run_agent 异常: {e}"); traceback.print_exc()
            send_message(open_id, f"❌ 错误: {str(e)}")
        finally: user_tasks.pop(open_id, None)
    threading.Thread(target=run_agent, daemon=True).start()
def handle_command(open_id, cmd):
    import glob
    if cmd == "/stop":
        if open_id in user_tasks: user_tasks[open_id]['running'] = False
        agent.abort(); send_message(open_id, "⏹️ 正在停止...")
    elif cmd == "/help":
        send_message(open_id, "📖 命令列表:\n/stop - 停止当前任务\n/status - 查看状态\n/restore - 恢复上次对话历史\n/new - 开启新对话\n/help - 显示帮助")
    elif cmd == "/status":
        send_message(open_id, f"状态: {'🟢 空闲' if not agent.is_busy() else '🔴 运行中'}")
    elif cmd == "/restore":
        try:
            files = glob.glob('./temp/model_responses_*.txt')
            if not files: return send_message(open_id, "❌ 没有找到历史记录")
            latest = max(files, key=os.path.getmtime)
            with open(latest, 'r', encoding='utf-8') as f: content = f.read()
            users = re.findall(r'=== USER ===\n(.+?)(?==== |$)', content, re.DOTALL)
            resps = re.findall(r'=== Response ===.*?\n(.+?)(?==== Prompt|$)', content, re.DOTALL)
            count = 0
            for u, r in zip(users, resps):
                u, r = u.strip(), r.strip()[:500]
                if u and r: agent.history.extend([f"[USER]: {u}", f"[Agent] {r}"]); count += 1
            agent.abort()
            send_message(open_id, f"✅ 已恢复 {count} 轮对话\n来源: {os.path.basename(latest)}\n(仅恢复上下文，请输入新问题继续)")
        except Exception as e: send_message(open_id, f"❌ 恢复失败: {e}")
    else: send_message(open_id, f"❓ 未知命令: {cmd}")
def main():
    global client
    if not APP_ID or not APP_SECRET: print("错误: 请在 mykey.py 中配置 fs_app_id 和 fs_app_secret"); sys.exit(1)
    client = create_client()
    handler = lark.EventDispatcherHandler.builder("", "").register_p2_im_message_receive_v1(handle_message).build()
    cli = lark.ws.Client(APP_ID, APP_SECRET, event_handler=handler, log_level=lark.LogLevel.INFO)
    print("=" * 50 + "\n飞书 Agent 已启动（长连接模式）\n" + f"App ID: {APP_ID}\n等待消息...\n" + "=" * 50)
    cli.start()
if __name__ == "__main__": main()