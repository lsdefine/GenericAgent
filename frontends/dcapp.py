# Discord Bot Frontend for GenericAgent
# ⚠️ 需要在 Discord Developer Portal 开启 "Message Content Intent"
#   Bot → Privileged Gateway Intents → MESSAGE CONTENT INTENT → 打开
# pip install discord.py

import asyncio, os, re, sys, threading, time
from collections import OrderedDict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agentmain import GeneraticAgent
from chatapp_common import (
    AgentChatMixin, build_done_text, ensure_single_instance, extract_files,
    public_access, redirect_log, require_runtime, split_text, strip_files, clean_reply,
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
MEDIA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "temp", "discord_media")
os.makedirs(MEDIA_DIR, exist_ok=True)


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
        body = strip_files(clean_reply(raw_text))

        # Send text (send_text handles splitting internally)
        if body:
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

    async def _handle_message(self, message):
        # Ignore self
        if message.author == self.client.user or message.author.bot:
            return

        is_dm = isinstance(message.channel, discord.DMChannel)
        is_guild = message.guild is not None

        # In guild channels, only respond when @mentioned
        if is_guild and not self.client.user.mentioned_in(message):
            return

        # Strip bot mention from content
        content = message.content or ""
        if is_guild and self.client.user:
            content = re.sub(rf"<@!?{self.client.user.id}>", "", content).strip()

        user_id = str(message.author.id)
        user_name = str(message.author)

        if not public_access(ALLOWED) and user_id not in ALLOWED:
            print(f"[Discord] unauthorized user: {user_name} ({user_id})")
            return

        # Download attachments
        attachment_paths = await self._download_attachments(message)

        # Build message text with attachment paths
        if attachment_paths:
            paths_text = "\n".join(f"[附件: {p}]" for p in attachment_paths)
            content = f"{content}\n{paths_text}" if content else paths_text

        if not content:
            return

        chat_id = self._chat_id(message)
        self._channel_cache[chat_id] = message.channel
        if len(self._channel_cache) > 500:
            self._channel_cache.popitem(last=False)

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
    threading.Thread(target=agent.run, daemon=True).start()
    asyncio.run(DiscordApp().start())