# Discord Bot Frontend for GenericAgent
# ⚠️ 需要在 Discord Developer Portal 开启 "Message Content Intent"
#   Bot → Privileged Gateway Intents → MESSAGE CONTENT INTENT → 打开
# pip install discord.py

import asyncio, json, os, queue as Q, re, sys, threading, time
from collections import OrderedDict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agentmain import GeneraticAgent
from chatapp_common import (
    AgentChatMixin, ensure_single_instance, extract_files,
    public_access, redirect_log, require_runtime, split_text, clean_reply,
    HELP_TEXT, format_restore,
    _handle_continue_frontend, _reset_conversation,
)
from llmcore import mykeys


def _mykey_value(keys, primary, fallback, default=None):
    value = keys.get(primary, None)
    if value in (None, "", []):
        value = keys.get(fallback, default)
    return default if value is None else value


def _allowed_values(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return value


try:
    import discord
    from discord import app_commands
except Exception:
    print("Please install discord.py to use Discord: pip install discord.py")
    sys.exit(1)

agent = GeneraticAgent(); agent.verbose = False
BOT_TOKEN = str(_mykey_value(mykeys, "discord_bot_token", "dc_bot_token", "") or "").strip()
ALLOWED = {
    str(x).strip()
    for x in _allowed_values(_mykey_value(mykeys, "discord_allowed_users", "dc_allowed_users", []))
    if str(x).strip()
}
USER_TASKS = {}
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMP_DIR = os.path.join(PROJECT_ROOT, "temp")
MEDIA_DIR = os.path.join(TEMP_DIR, "discord_media")
ACTIVE_FILE = os.path.join(TEMP_DIR, "discord_active_channels.json")
ACTIVE_CLEANUP_HOUR = 3
ACTIVE_CLEANUP_MINUTE = 0
ACTIVE_CLEANUP_FETCH_DELAY_SECONDS = 0.25
TURN_MARKER_LINE_RE = re.compile(r"^\s*\**LLM Running \(Turn \d+\) \.\.\.\**\s*$")
DISCORD_FILE_HINT = (
    "Do not mention local file paths or use [FILE:filepath] "
    "unless the user explicitly asks to send/show a file."
)
DISCORD_FILE_SEND_HINT = (
    "The user explicitly requested a file. If you need to send a local regular file, "
    "put exactly one [FILE:filepath] marker in the final answer; Discord will upload it "
    "as an attachment and hide the local path from visible text."
)
DISCORD_FILE_NO_SEND_HINT = (
    "The user did not explicitly request a file attachment. Do not use [FILE:filepath] "
    "or expose local file paths; summarize or paste short text instead."
)
EXIT_CHANNEL_TEXTS = {"退下", "退出该频道", "退出此频道", "退出频道"}
EXIT_THREAD_TEXTS = {"退出该子区", "退出此子区", "退出子区"}
os.makedirs(MEDIA_DIR, exist_ok=True)


def _extract_discord_progress(text):
    """Return the newest concise <summary> from a streaming transcript."""
    search_text = re.sub(r"`{3,}.*?`{3,}|<thinking>.*?</thinking>", "", text or "", flags=re.DOTALL)
    matches = re.findall(r"<summary>\s*((?:(?!<summary>).)*?)\s*</summary>", search_text, flags=re.DOTALL)
    if not matches:
        return ""
    summary = re.sub(r"\s+", " ", matches[-1]).strip()
    return summary[:120]


def _extract_discord_turn(text):
    """Return the newest GA turn number outside fenced code blocks."""
    turn = None
    for end in _turn_marker_ends_outside_code(text):
        prefix = (text or "")[:end]
        line = prefix.splitlines()[-1] if prefix.splitlines() else ""
        match = re.search(r"Turn (\d+)", line)
        if match:
            turn = int(match.group(1))
    return turn


def _render_file_refs_for_discord(text):
    """Hide GA [FILE:path] markers from Discord text to avoid leaking local paths."""
    return re.sub(r"\[FILE:([^\]]+)\]", "", text or "")


def _is_sendable_discord_file(path):
    """Return True only for local regular files that Discord should upload."""
    try:
        return os.path.isfile(path)
    except OSError:
        return False


def _user_requested_file_send(text):
    """Heuristic gate: only allow Discord file upload when user explicitly asks for a file/attachment."""
    text = (text or "").lower()
    compact = re.sub(r"\s+", "", text)
    negative_patterns = (
        r"do\s+not\s+(?:send|attach|upload).{0,40}\b(?:file|attachment)\b",
        r"(?:don't|dont)\s+(?:send|attach|upload).{0,40}\b(?:file|attachment)\b",
        r"(?:no|without)\s+(?:file|attachment)s?\b",
        r"不要.{0,12}(?:发|发送|上传).{0,12}(?:文件|附件)",
        r"不(?:要|用).{0,12}(?:文件|附件)",
    )
    if any(re.search(pat, text) or re.search(pat, compact) for pat in negative_patterns):
        return False
    positive_patterns = (
        r"\b(send|attach|upload)\b.*\b(file|attachment)\b",
        r"\b(file|attachment)\b.*\b(send|attach|upload)\b",
        r"\bsend\s+me\s+(the\s+)?file\b",
        r"\bshow\s+me\s+(the\s+)?file\b",
        r"\bdownload\b",
        r"发送.*文件",
        r"把.*文件.*发",
        r"发.*文件",
        r"生成.*(?:报告|文档|表格|pdf|docx|xlsx|csv|图片).*(?:发|给|下载|导出)",
        r"(?:报告|文档|表格|pdf|docx|xlsx|csv|图片).*(?:发我|给我|下载|导出)",
        r"(?:导出|下载).*(?:报告|文档|表格|pdf|docx|xlsx|csv|图片|文件)",
        r"上传.*文件",
        r"作为附件",
        r"附件.*发",
        r"发.*附件",
    )
    if any(re.search(pat, text) or re.search(pat, compact) for pat in positive_patterns):
        return True
    if "[file:" in text:
        return True
    return False


def _strip_turn_marker_lines_outside_code(text):
    out = []
    in_fence = None
    fence_len = 0
    for line in (text or "").splitlines(True):
        body = line.rstrip("\r\n")
        stripped = body.lstrip()
        if in_fence:
            out.append(line)
            if stripped.startswith(in_fence * fence_len):
                in_fence = None
                fence_len = 0
            continue
        fence = re.match(r"(`{3,}|~{3,})", stripped)
        if fence:
            marker = fence.group(1)
            in_fence = marker[0]
            fence_len = len(marker)
            out.append(line)
            continue
        if TURN_MARKER_LINE_RE.match(body):
            continue
        out.append(line)
    return "".join(out)


def _strip_discord_transcript(text):
    """Hide LLM/tool transcript noise while preserving the final natural reply."""
    text = _strip_turn_marker_lines_outside_code(text)
    text = re.sub(r"^\s*🛠️\s+.*?(?=^\s*(?:\*?\*?LLM Running|<summary>|$))", "", text, flags=re.M | re.DOTALL)
    text = re.sub(r"^\s*(?:✅|❌|ERR|STDOUT|PAT\b|RC\b).*?$", "", text, flags=re.M)
    text = re.sub(r"<tool_use>.*?</tool_use>", "", text, flags=re.DOTALL)
    text = clean_reply(text)
    return _render_file_refs_for_discord(text).strip()


def _display_done_text(text):
    body = _strip_discord_transcript(_final_discord_answer(text))
    if body and body != "...":
        return body
    # Discord must not expose internal <summary> status snapshots as a fallback
    # final answer. If the model only produced tool/commentary status, keep the
    # user-facing response generic instead of leaking execution summaries.
    return "..."


def _turn_marker_ends_outside_code(text):
    ends = []
    in_fence = None
    fence_len = 0
    pos = 0
    for line in (text or "").splitlines(True):
        body = line.rstrip("\r\n")
        stripped = body.lstrip()
        if in_fence:
            if stripped.startswith(in_fence * fence_len):
                in_fence = None
                fence_len = 0
            pos += len(line)
            continue
        fence = re.match(r"(`{3,}|~{3,})", stripped)
        if fence:
            marker = fence.group(1)
            in_fence = marker[0]
            fence_len = len(marker)
            pos += len(line)
            continue
        if TURN_MARKER_LINE_RE.match(body):
            ends.append(pos + len(line))
        pos += len(line)
    return ends


def _final_discord_answer(text):
    """Prefer the newest GA turn body as the final Discord-visible answer."""
    text = text or ""
    marker_ends = _turn_marker_ends_outside_code(text)
    if not marker_ends:
        return text
    candidate = text[marker_ends[-1]:].strip()
    cleaned = _strip_discord_transcript(candidate)
    return candidate if cleaned and cleaned != "..." else text


class _DiscordProgressMessage:
    """Maintain one editable Discord progress message instead of sending step spam."""

    def __init__(self, app, chat_id, ctx):
        self.app = app
        self.chat_id = chat_id
        self.ctx = dict(ctx)
        self.message = None
        self.last_text = ""
        self.last_summary = ""
        self.last_turn = None
        self.edit_failed = False

    async def start(self):
        await self._set(self._render())

    async def update(self, summary, turn=None):
        summary = (summary or "").strip()
        if turn is not None:
            self.last_turn = turn
        if summary:
            self.last_summary = summary
        await self._set(self._render())

    async def heartbeat(self):
        await self._set(self._render())

    async def finish(self):
        await self._set("已完成")

    def _render(self):
        turn = f"Turn {self.last_turn}" if self.last_turn is not None else "Turn ?"
        summary = self.last_summary or "还在处理中，请稍等..."
        return f"{turn}\n当前进度：{summary}"

    async def _set(self, text):
        if not text or text == self.last_text:
            return
        self.last_text = text
        if self.edit_failed:
            return
        if self.message is not None:
            try:
                await self.message.edit(content=text)
                return
            except Exception as e:
                print(f"[Discord] progress edit failed: {type(e).__name__}: {e}")
                self.edit_failed = True
                return
        self.message = await self.app.send_text(self.chat_id, text, silent=True, **self.ctx)


class DiscordApp(AgentChatMixin):
    label, source, split_limit = "Discord", "discord", 1900
    ping_interval = 40

    def __init__(self):
        super().__init__(agent, USER_TASKS)
        self.background_tasks = set()
        self._channel_cache = OrderedDict()  # chat_id -> channel/user object (LRU, max 500)
        self._active_channels = self._load_active_channels()  # guild chat_id -> {last_seen: float}
        self._active_lock = threading.Lock()
        self._agents = OrderedDict()  # chat_id -> GeneraticAgent, each chat has isolated history
        self._agent_lock = threading.Lock()
        self._active_cleanup_task = None
        self._build_client()

    def _build_client(self):
        """Create a fresh Discord client.

        discord.py Client instances are single-use after close/logout.  Reusing
        the same instance in the reconnect loop can leave the bot unable to
        reconnect after a restart/disconnect, so every outer reconnect attempt
        gets a new client, command tree and event bindings.
        """
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.dm_messages = True
        proxy = str(mykeys.get("proxy", "") or "").strip() or None
        self.client = discord.Client(intents=intents, proxy=proxy)
        self.tree = app_commands.CommandTree(self.client)
        self._slash_synced = False
        self._register_slash_commands()

        @self.client.event
        async def on_ready():
            user = self.client.user
            uid = getattr(user, "id", "?")
            print(f"[Discord] bot ready: {user} ({uid}) pid={os.getpid()} python={os.path.basename(sys.executable)}")
            if not self._slash_synced:
                try:
                    synced = await self.tree.sync()
                    self._slash_synced = True
                    print(f"[Discord] synced {len(synced)} slash commands")
                except Exception as e:
                    print(f"[Discord] slash command sync failed: {e}")
            if self._active_cleanup_task is None or self._active_cleanup_task.done():
                self._active_cleanup_task = asyncio.create_task(self._active_channel_cleanup_loop())

        @self.client.event
        async def on_message(message):
            await self._handle_message(message)

    def _chat_id(self, message):
        """Return a string chat_id: 'dm:<user_id>' or 'ch:<channel_id>'."""
        if isinstance(message.channel, discord.DMChannel):
            return f"dm:{message.author.id}"
        return f"ch:{message.channel.id}"

    def _interaction_chat_id(self, interaction):
        """Return a string chat_id for an Interaction: 'dm:<user_id>' or 'ch:<channel_id>'."""
        if interaction.guild is None:
            return f"dm:{interaction.user.id}"
        return f"ch:{interaction.channel_id}"

    async def _reply_interaction(self, interaction, content, silent=False):
        first_message = None
        for part in split_text(content or "...", self.split_limit):
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(part, silent=silent)
                    msg = await interaction.original_response()
                else:
                    msg = await interaction.followup.send(part, silent=silent, wait=True)
            except TypeError:
                if not interaction.response.is_done():
                    await interaction.response.send_message(part)
                    msg = await interaction.original_response()
                else:
                    msg = await interaction.followup.send(part, wait=True)
            if first_message is None:
                first_message = msg
        return first_message

    async def _send_via_interaction(self, chat_id, content, interaction=None, **ctx):
        if interaction is None:
            return await self.send_text(chat_id, content, **ctx)
        return await self._reply_interaction(interaction, content, silent=ctx.get("silent", False))

    def _plan_prompt(self, task):
        return (
            "启动plan模式执行以下任务。请严格按plan_sop：先完成探索态，创建plan并进入plan模式；"
            "需要用户确认时在Discord中询问；执行中按plan更新；完成前必须做独立VERIFY验证。\n\n"
            f"任务：{task.strip()}"
        )

    def _goal_prompt(self, objective, budget):
        budget = (budget or "").strip()
        budget_line = f"时间/轮次预算：{budget}\n" if budget else "若用户未给预算，请先询问预算再启动goal模式。\n"
        return (
            "启动goal模式处理以下开放目标。请严格按goal_mode_sop：确认目标和预算，写入goal状态，"
            "后台reflect持续运行，预算耗尽后收口，并可汇报进度。\n"
            f"{budget_line}\n目标：{objective.strip()}"
        )

    def _register_slash_commands(self):
        @self.tree.command(name="help", description="显示帮助")
        async def help_cmd(interaction: discord.Interaction):
            await self._handle_interaction_command(interaction, "/help")

        @self.tree.command(name="status", description="查看状态")
        async def status_cmd(interaction: discord.Interaction):
            await self._handle_interaction_command(interaction, "/status")

        @self.tree.command(name="stop", description="停止当前任务")
        async def stop_cmd(interaction: discord.Interaction):
            await self._handle_interaction_command(interaction, "/stop")

        @self.tree.command(name="new", description="开启新对话并清空当前上下文")
        async def new_cmd(interaction: discord.Interaction):
            await self._handle_interaction_command(interaction, "/new")

        @self.tree.command(name="restore", description="恢复上次对话历史")
        async def restore_cmd(interaction: discord.Interaction):
            await self._handle_interaction_command(interaction, "/restore")

        @self.tree.command(name="continue", description="列出或恢复可继续的会话")
        @app_commands.describe(n="要恢复的序号；留空则列出可恢复会话")
        async def continue_cmd(interaction: discord.Interaction, n: int | None = None):
            cmd = "/continue" if n is None else f"/continue {n}"
            await self._handle_interaction_command(interaction, cmd)

        @self.tree.command(name="llm", description="列出或切换LLM")
        @app_commands.describe(n="要切换的LLM序号；留空则列出")
        async def llm_cmd(interaction: discord.Interaction, n: int | None = None):
            cmd = "/llm" if n is None else f"/llm {n}"
            await self._handle_interaction_command(interaction, cmd)

        @self.tree.command(name="plan", description="按plan模式执行复杂任务")
        @app_commands.describe(task="要规划并执行的复杂任务")
        async def plan_cmd(interaction: discord.Interaction, task: str):
            await self._handle_interaction_agent(interaction, self._plan_prompt(task))

        @self.tree.command(name="goal", description="按goal模式运行开放目标")
        @app_commands.describe(objective="开放目标", budget="时间或轮次预算，例如3小时/30分钟/20轮")
        async def goal_cmd(interaction: discord.Interaction, objective: str, budget: str | None = None):
            await self._handle_interaction_agent(interaction, self._goal_prompt(objective, budget))

    async def _defer_interaction(self, interaction):
        if interaction.response.is_done():
            return
        try:
            await interaction.response.defer(thinking=True)
        except TypeError:
            await interaction.response.defer()

    async def _handle_interaction_command(self, interaction, cmd):
        chat_id = self._interaction_chat_id(interaction)
        user_id = str(interaction.user.id)
        if not public_access(ALLOWED) and user_id not in ALLOWED:
            return await self._reply_interaction(interaction, "❌ 未授权")
        await self._defer_interaction(interaction)
        if interaction.guild is not None:
            self._touch_active_channel(chat_id)
        self._channel_cache[chat_id] = interaction.channel
        await self.handle_command(chat_id, cmd, interaction=interaction)

    async def _handle_interaction_agent(self, interaction, text):
        chat_id = self._interaction_chat_id(interaction)
        user_id = str(interaction.user.id)
        if not public_access(ALLOWED) and user_id not in ALLOWED:
            return await self._reply_interaction(interaction, "❌ 未授权")
        await self._defer_interaction(interaction)
        if interaction.guild is not None:
            self._touch_active_channel(chat_id)
        self._channel_cache[chat_id] = interaction.channel
        notify_user_id = user_id if interaction.guild is not None else None
        task = asyncio.create_task(self.run_agent(chat_id, text, interaction=interaction, notify_user_id=notify_user_id))
        self.background_tasks.add(task)
        task.add_done_callback(self.background_tasks.discard)

    def _load_active_channels(self):
        try:
            with open(ACTIVE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return {}
            active = {}
            for chat_id, item in data.items():
                if not str(chat_id).startswith("ch:") or not isinstance(item, dict):
                    continue
                active[str(chat_id)] = {"last_seen": float(item.get("last_seen") or 0)}
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
            return True

    def _touch_active_channel(self, chat_id, now=None):
        if not chat_id.startswith("ch:"):
            return
        with self._active_lock:
            self._active_channels[chat_id] = {"last_seen": float(now or time.time())}
            self._save_active_channels()

    def _deactivate_channel(self, chat_id, abort_agent=True):
        with self._active_lock:
            changed = self._active_channels.pop(chat_id, None) is not None
            self._save_active_channels()
        self._channel_cache.pop(chat_id, None)
        state = self.user_tasks.get(chat_id)
        if state:
            state["running"] = False
        if abort_agent:
            try:
                ga = self._agents.get(chat_id)
                if ga is not None:
                    ga.abort()
            except Exception as e:
                print(f"[Discord] deactivate abort failed for {chat_id}: {e}")
        return changed

    def _active_channel_ids_snapshot(self):
        with self._active_lock:
            return list(self._active_channels.keys())

    async def _validate_active_channel(self, chat_id):
        if not chat_id.startswith("ch:"):
            return True
        try:
            channel = await self.client.fetch_channel(int(chat_id[3:]))
            self._channel_cache[chat_id] = channel
            if len(self._channel_cache) > 500:
                self._channel_cache.popitem(last=False)
            return True
        except (discord.NotFound, discord.Forbidden):
            if self._deactivate_channel(chat_id, abort_agent=False):
                print(f"[Discord] pruned unavailable active channel: {chat_id}")
            return False
        except Exception as e:
            print(f"[Discord] active channel validation skipped for {chat_id}: {type(e).__name__}: {e}")
            return True

    async def _cleanup_active_channels_once(self):
        for chat_id in self._active_channel_ids_snapshot():
            await self._validate_active_channel(chat_id)
            await asyncio.sleep(ACTIVE_CLEANUP_FETCH_DELAY_SECONDS)

    def _seconds_until_next_active_cleanup(self):
        now = time.localtime()
        target = time.mktime((
            now.tm_year, now.tm_mon, now.tm_mday,
            ACTIVE_CLEANUP_HOUR, ACTIVE_CLEANUP_MINUTE, 0,
            now.tm_wday, now.tm_yday, now.tm_isdst,
        ))
        if target <= time.time():
            target += 24 * 3600
        return max(60, target - time.time())

    async def _active_channel_cleanup_loop(self):
        while True:
            await asyncio.sleep(self._seconds_until_next_active_cleanup())
            try:
                await self._cleanup_active_channels_once()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"[Discord] active channel cleanup error: {type(e).__name__}: {e}")

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

    async def send_text(self, chat_id, content, silent=False, **ctx):
        """Send text (and optionally files) to a chat_id."""
        interaction = ctx.pop("interaction", None)
        if interaction is not None:
            return await self._reply_interaction(interaction, content, silent=silent)
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
            except (discord.NotFound, discord.Forbidden) as e:
                print(f"[Discord] cannot resolve active channel for {chat_id}: {type(e).__name__}: {e}")
                if chat_id.startswith("ch:"):
                    self._deactivate_channel(chat_id, abort_agent=False)
                return
            except Exception as e:
                print(f"[Discord] cannot resolve channel for {chat_id}: {e}")
                return
        first_message = None
        for part in split_text(content, self.split_limit):
            try:
                msg = await channel.send(part, silent=silent)
                if first_message is None:
                    first_message = msg
            except Exception as e:
                print(f"[Discord] send error: {e}")
        return first_message

    async def send_done(self, chat_id, raw_text, notify_user_id=None, allow_files=False, **ctx):
        """Send final reply: text parts + file attachments only after explicit user request."""
        file_refs = [p.strip() for p in extract_files(raw_text) if p and p.strip()]
        if not allow_files and file_refs:
            print(f"[Discord] blocked {len(file_refs)} file ref(s): user did not explicitly request a file")
        files = [p for p in file_refs if allow_files and _is_sendable_discord_file(p)]
        for p in file_refs:
            if os.path.isdir(p):
                print(f"[Discord] skip directory file ref: {p}")
            elif not os.path.exists(p):
                print(f"[Discord] skip missing file ref: {p}")
        body = _display_done_text(raw_text)
        if notify_user_id and body and body != "...":
            body = f"<@{notify_user_id}> {body}"

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
                        await self.send_text(chat_id, f"⚠️ 文件发送失败: {os.path.basename(fpath)} ({type(e).__name__}: {e})", **ctx)

        if not body and not files:
            await self.send_text(chat_id, "...", **ctx)

    async def handle_command(self, chat_id, cmd, **ctx):
        """Handle slash commands against the per-chat agent, keeping Discord chats isolated."""
        sender = self._send_via_interaction if "interaction" in ctx else self.send_text
        ga = self._get_agent(chat_id)
        parts = (cmd or "").split()
        op = (parts[0] if parts else "").lower()
        if op == "/help":
            return await sender(chat_id, HELP_TEXT, **ctx)
        if op == "/stop":
            state = self.user_tasks.get(chat_id)
            if state:
                state["running"] = False
            ga.abort()
            return await sender(chat_id, "⏹️ 正在停止...", **ctx)
        if op == "/status":
            llm = ga.get_llm_name() if ga.llmclient else "未配置"
            return await sender(chat_id, f"状态: {'🔴 运行中' if ga.is_running else '🟢 空闲'}\nLLM: [{ga.llm_no}] {llm}", **ctx)
        if op == "/llm":
            if not ga.llmclient:
                return await sender(chat_id, "❌ 当前没有可用的 LLM 配置", **ctx)
            if len(parts) > 1:
                try:
                    ga.next_llm(int(parts[1]))
                    return await sender(chat_id, f"✅ 已切换到 [{ga.llm_no}] {ga.get_llm_name()}", **ctx)
                except Exception:
                    return await sender(chat_id, f"用法: /llm <0-{len(ga.list_llms()) - 1}>", **ctx)
            lines = [f"{'→' if cur else '  '} [{i}] {name}" for i, name, cur in ga.list_llms()]
            return await sender(chat_id, "LLMs:\n" + "\n".join(lines), **ctx)
        if op == "/restore":
            try:
                restored_info, err = format_restore()
                if err:
                    return await sender(chat_id, err, **ctx)
                restored, fname, count = restored_info
                ga.abort()
                ga.history.extend(restored)
                return await sender(chat_id, f"✅ 已恢复 {count} 轮对话\n来源: {fname}\n(仅恢复上下文，请输入新问题继续)", **ctx)
            except Exception as e:
                return await sender(chat_id, f"❌ 恢复失败: {e}", **ctx)
        if op == "/continue":
            return await sender(chat_id, _handle_continue_frontend(ga, cmd), **ctx)
        if op == "/new":
            return await sender(chat_id, _reset_conversation(ga), **ctx)
        return await sender(chat_id, HELP_TEXT, **ctx)

    async def run_agent(self, chat_id, text, **ctx):
        """Run the isolated per-chat Discord agent."""
        sender = self._send_via_interaction if "interaction" in ctx else self.send_text
        ga = self._get_agent(chat_id)
        existing = self.user_tasks.get(chat_id)
        if existing and existing.get("running"):
            await sender(chat_id, "已有任务正在运行，请等待完成，或使用 /stop 停止后再发新任务。", silent=True, **ctx)
            return
        state = {"running": True}
        self.user_tasks[chat_id] = state
        progress = _DiscordProgressMessage(self, chat_id, ctx)
        try:
            await progress.start()
            allow_files = _user_requested_file_send(text)
            file_hint = DISCORD_FILE_SEND_HINT if allow_files else DISCORD_FILE_NO_SEND_HINT
            dq = ga.put_task(f"{DISCORD_FILE_HINT}\n{file_hint}\n\n{text}", source=self.source)
            last_ping = time.time()
            while state["running"]:
                try:
                    item = await asyncio.to_thread(dq.get, True, 3)
                except Q.Empty:
                    if ga.is_running and time.time() - last_ping > self.ping_interval:
                        await progress.heartbeat()
                        last_ping = time.time()
                    continue
                if "next" in item:
                    turn = _extract_discord_turn(item.get("next", ""))
                    step = _extract_discord_progress(item.get("next", ""))
                    if step or turn is not None:
                        await progress.update(step, turn=turn)
                        last_ping = time.time()
                    continue
                if "done" in item:
                    await progress.finish()
                    await self.send_done(chat_id, item.get("done", ""), allow_files=allow_files, **ctx)
                    break
            if not state["running"]:
                await sender(chat_id, "⏹️ 已停止", **ctx)
        except Exception as e:
            import traceback
            print(f"[{self.label}] run_agent error: {e}")
            traceback.print_exc()
            await sender(chat_id, f"❌ 错误: {e}", **ctx)
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

        notify_user_id = user_id if is_guild else None
        task = asyncio.create_task(self.run_agent(chat_id, content, notify_user_id=notify_user_id))
        self.background_tasks.add(task)
        task.add_done_callback(self.background_tasks.discard)

    async def start(self):
        print(f"[Discord] bot starting... pid={os.getpid()} python={sys.executable}")
        delay, max_delay = 5, 300
        while True:
            started_at = time.monotonic()
            try:
                if getattr(self, "client", None) is not None and self.client.is_closed():
                    self._build_client()
                await self.client.start(BOT_TOKEN)
            except KeyboardInterrupt:
                raise
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"[Discord] disconnected/error: {type(e).__name__}: {e}")
            finally:
                old_client = getattr(self, "client", None)
                if old_client is not None and not old_client.is_closed():
                    try:
                        await old_client.close()
                    except Exception as e:
                        print(f"[Discord] client close failed: {type(e).__name__}: {e}")
                self._build_client()
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
