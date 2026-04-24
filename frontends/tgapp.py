import os, sys, re, threading, asyncio, queue as Q, socket, time, random
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TEMP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'temp')
from agentmain import GeneraticAgent
try:
    from telegram import BotCommand
    from telegram.constants import ChatType, MessageLimit, ParseMode
    from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
    from telegram.helpers import escape_markdown
    from telegram.request import HTTPXRequest
except:
    print("Please ask the agent install python-telegram-bot to use telegram module.")
    sys.exit(1)
from chatapp_common import (
    FILE_HINT,
    HELP_TEXT,
    TELEGRAM_MENU_COMMANDS,
    clean_reply,
    extract_files,
    format_restore,
    split_text,
    strip_files,
)
from continue_cmd import handle_frontend_command, reset_conversation
from llmcore import mykeys

agent = GeneraticAgent()
agent.verbose = False
agent.inc_out = True
ALLOWED = set(mykeys.get('tg_allowed_users', []))

_DRAFT_HINT = "thinking..."
_STREAM_SUFFIX = " ⏳"
_STREAM_SEGMENT_LIMIT = max(1200, MessageLimit.MAX_TEXT_LENGTH - 256)
_QUEUE_WAIT_SECONDS = 1
_MD_TOKEN_RE = re.compile(
    r"(`{3,})([A-Za-z0-9_+-]*)\n([\s\S]*?)\1"
    r"|\[([^\]]+)\]\(([^)\n]+)\)"
    r"|`([^`\n]+)`"
    r"|\*\*([^\n]+?)\*\*"
    r"|(?<!\*)\*(?!\*)([^\n]+?)(?<!\*)\*(?!\*)",
    re.DOTALL,
)

def _make_draft_id():
    return random.randint(1, 2**31 - 1)

def _visible_segments(text):
    text = (text or "").strip()
    return split_text(text, _STREAM_SEGMENT_LIMIT) if text else []

def _resolve_files(paths):
    files, seen = [], set()
    for fpath in paths:
        if not os.path.isabs(fpath):
            fpath = os.path.join(_TEMP_DIR, fpath)
        if fpath in seen or not os.path.exists(fpath):
            continue
        files.append(fpath)
        seen.add(fpath)
    return files


def _escape_pre(text):
    return escape_markdown(text or "", version=2, entity_type="pre")

def _escape_code(text):
    return escape_markdown(text or "", version=2, entity_type="code")

def _escape_link_target(text):
    return escape_markdown(text or "", version=2, entity_type="text_link")

def _to_markdown_v2(text):
    if not text:
        return ""
    parts, pos = [], 0
    for match in _MD_TOKEN_RE.finditer(text):
        parts.append(escape_markdown(text[pos:match.start()], version=2))
        if match.group(1):
            lang = re.sub(r"[^A-Za-z0-9_+-]", "", match.group(2) or "")
            code = _escape_pre(match.group(3) or "")
            header = f"```{lang}\n" if lang else "```\n"
            parts.append(f"{header}{code}\n```")
        elif match.group(4) is not None:
            label = escape_markdown(match.group(4), version=2)
            target = _escape_link_target(match.group(5))
            parts.append(f"[{label}]({target})")
        elif match.group(6) is not None:
            parts.append(f"`{_escape_code(match.group(6))}`")
        elif match.group(7) is not None:
            parts.append(f"*{escape_markdown(match.group(7), version=2)}*")
        elif match.group(8) is not None:
            parts.append(f"_{escape_markdown(match.group(8), version=2)}_")
        pos = match.end()
    parts.append(escape_markdown(text[pos:], version=2))
    return "".join(parts)

def _is_not_modified_error(exc):
    return "not modified" in str(exc).lower()

class _TelegramStreamSession:
    def __init__(self, root_msg):
        self.root_msg = root_msg
        self.private_chat = getattr(getattr(root_msg, "chat", None), "type", "") == ChatType.PRIVATE
        self.can_use_draft = self.private_chat
        self.draft_id = _make_draft_id()
        self.live_msg = None
        self.raw_text = ""
        self.files = []
        self.sent_segments = 0
        self.active_display = ""

    async def prime(self):
        if self.can_use_draft and await self._send_draft(_DRAFT_HINT):
            self.active_display = _DRAFT_HINT
            return
        await self._upsert_live_message(_DRAFT_HINT)
        self.active_display = _DRAFT_HINT

    async def add_chunk(self, chunk):
        if not chunk:
            return
        self.raw_text += chunk
        await self._refresh(done=False, send_files=False)

    async def finalize(self, full_text=None, send_files=True):
        if full_text is not None:
            self.raw_text = full_text
        await self._refresh(done=True, send_files=send_files)

    async def finish_with_notice(self, notice):
        if self.raw_text.strip():
            await self.finalize(send_files=False)
            await self._reply_text(notice)
            return
        if self.live_msg is not None:
            await self._edit_text(self.live_msg, notice)
            self.live_msg = None
            self.active_display = ""
            return
        await self._reply_text(notice)
        self.active_display = ""

    async def _refresh(self, done, send_files):
        cleaned = clean_reply(self.raw_text) if self.raw_text.strip() else ""
        self.files = _resolve_files(extract_files(cleaned))
        body = strip_files(cleaned)
        if done and not body and self.files:
            body = "已生成附件"
        elif done and not body:
            body = "..."
        segments = _visible_segments(body)
        finalized_target = len(segments) if done else max(len(segments) - 1, 0)
        while self.sent_segments < finalized_target:
            await self._finalize_segment(segments[self.sent_segments])
            self.sent_segments += 1
        if done:
            if send_files:
                await self._send_files()
            return
        active_text = segments[-1] if segments else _DRAFT_HINT
        await self._stream_active(active_text)

    async def _stream_active(self, text):
        display = (text or _DRAFT_HINT).strip() or _DRAFT_HINT
        if display != _DRAFT_HINT:
            display = display + _STREAM_SUFFIX
        if display == self.active_display:
            return
        if self.can_use_draft and await self._send_draft(display):
            self.active_display = display
            return
        await self._upsert_live_message(display)
        self.active_display = display

    async def _finalize_segment(self, text):
        final_text = (text or "").strip() or "..."
        if self.live_msg is not None:
            await self._edit_text(self.live_msg, final_text)
            self.live_msg = None
        else:
            await self._reply_text(final_text)
        self.active_display = ""
        if self.can_use_draft:
            self.draft_id = _make_draft_id()

    async def _send_files(self):
        for fpath in self.files:
            if fpath.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
                try:
                    with open(fpath, "rb") as fp:
                     await self.root_msg.reply_photo(fp)
                except Exception: pass
            else:
                try:
                    with open(fpath, "rb") as fp:
                        await self.root_msg.reply_document(fp)
                except Exception: pass

    async def _send_draft(self, text):
        try:
            await self.root_msg.reply_text_draft(
                self.draft_id,
                _to_markdown_v2(text),
                parse_mode=ParseMode.MARKDOWN_V2,
            )
            return True
        except Exception as exc:
            if _is_not_modified_error(exc):
                return True
            print(f"[TG draft fallback] {type(exc).__name__}: {exc}", flush=True)
            self.can_use_draft = False
            self.draft_id = _make_draft_id()
            return False

    async def _reply_text(self, text):
        markdown = _to_markdown_v2(text)
        try:
            return await self.root_msg.reply_text(markdown, parse_mode=ParseMode.MARKDOWN_V2)
        except Exception as exc:
            if _is_not_modified_error(exc):
                return None
            return await self.root_msg.reply_text(text)

    async def _edit_text(self, msg, text):
        markdown = _to_markdown_v2(text)
        try:
            updated = await msg.edit_text(markdown, parse_mode=ParseMode.MARKDOWN_V2)
        except Exception as exc:
            if _is_not_modified_error(exc):
                return msg
            updated = await msg.edit_text(text)
        return updated if hasattr(updated, "edit_text") else msg

    async def _upsert_live_message(self, text):
        if self.live_msg is None:
            self.live_msg = await self._reply_text(text)
        else:
            self.live_msg = await self._edit_text(self.live_msg, text)


async def _stream(dq, msg):
    session = _TelegramStreamSession(msg)
    await session.prime()
    try:
        while True:
            try:
                first = await asyncio.to_thread(dq.get, True, _QUEUE_WAIT_SECONDS)
            except Q.Empty:
                continue
            items = [first]
            try:
                while True:
                    items.append(dq.get_nowait())
            except Q.Empty:
                pass
            done_item = next((item for item in items if "done" in item), None)
            if done_item is not None:
                await session.finalize(done_item.get("done", ""))
                break
            chunk = "".join(item.get("next", "") for item in items if item.get("next"))
            if chunk:
                await session.add_chunk(chunk)
    except asyncio.CancelledError:
        await session.finish_with_notice("⏹️ 已停止")
    except Exception as exc:
        print(f"[TG stream error] {type(exc).__name__}: {exc}", flush=True)
        await session.finish_with_notice(f"❌ 输出失败: {exc}")


def _normalized_command(text):
    parts = (text or "").strip().split(None, 1)
    if not parts:
        return ''
    head = parts[0].lower()
    if head.startswith('/'):
        head = '/' + head[1:].split('@', 1)[0]
    return head + (f" {parts[1].strip()}" if len(parts) > 1 and parts[1].strip() else '')

def _cancel_stream_task(ctx):
    task = ctx.user_data.pop('stream_task', None)
    if task and not task.done():
        task.cancel()

async def _sync_commands(application):
    await application.bot.set_my_commands([BotCommand(command, description) for command, description in TELEGRAM_MENU_COMMANDS])

async def handle_msg(update, ctx):
    uid = update.effective_user.id
    if ALLOWED and uid not in ALLOWED:
        return await update.message.reply_text("no")
    prompt = f"{FILE_HINT}\n\n{update.message.text}"
    dq = agent.put_task(prompt, source="telegram")
    task = asyncio.create_task(_stream(dq, update.message))
    ctx.user_data['stream_task'] = task

async def cmd_abort(update, ctx):
    _cancel_stream_task(ctx)
    agent.abort()
    await update.message.reply_text("⏹️ 正在停止...")

async def cmd_llm(update, ctx):
    args = (update.message.text or '').split()
    if len(args) > 1:
        try:
            n = int(args[1])
            agent.next_llm(n)
            await update.message.reply_text(f"✅ 已切换到 [{agent.llm_no}] {agent.get_llm_name()}")
        except (ValueError, IndexError):
            await update.message.reply_text(f"用法: /llm <0-{len(agent.list_llms())-1}>")
    else:
        lines = [f"{'→' if cur else '  '} [{i}] {name}" for i, name, cur in agent.list_llms()]
        await update.message.reply_text("LLMs:\n" + "\n".join(lines))

async def handle_photo(update, ctx):
    uid = update.effective_user.id
    if ALLOWED and uid not in ALLOWED:
        return await update.message.reply_text("no")
    photo = update.message.photo[-1]
    file = await photo.get_file()
    fpath = f"tg_{photo.file_unique_id}.jpg"
    await file.download_to_drive(os.path.join(_TEMP_DIR, fpath))
    caption = update.message.caption
    prompt = f"[TIPS] 收到图片temp/{fpath}\n{caption}" if caption else f"[TIPS] 收到图片temp/{fpath}，请等待下一步指令"
    dq = agent.put_task(prompt, source="telegram")
    task = asyncio.create_task(_stream(dq, update.message))
    ctx.user_data['stream_task'] = task

async def handle_command(update, ctx):
    uid = update.effective_user.id
    if ALLOWED and uid not in ALLOWED:
        return await update.message.reply_text("no")
    cmd = _normalized_command(update.message.text)
    op = cmd.split()[0] if cmd else ''
    if op == '/help': return await update.message.reply_text(HELP_TEXT)
    if op == '/status':
        llm = agent.get_llm_name() if agent.llmclient else '未配置'
        return await update.message.reply_text(f"状态: {'🔴 运行中' if agent.is_running else '🟢 空闲'}\nLLM: [{agent.llm_no}] {llm}")
    if op == '/stop': return await cmd_abort(update, ctx)
    if op == '/llm': return await cmd_llm(update, ctx)
    if op == '/new':
        _cancel_stream_task(ctx)
        return await update.message.reply_text(reset_conversation(agent))
    if op == '/restore':
        _cancel_stream_task(ctx)
        try:
            restored_info, err = format_restore()
            if err:
                return await update.message.reply_text(err)
            restored, fname, count = restored_info
            agent.abort()
            agent.history.extend(restored)
            return await update.message.reply_text(f"✅ 已恢复 {count} 轮对话\n来源: {fname}\n(仅恢复上下文，请输入新问题继续)")
        except Exception as e:
            return await update.message.reply_text(f"❌ 恢复失败: {e}")
    if op == '/continue':
        if cmd != '/continue': _cancel_stream_task(ctx)
        return await update.message.reply_text(handle_frontend_command(agent, cmd))
    return await update.message.reply_text(HELP_TEXT)

if __name__ == '__main__':
    try:  # Single instance lock using socket
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
            app = (ApplicationBuilder().token(mykeys['tg_bot_token'])
                   .request(request).get_updates_request(request).post_init(_sync_commands).build())
            app.add_handler(MessageHandler(filters.COMMAND, handle_command))
            app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
            app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
            app.add_error_handler(_error_handler)
            app.run_polling(drop_pending_updates=True, poll_interval=1.0, timeout=30)
        except Exception as e:
            print(f"[{time.strftime('%m-%d %H:%M')}] polling crashed: {e}", flush=True)
            time.sleep(10)
            asyncio.set_event_loop(asyncio.new_event_loop())
