# Discord Bot Frontend for GenericAgent
# ⚠️ 需要在 Discord Developer Portal 开启 "Message Content Intent"
#   Bot → Privileged Gateway Intents → MESSAGE CONTENT INTENT → 打开
# pip install discord.py

import asyncio, json, os, queue as Q, re, sys, threading, time
from collections import OrderedDict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agentmain import GeneraticAgent
from chatapp_common import (
    AgentChatMixin, build_done_text, ensure_single_instance, extract_files,
    public_access, redirect_log, require_runtime, split_text, strip_files, clean_reply,
    HELP_TEXT, FILE_HINT, format_restore,
    _handle_continue_frontend, _reset_conversation,
)
from llmcore import mykeys

try:
    import discord
except Exception:
    print("Please install discord.py to use Discord: pip install discord.py")
    sys.exit(1)

agent = GeneraticAgent(); agent.verbose = False
BOT_TOKEN = str(mykeys.get("discord_bot_token", "") or "").strip()
ALLOWED = {str(x).strip() for x in mykeys.get("discord_allowed_users", []) if str(x).strip()}
USER_TASKS = {}
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMP_DIR = os.path.join(PROJECT_ROOT, "temp")
MEDIA_DIR = os.path.join(TEMP_DIR, "discord_media")
ACTIVE_FILE = os.path.join(TEMP_DIR, "discord_active_channels.json")
ACTIVE_TTL_SECONDS = 30 * 24 * 3600
EXIT_CHANNEL_TEXTS = {"退出该频道", "退出此频道", "退出频道"}
EXIT_THREAD_TEXTS = {"退出该子区", "退出此子区", "退出子区"}
os.makedirs(MEDIA_DIR, exist_ok=True)


def _extract_discord_progress(text):
    """Return the newest concise <summary> from a streaming transcript."""
    matches = re.findall(r"<summary>\s*(.*?)\s*</summary>", text or "", flags=re.DOTALL)
    if not matches:
        return ""
    summary = re.sub(r"\s+", " ", matches[-1]).strip()
    return summary[:120]


def _strip_discord_transcript(text):
    """Hide LLM/tool transcript noise while preserving the final natural reply."""
    text = text or ""
    text = re.sub(r"^\s*\*?\*?LLM Running \(Turn \d+\) \.\.\.\*?\*?\s*$", "", text, flags=re.M)
    text = re.sub(r"^\s*🛠️\s+.*?(?=^\s*(?:\*?\*?LLM Running|<summary>|$))", "", text, flags=re.M | re.DOTALL)
    text = re.sub(r"^\s*(?:✅|❌|ERR|STDOUT|PAT\b|RC\b).*?$", "", text, flags=re.M)
    text = re.sub(r"<tool_use>.*?</tool_use>", "", text, flags=re.DOTALL)
    text = clean_reply(text)
    return strip_files(text).strip()


def _display_done_text(text):
    body = _strip_discord_transcript(text)
    if body and body != "...":
        return body
    summaries = re.findall(r"<summary>\s*(.*?)\s*</summary>", text or "", flags=re.DOTALL)
    if summaries:
        return re.sub(r"\s+", " ", summaries[-1]).strip() or "..."
    return "..."


class DiscordApp(AgentChatMixin):
    label, source, split_limit = "Discord", "discord", 1900

    def __init__(self):
        super().__init__(agent, USER_TASKS)
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.dm_messages = True
        proxy = str(mykeys.get("proxy", "") or "").strip() or None
        self.client = discord.Client(intents=intents, proxy=proxy)
        self.background_tasks = set()
        self._channel_cache = OrderedDict()  # chat_id -> channel/user object (LRU, max 500)
        self._active_channels = self._load_active_channels()  # guild chat_id -> {last_seen: float}
        self._active_lock = threading.Lock()
        self._agents = OrderedDict()  # chat_id -> GeneraticAgent, each chat has isolated history
        self._agent_lock = threading.Lock()

        @self.client.event
        async def on_ready():
            print(f"[Discord] bot ready: {self.client.user} ({self.client.user.id})")

        @self.client.event
        async def on_message(message):
            await self._handle_message(message)

    def _chat_id(self, message):
        """Return a string chat_id: 'dm:<user_id>' or 'ch:<channel_id>'."""
        if isinstance(message.channel, discord.DMChannel):
            return f"dm:{message.author.id}"
        return f"ch:{message.channel.id}"

    def _load_active_channels(self):
        try:
            with open(ACTIVE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return {}
            now = time.time()
            active = {}
            for chat_id, item in data.items():
                if not str(chat_id).startswith("ch:") or not isinstance(item, dict):
                    continue
                last_seen = float(item.get("last_seen") or 0)
                if now - last_seen <= ACTIVE_TTL_SECONDS:
                    active[str(chat_id)] = {"last_seen": last_seen}
            return active
        except FileNotFoundError:
            return {}
        except Exception as e:
            print(f"[Discord] failed to load active channels: {e}")
            return {}

    def _save_active_channels(self):
        try:
            os.makedirs(os.path.dirname(ACTIVE_FILE), exist_ok=True)
            tmp = ACTIVE_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._active_channels, f, ensure_ascii=False, indent=2, sort_keys=True)
            os.replace(tmp, ACTIVE_FILE)
        except Exception as e:
            print(f"[Discord] failed to save active channels: {e}")

    def _is_active_channel(self, chat_id, now=None):
        now = now or time.time()
        with self._active_lock:
            item = self._active_channels.get(chat_id)
            if not item:
                return False
            if now - float(item.get("last_seen") or 0) > ACTIVE_TTL_SECONDS:
                self._active_channels.pop(chat_id, None)
                self._save_active_channels()
                print(f"[Discord] channel expired: {chat_id}")
                return False
            return True

    def _touch_active_channel(self, chat_id, now=None):
        if not chat_id.startswith("ch:"):
            return
        with self._active_lock:
            self._active_channels[chat_id] = {"last_seen": float(now or time.time())}
            self._save_active_channels()

    def _deactivate_channel(self, chat_id):
        with self._active_lock:
            changed = self._active_channels.pop(chat_id, None) is not None
            self._save_active_channels()
        state = self.user_tasks.get(chat_id)
        if state:
            state["running"] = False
        try:
            self._get_agent(chat_id).abort()
        except Exception as e:
            print(f"[Discord] deactivate abort failed for {chat_id}: {e}")
        return changed

    def _get_agent(self, chat_id):
        with self._agent_lock:
            ga = self._agents.get(chat_id)
            if ga is None:
                ga = GeneraticAgent()
                ga.verbose = False
                self._agents[chat_id] = ga
                threading.Thread(target=ga.run, daemon=True, name=f"discord-agent-{chat_id}").start()
                if len(self._agents) > 200:
                    old_chat_id, _old_agent = self._agents.popitem(last=False)
                    print(f"[Discord] dropped agent cache entry: {old_chat_id}")
            else:
                self._agents.move_to_end(chat_id)
            return ga

    async def _download_attachments(self, message):
        """Download attachments/images to MEDIA_DIR, return list of local paths."""
        paths = []
        for att in message.attachments:
            safe_name = re.sub(r'[<>:"/\\|?*]', '_', att.filename or f"file_{att.id}")
            local_path = os.path.join(MEDIA_DIR, f"{att.id}_{safe_name}")
            try:
                await att.save(local_path)
                paths.append(local_path)
                print(f"[Discord] saved attachment: {local_path}")
            except Exception as e:
                print(f"[Discord] failed to save attachment {att.filename}: {e}")
        return paths

    async def send_text(self, chat_id, content, **ctx):
        """Send text (and optionally files) to a chat_id."""
        channel = self._channel_cache.get(chat_id)
        if channel is None:
            try:
                if chat_id.startswith("dm:"):
                    user = await self.client.fetch_user(int(chat_id[3:]))
                    channel = await user.create_dm()
                else:
                    channel = await self.client.fetch_channel(int(chat_id[3:]))
                self._channel_cache[chat_id] = channel
                if len(self._channel_cache) > 500:
                    self._channel_cache.popitem(last=False)
            except Exception as e:
                print(f"[Discord] cannot resolve channel for {chat_id}: {e}")
                return
        for part in split_text(content, self.split_limit):
            try:
                await channel.send(part)
            except Exception as e:
                print(f"[Discord] send error: {e}")

    async def send_done(self, chat_id, raw_text, **ctx):
        """Send final reply: text parts + file attachments."""
        files = [p for p in extract_files(raw_text) if os.path.exists(p)]
        body = _display_done_text(raw_text)

        # Send text (send_text handles splitting internally)
        if body and body != "...":
            await self.send_text(chat_id, body, **ctx)

        # Send files as Discord attachments
        if files:
            channel = self._channel_cache.get(chat_id)
            if channel:
                for fpath in files:
                    try:
                        await channel.send(file=discord.File(fpath))
                    except Exception as e:
                        print(f"[Discord] failed to send file {fpath}: {e}")
                        await self.send_text(chat_id, f"⚠️ 文件发送失败: {os.path.basename(fpath)}", **ctx)

        if not body and not files:
            await self.send_text(chat_id, "...", **ctx)

    async def handle_command(self, chat_id, cmd, **ctx):
        """Handle slash commands against the per-chat agent, keeping Discord chats isolated."""
        ga = self._get_agent(chat_id)
        parts = (cmd or "").split()
        op = (parts[0] if parts else "").lower()
        if op == "/help":
            return await self.send_text(chat_id, HELP_TEXT, **ctx)
        if op == "/stop":
            state = self.user_tasks.get(chat_id)
            if state:
                state["running"] = False
            ga.abort()
            return await self.send_text(chat_id, "⏹️ 正在停止...", **ctx)
        if op == "/status":
            llm = ga.get_llm_name() if ga.llmclient else "未配置"
            return await self.send_text(chat_id, f"状态: {'🔴 运行中' if ga.is_running else '🟢 空闲'}\nLLM: [{ga.llm_no}] {llm}", **ctx)
        if op == "/llm":
            if not ga.llmclient:
                return await self.send_text(chat_id, "❌ 当前没有可用的 LLM 配置", **ctx)
            if len(parts) > 1:
                try:
                    ga.next_llm(int(parts[1]))
                    return await self.send_text(chat_id, f"✅ 已切换到 [{ga.llm_no}] {ga.get_llm_name()}", **ctx)
                except Exception:
                    return await self.send_text(chat_id, f"用法: /llm <0-{len(ga.list_llms()) - 1}>", **ctx)
            lines = [f"{'→' if cur else '  '} [{i}] {name}" for i, name, cur in ga.list_llms()]
            return await self.send_text(chat_id, "LLMs:\n" + "\n".join(lines), **ctx)
        if op == "/restore":
            try:
                restored_info, err = format_restore()
                if err:
                    return await self.send_text(chat_id, err, **ctx)
                restored, fname, count = restored_info
                ga.abort()
                ga.history.extend(restored)
                return await self.send_text(chat_id, f"✅ 已恢复 {count} 轮对话\n来源: {fname}\n(仅恢复上下文，请输入新问题继续)", **ctx)
            except Exception as e:
                return await self.send_text(chat_id, f"❌ 恢复失败: {e}", **ctx)
        if op == "/continue":
            return await self.send_text(chat_id, _handle_continue_frontend(ga, cmd), **ctx)
        if op == "/new":
            return await self.send_text(chat_id, _reset_conversation(ga), **ctx)
        return await self.send_text(chat_id, HELP_TEXT, **ctx)

    async def run_agent(self, chat_id, text, **ctx):
        """Run the isolated per-chat Discord agent."""
        ga = self._get_agent(chat_id)
        state = {"running": True}
        self.user_tasks[chat_id] = state
        try:
            await self.send_text(chat_id, "思考中...", **ctx)
            dq = ga.put_task(f"{FILE_HINT}\n\n{text}", source=self.source)
            last_ping = time.time()
            last_step = ""
            step_no = 0
            while state["running"]:
                try:
                    item = await asyncio.to_thread(dq.get, True, 3)
                except Q.Empty:
                    if ga.is_running and time.time() - last_ping > self.ping_interval:
                        await self.send_text(chat_id, "⏳ 还在处理中，请稍等...", **ctx)
                        last_ping = time.time()
                    continue
                if "next" in item:
                    step = _extract_discord_progress(item.get("next", ""))
                    if step and step != last_step:
                        step_no += 1
                        await self.send_text(chat_id, f"步骤{step_no}：{step}", **ctx)
                        last_step = step
                        last_ping = time.time()
                    continue
                if "done" in item:
                    await self.send_done(chat_id, item.get("done", ""), **ctx)
                    break
            if not state["running"]:
                await self.send_text(chat_id, "⏹️ 已停止", **ctx)
        except Exception as e:
            import traceback
            print(f"[{self.label}] run_agent error: {e}")
            traceback.print_exc()
            await self.send_text(chat_id, f"❌ 错误: {e}", **ctx)
        finally:
            self.user_tasks.pop(chat_id, None)

    async def _handle_message(self, message):
        # Ignore self
        if message.author == self.client.user or message.author.bot:
            return

        is_dm = isinstance(message.channel, discord.DMChannel)
        is_guild = message.guild is not None
        chat_id = self._chat_id(message)
        now = time.time()
        mentioned = bool(is_guild and self.client.user and self.client.user.mentioned_in(message))

        self._channel_cache[chat_id] = message.channel
        if len(self._channel_cache) > 500:
            self._channel_cache.popitem(last=False)

        user_id = str(message.author.id)
        user_name = str(message.author)

        if not public_access(ALLOWED) and user_id not in ALLOWED:
            print(f"[Discord] unauthorized user: {user_name} ({user_id})")
            return

        if is_guild:
            active = self._is_active_channel(chat_id, now)
            if not mentioned and not active:
                return
            if mentioned or active:
                self._touch_active_channel(chat_id, now)

        # Strip bot mention from content
        content = message.content or ""
        if is_guild and self.client.user:
            content = re.sub(rf"<@!?{self.client.user.id}>", "", content).strip()
        else:
            content = content.strip()

        normalized = re.sub(r"\s+", "", content)
        if is_guild and normalized in EXIT_CHANNEL_TEXTS | EXIT_THREAD_TEXTS:
            self._deactivate_channel(chat_id)
            label = "子区" if normalized in EXIT_THREAD_TEXTS else "频道"
            await self.send_text(chat_id, f"✅ 已退出该{label}，之后除非重新 @ 我，否则不会主动响应。")
            print(f"[Discord] manually deactivated {chat_id} by {user_name} ({user_id})")
            return

        # Download attachments
        attachment_paths = await self._download_attachments(message)

        # Build message text with attachment paths
        if attachment_paths:
            paths_text = "\n".join(f"[附件: {p}]" for p in attachment_paths)
            content = f"{content}\n{paths_text}" if content else paths_text

        if not content:
            return

        print(f"[Discord] message from {user_name} ({user_id}, {'dm' if is_dm else 'guild'}): {content[:200]}")

        if content.startswith("/"):
            return await self.handle_command(chat_id, content)

        task = asyncio.create_task(self.run_agent(chat_id, content))
        self.background_tasks.add(task)
        task.add_done_callback(self.background_tasks.discard)

    async def start(self):
        print("[Discord] bot starting...")
        delay, max_delay = 5, 300
        while True:
            started_at = time.monotonic()
            try:
                await self.client.start(BOT_TOKEN)
            except Exception as e:
                print(f"[Discord] error: {e}")
            if time.monotonic() - started_at >= 60:
                delay = 5
            print(f"[Discord] reconnect in {delay}s...")
            await asyncio.sleep(delay)
            delay = min(delay * 2, max_delay)


if __name__ == "__main__":
    _LOCK_SOCK = ensure_single_instance(19532, "Discord")
    require_runtime(agent, "Discord", discord_bot_token=BOT_TOKEN)
    redirect_log(__file__, "dcapp.log", "Discord", ALLOWED)
    asyncio.run(DiscordApp().start())
