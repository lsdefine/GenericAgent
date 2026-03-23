import os, sys, re, threading, asyncio, queue as Q, socket, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TEMP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'temp')
from agentmain import GeneraticAgent
try:
    from telegram import Update
    from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes
    from telegram.request import HTTPXRequest
except:
    print("Please ask the agent install python-telegram-bot to use telegram module.")
    sys.exit(1)
from llmcore import mykeys

agent = GeneraticAgent()
agent.verbose = False
ALLOWED = set(mykeys.get('tg_allowed_users', []))

_TAG_PATS = [r'<' + t + r'>.*?</' + t + r'>' for t in ('thinking', 'summary', 'tool_use')]
_TAG_PATS.append(r'<file_content>.*?</file_content>')

def _clean(t):
    for p in _TAG_PATS:
        t = re.sub(p, '', t, flags=re.DOTALL)
    return re.sub(r'\n{3,}', '\n\n', t).strip() or '...'

import html as _html
def _inline_md(s):
    s = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', s)
    s = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<i>\1</i>', s)
    s = re.sub(r'`([^`]+)`', r'<code>\1</code>', s)
    return s
def _to_html(t):
    parts, pos = [], 0
    for m in re.finditer(r'(`{3,})(?:\w*\n)?([\s\S]*?)\1', t):
        parts.append(_inline_md(_html.escape(t[pos:m.start()])))
        parts.append('<pre><code>' + _html.escape(m.group(2)) + '</code></pre>')
        pos = m.end()
    parts.append(_inline_md(_html.escape(t[pos:])))
    return ''.join(parts)

async def _stream(dq, msg):
    last_text = ""
    while True:
        await asyncio.sleep(3)
        item = None
        try:
            while True: item = dq.get_nowait()
        except Q.Empty: pass
        if item is None: continue
        raw = item.get("done") or item.get("next", "")
        done = "done" in item
        show = _clean(raw)
        if len(show) > 4000:
            # freeze current msg, start a new one
            try: msg = await msg.reply_text("(continued...)")
            except Exception: pass
            last_text = ""
            show = show[-3900:]
        display = show if done else show + " ⏳"
        if display != last_text:
            try: await msg.edit_text(_to_html(display), parse_mode='HTML')
            except Exception:
                try: await msg.edit_text(display)
                except Exception: pass
            last_text = display
        if done:
            files = re.findall(r'\[FILE:([^\]]+)\]', show[-1000:])
            for fpath in files:
                if not os.path.isabs(fpath): fpath = os.path.join(_TEMP_DIR, fpath)
                if os.path.exists(fpath):
                    if fpath.lower().endswith(('.png','.jpg','.jpeg','.gif','.webp')):
                        try: await msg.reply_photo(open(fpath,'rb'))
                        except Exception: pass
                    else:
                        try: await msg.reply_document(open(fpath,'rb'))
                        except Exception: pass
            show = re.sub(r'\[FILE:[^\]]+\]', '', show)
            if show.strip():
                try: await msg.edit_text(_to_html(show), parse_mode='HTML')
                except Exception:
                    try: await msg.edit_text(show)
                    except Exception: pass
            break

async def handle_msg(update, ctx):
    uid = update.effective_user.id
    if ALLOWED and uid not in ALLOWED:
        return await update.message.reply_text("no")
    msg = await update.message.reply_text("thinking...")
    prompt = f"If you need to show files to user, use [FILE:filepath] in your response.\n\n{update.message.text}"
    dq = agent.put_task(prompt, source="telegram")
    task = asyncio.create_task(_stream(dq, msg))
    ctx.user_data['stream_task'] = task

async def cmd_abort(update, ctx):
    agent.abort()
    task = ctx.user_data.get('stream_task')
    if task and not task.done():
        task.cancel()
    await update.message.reply_text("Aborted")

async def cmd_llm(update, ctx):
    args = (update.message.text or '').split()
    if len(args) > 1:
        try:
            n = int(args[1])
            agent.next_llm(n)
            await update.message.reply_text(f"Switched to [{agent.llm_no}] {agent.get_llm_name()}")
        except (ValueError, IndexError):
            await update.message.reply_text(f"Usage: /llm <0-{len(agent.list_llms())-1}>")
    else:
        lines = [f"{'→' if cur else '  '} [{i}] {name}" for i, name, cur in agent.list_llms()]
        await update.message.reply_text("LLMs:\n" + "\n".join(lines))

if __name__ == '__main__':
    # Single instance lock using socket
    try:
        _lock_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM); _lock_sock.bind(('127.0.0.1', 19527))
    except OSError: 
        print('[Telegram] Another instance is already running, skiping...')
        sys.exit(1)
    if not ALLOWED: 
        print('[Telegram] ERROR: tg_allowed_users in mykey.py is empty or missing. Set it to avoid unauthorized access.')
        sys.exit(1)
    _logf = open(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'temp', 'tgapp.log'), 'a', encoding='utf-8', buffering=1)
    sys.stdout = sys.stderr = _logf
    print('[NEW] New process starting, the above are history infos ...')
    threading.Thread(target=agent.run, daemon=True).start()
    proxy = mykeys.get('proxy', 'http://127.0.0.1:2082')
    print('proxy:', proxy)

    async def _error_handler(update, context: ContextTypes.DEFAULT_TYPE):
        print(f"[{time.strftime('%m-%d %H:%M')}] TG error: {context.error}", flush=True)

    while True:
        try:
            print(f"TG bot starting... {time.strftime('%m-%d %H:%M')}")
            # Recreate request and app objects on each restart to avoid stale connections
            request = HTTPXRequest(proxy=proxy, read_timeout=30, write_timeout=30, connect_timeout=30, pool_timeout=30)
            app = (ApplicationBuilder()
                   .token(mykeys['tg_bot_token'])
                   .request(request)
                   .get_updates_request(request)
                   .build())
            app.add_handler(CommandHandler("stop", cmd_abort))
            app.add_handler(CommandHandler("llm", cmd_llm))
            app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
            app.add_error_handler(_error_handler)
            
            app.run_polling(
                drop_pending_updates=True,
                poll_interval=1.0,
                timeout=30,
            )
        except Exception as e:
            print(f"[{time.strftime('%m-%d %H:%M')}] polling crashed: {e}", flush=True)
            time.sleep(10)
            asyncio.set_event_loop(asyncio.new_event_loop())
