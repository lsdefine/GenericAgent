# 飞书 Agent 应用 - fsapp.py
# 使用长连接模式（无需公网服务器）

import os, sys, threading, asyncio, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import lark_oapi as lark
from lark_oapi.api.im.v1 import *
from lark_oapi.api.contact.v3 import *

from agentmain import GeneraticAgent
import mykey
import re
import queue as Q

# ============ 清理标签（同tgapp.py）============
_TAG_PATS = [r'<' + t + r'>.*?</' + t + r'>' for t in ('thinking', 'summary', 'tool_use')]
_TAG_PATS.append(r'<file_content>.*?</file_content>')

def _clean(t):
    """清理输出中的标签，只保留用户可读内容"""
    for p in _TAG_PATS:
        t = re.sub(p, '', t, flags=re.DOTALL)
    return re.sub(r'\n{3,}', '\n\n', t).strip() or '...'

# ============ 配置 ============
APP_ID = getattr(mykey, 'fs_app_id', None)
APP_SECRET = getattr(mykey, 'fs_app_secret', None)
ALLOWED_USERS = set(getattr(mykey, 'fs_allowed_users', []))  # 允许的用户 open_id 列表

# ============ 全局变量 ============
agent = GeneraticAgent()
threading.Thread(target=agent.run, daemon=True).start()  # 启动 Agent 后台处理线程
client = None
user_tasks = {}  # user_id -> {'running': bool, 'round': int}

def create_client():
    """创建飞书客户端"""
    return lark.Client.builder() \
        .app_id(APP_ID) \
        .app_secret(APP_SECRET) \
        .log_level(lark.LogLevel.INFO) \
        .build()

def _make_card(text: str) -> str:
    """构建飞书卡片消息 JSON"""
    import json
    card = {
        "config": {"wide_screen_mode": True},
        "elements": [{"tag": "markdown", "content": text}]
    }
    return json.dumps(card)

def send_message(open_id: str, content: str, msg_type: str = "text", use_card: bool = False):
    """发送消息给用户。use_card=True时发卡片（可编辑）"""
    import json
    if use_card:
        content_json = _make_card(content)
        m_type = "interactive"
    else:
        content_json = json.dumps({"text": content})
        m_type = "text"
    
    body = CreateMessageRequest.builder() \
        .receive_id_type("open_id") \
        .request_body(CreateMessageRequestBody.builder()
            .receive_id(open_id)
            .msg_type(m_type)
            .content(content_json)
            .build()) \
        .build()
    
    response = client.im.v1.message.create(body)
    if not response.success():
        print(f"发送失败: {response.code}, {response.msg}")
        return None
    return response.data.message_id

def update_message(message_id: str, content: str):
    """更新卡片消息内容"""
    body = PatchMessageRequest.builder() \
        .message_id(message_id) \
        .request_body(PatchMessageRequestBody.builder()
            .content(_make_card(content))
            .build()) \
        .build()
    
    response = client.im.v1.message.patch(body)
    if not response.success():
        print(f"[ERROR] update_message 失败: {response.code}, {response.msg}")
    return response.success()

def handle_message(data: lark.im.v1.P2ImMessageReceiveV1):
    """处理收到的消息"""
    event = data.event
    message = event.message
    sender = event.sender
    
    open_id = sender.sender_id.open_id
    chat_type = message.chat_type  # p2p 或 group
    msg_type = message.message_type
    
    # 权限检查
    if ALLOWED_USERS and open_id not in ALLOWED_USERS:
        print(f"未授权用户: {open_id}")
        return
    
    # 只处理文本消息
    if msg_type != "text":
        send_message(open_id, "⚠️ 目前只支持文本消息")
        return
    
    # 解析消息内容
    import json
    content_json = json.loads(message.content)
    text = content_json.get("text", "").strip()
    
    if not text:
        return
    
    print(f"收到消息 [{open_id}]: {text}")
    
    # 处理命令
    if text.startswith("/"):
        handle_command(open_id, text)
        return
    
    # 提交任务给 Agent（同 tgapp.py 模式：单消息+不断更新）
    def run_agent():
        import time
        user_tasks[open_id] = {'running': True}
        
        try:
            # 先发一条卡片消息，后续不断更新它
            msg_id = send_message(open_id, "思考中...", use_card=True)
            dq = agent.put_task(text)
            last_text = ""
            
            while user_tasks.get(open_id, {}).get('running', False):
                time.sleep(3)  # 每3秒检查一次
                
                # 取出队列中所有待处理项
                item = None
                try:
                    while True:
                        item = dq.get_nowait()
                except:
                    pass
                
                if item is None:
                    continue
                
                # 获取内容
                raw = item.get("done") or item.get("next", "")
                done = "done" in item
                
                # 清理标签，只保留用户可读内容
                show = _clean(raw)
                
                # 超长处理：发新卡片消息继续
                if len(show) > 3500:
                    msg_id = send_message(open_id, "(继续...)", use_card=True)
                    last_text = ""
                    show = show[-3000:]
                
                # 显示内容（进行中加 ⏳）
                display = show if done else show + " ⏳"
                
                # 只有内容变化才更新
                if display != last_text and msg_id:
                    update_message(msg_id, display)
                    last_text = display
                
                if done:
                    break
            
            # 检查是否被用户停止
            if not user_tasks.get(open_id, {}).get('running', True):
                send_message(open_id, "⏹️ 已停止")
                
        except Exception as e:
            import traceback
            print(f"[ERROR] run_agent 异常: {e}")
            traceback.print_exc()
            send_message(open_id, f"❌ 错误: {str(e)}")
        finally:
            user_tasks.pop(open_id, None)
    
    # 在后台线程运行
    threading.Thread(target=run_agent, daemon=True).start()

def handle_command(open_id: str, cmd: str):
    """处理命令"""
    if cmd == "/stop":
        # 设置停止标志
        if open_id in user_tasks:
            user_tasks[open_id]['running'] = False
        agent.abort()
        send_message(open_id, "⏹️ 正在停止...")
    elif cmd == "/help":
        help_text = """📖 命令列表:
/stop - 停止当前任务
/status - 查看状态
/restore - 恢复上次对话历史
/help - 显示帮助"""
        send_message(open_id, help_text)
    elif cmd == "/status":
        status = "🟢 空闲" if not agent.is_busy() else "🔴 运行中"
        send_message(open_id, f"状态: {status}")
    elif cmd == "/restore":
        # 恢复上次对话历史
        import glob
        import re
        try:
            # 找最新的 model_responses 文件
            files = glob.glob('./temp/model_responses_*.txt')
            if not files:
                send_message(open_id, "❌ 没有找到历史记录")
                return
            latest = max(files, key=os.path.getmtime)
            
            # 解析文件
            with open(latest, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 提取 USER 和 Response 块
            user_pattern = r'=== USER ===\n(.+?)(?==== |$)'
            resp_pattern = r'=== Response ===.*?\n(.+?)(?==== Prompt|$)'
            
            users = re.findall(user_pattern, content, re.DOTALL)
            resps = re.findall(resp_pattern, content, re.DOTALL)
            
            # 恢复到 agent.history
            count = 0
            for u, r in zip(users, resps):
                u = u.strip()
                r = r.strip()[:500]  # 截断过长回复
                if u and r:
                    agent.history.append(f"[USER]: {u}")
                    agent.history.append(f"[Agent] {r}")
                    count += 1
            
            # 确保恢复后不会自动触发任务
            agent.abort()
            send_message(open_id, f"✅ 已恢复 {count} 轮对话\n来源: {os.path.basename(latest)}\n(仅恢复上下文，请输入新问题继续)")
        except Exception as e:
            send_message(open_id, f"❌ 恢复失败: {e}")
    else:
        send_message(open_id, f"❓ 未知命令: {cmd}")

def main():
    global client
    
    if not APP_ID or not APP_SECRET:
        print("错误: 请在 mykey.py 中配置 fs_app_id 和 fs_app_secret")
        sys.exit(1)
    
    client = create_client()
    
    # 创建事件处理器
    event_handler = lark.EventDispatcherHandler.builder("", "") \
        .register_p2_im_message_receive_v1(handle_message) \
        .build()
    
    # 使用 WebSocket 长连接模式
    cli = lark.ws.Client(
        APP_ID,
        APP_SECRET,
        event_handler=event_handler,
        log_level=lark.LogLevel.INFO
    )
    
    print("=" * 50)
    print("飞书 Agent 已启动（长连接模式）")
    print(f"App ID: {APP_ID}")
    print("等待消息...")
    print("=" * 50)
    
    # 启动长连接
    cli.start()

if __name__ == "__main__":
    main()