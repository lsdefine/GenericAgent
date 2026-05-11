"""
Subagent 集群监控 Dashboard
=============================
基于 Streamlit，实时监控所有活跃 subagent 的运行状态。
支持：查看进度、阅读日志、远程干预（停止/注入指令）。

启动方式：
    streamlit run frontends/subagent_dashboard.py
"""

import os, sys, glob, time, subprocess, json, re
from datetime import datetime, timedelta
from pathlib import Path

import streamlit as st

# ── 路径配置 ──
CODE_ROOT = Path(__file__).resolve().parent.parent
TEMP_DIR = CODE_ROOT / "temp"

# ── 页面配置 ──
st.set_page_config(
    page_title="Subagent 集群监控",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── 样式美化 ──
st.markdown("""
<style>
    .agent-card {
        border: 1px solid #ddd;
        border-radius: 12px;
        padding: 16px;
        margin-bottom: 16px;
        background: #fafafa;
        transition: box-shadow 0.3s ease;
    }
    .agent-card:hover { box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
    .agent-card.running { border-left: 5px solid #4CAF50; }
    .agent-card.waiting { border-left: 5px solid #FF9800; }
    .agent-card.done    { border-left: 5px solid #2196F3; }
    .agent-card.stopped { border-left: 5px solid #9E9E9E; }
    .agent-card.error   { border: 2px solid #f44336; border-left: 6px solid #f44336; }
    @keyframes pulse-border {
        0%   { box-shadow: 0 0 0 0 rgba(76, 175, 80, 0.4); }
        70%  { box-shadow: 0 0 0 8px rgba(76, 175, 80, 0); }
        100% { box-shadow: 0 0 0 0 rgba(76, 175, 80, 0); }
    }
    .agent-card.running { animation: pulse-border 2s infinite; }
    .status-badge {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 12px;
        font-size: 0.8em;
        font-weight: bold;
        color: white;
    }
    .status-running { background: #4CAF50; }
    .status-waiting { background: #FF9800; }
    .status-done    { background: #2196F3; }
    .status-stopped { background: #9E9E9E; }
    .metric-box {
        text-align: center;
        padding: 8px;
        background: white;
        border-radius: 8px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    }
    .log-viewer {
        background: #1e1e1e;
        color: #d4d4d4;
        padding: 12px;
        border-radius: 8px;
        font-family: 'Courier New', monospace;
        font-size: 0.85em;
        max-height: 300px;
        overflow-y: auto;
        white-space: pre-wrap;
        word-break: break-all;
    }
    div[data-testid="stHorizontalBlock"] { gap: 1rem; }
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════
#  核心函数
# ═══════════════════════════════════════════════════════════════

def get_subagent_dirs():
    """扫描 temp/ 下所有含 input.txt 的子目录（视为 subagent 任务目录）"""
    if not TEMP_DIR.exists():
        return []
    dirs = []
    for d in sorted(TEMP_DIR.iterdir()):
        if d.is_dir() and (d / "input.txt").exists():
            dirs.append(d)
    return dirs


def get_running_pids():
    """获取所有 Python 进程的 {PID: command_line} 映射
    优先级: psutil → wmic → tasklist → 空（由启发式兜底）
    """
    pid_map = {}

    # ── 方法1: psutil（最准确） ──
    try:
        import psutil
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                name = proc.info['name'] or ''
                if 'python' in name.lower():
                    cmdline = ' '.join(proc.info['cmdline'] or [])
                    pid_map[proc.info['pid']] = cmdline
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        if pid_map:
            return pid_map
    except ImportError:
        pass

    # ── 方法2: wmic (Windows) ──
    try:
        result = subprocess.run(
            'wmic process where "name=\'python.exe\' or name=\'pythonw.exe\'" get processid,commandline /FORMAT:CSV',
            capture_output=True, text=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW
        )
        for line in result.stdout.strip().split('\n')[1:]:  # skip header
            if not line.strip(): continue
            parts = line.split(',', 2)
            if len(parts) >= 3:
                cmd = parts[1].strip('"')
                pid_str = parts[2].strip('"')
                if pid_str.isdigit():
                    pid_map[int(pid_str)] = cmd
        if pid_map:
            return pid_map
    except Exception:
        pass

    # ── 方法3: tasklist 兜底 ──
    try:
        result = subprocess.run(
            'tasklist /NH /FI "IMAGENAME eq python.exe" /FO CSV',
            capture_output=True, text=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW
        )
        for line in result.stdout.strip().split('\n'):
            if not line.strip(): continue
            parts = line.split(',')
            if len(parts) >= 2 and parts[1].strip('"').isdigit():
                pid_map[int(parts[1].strip('"'))] = "python.exe"
    except Exception:
        pass

    # ── 方法4: 都不行就返回空（后续启发式兜底） ──
    return pid_map



def _extract_model_name(task_dir: Path) -> str:
    """从 stdout.log 首部提取模型/session 名称"""
    log_file = task_dir / "stdout.log"
    if not log_file.exists():
        return "未知"
    try:
        raw = log_file.read_bytes()
        for enc in ['utf-8', 'gbk', 'cp936']:
            try:
                head = raw.decode(enc)[:2000]
                break
            except (UnicodeDecodeError, LookupError):
                continue
        else:
            return "未知"
        m = re.search(r'Using session\s*\(([^)]+)\)', head)
        if m:
            return m.group(1)
        m = re.search(r'(?:model|model_name)\s*[:=]\s*["\']?([^"\'\\\s,;)]+)', head, re.IGNORECASE)
        if m:
            return m.group(1)
        return "未知"
    except Exception:
        return "未知"

def get_subagent_status(task_dir: Path, pid_map: dict):
    """
    判断 subagent 运行状态
    返回: (status, pid, runtime_seconds, latest_output, all_outputs, logs)
    """
    # ── 读取所有文件 ──
    input_text = ""
    if (task_dir / "input.txt").exists():
        input_text = (task_dir / "input.txt").read_text(encoding='utf-8', errors='replace')[:300]

    # 收集 output 文件（按编号排序）
    output_files = sorted(
        (f for f in task_dir.glob("output*.txt") if f.name != "output.txt"),
        key=lambda f: int(re.search(r'(\d+)', f.stem).group(1)) if re.search(r'(\d+)', f.stem) else 0
    )
    all_outputs = []
    for f in output_files:
        try:
            content = f.read_text(encoding='utf-8', errors='replace')
            all_outputs.append({"file": f.name, "content": content})
        except Exception:
            all_outputs.append({"file": f.name, "content": "[读取失败]"})

    latest_output = all_outputs[-1]["content"] if all_outputs else ""
    latest_output_preview = latest_output[:800] if latest_output else "(无输出)"

    # 读取日志（带编码检测）
    def _detect_and_read(file_path: Path, tail_bytes: int = 3000):
        """尝试 UTF-8 → GBK → replace 逐级降级读取文件尾部"""
        if not file_path.exists():
            return "", "File Not Found"
        raw = file_path.read_bytes()
        for enc in ['utf-8', 'gbk', 'cp936']:
            try:
                text = raw.decode(enc)
                return text[-tail_bytes:], enc
            except (UnicodeDecodeError, LookupError):
                continue
        # 最后手段：replace
        text = raw.decode('utf-8', errors='replace')
        return text[-tail_bytes:], f"utf-8(replace)"




    stdout_log = ""
    stdout_enc = ""
    if (task_dir / "stdout.log").exists():
        stdout_log, stdout_enc = _detect_and_read(task_dir / "stdout.log", 3000)

    stderr_log = ""
    stderr_enc = ""
    if (task_dir / "stderr.log").exists():
        stderr_log, stderr_enc = _detect_and_read(task_dir / "stderr.log", 2000)

    # 构造编码显示标签
    enc_label = ""
    if stdout_enc and stderr_enc:
        enc_label = f"stdout:{stdout_enc} | stderr:{stderr_enc}"
    elif stdout_enc:
        enc_label = f"stdout:{stdout_enc}"

    # ── 判断状态 ──
    # 1. 是否有 _stop 文件
    if (task_dir / "_stop").exists():
        return ("stopped", None, 0, latest_output_preview, all_outputs, stdout_log, stderr_log, input_text, enc_label)

    # 2. 检查进程是否存活
    pid = None
    is_alive = False

    # 精确匹配：进程命令行包含任务名和 agentmain/--task
    for p, cmdline in pid_map.items():
        if str(task_dir.name) in cmdline and ('agentmain' in cmdline or '--task' in cmdline):
            pid = p
            is_alive = True
            break

    # 3. 启发式判断（当 pid_map 为空或未匹配时）
    if not is_alive:
        # 检查 output 文件最近是否有更新（3分钟内视为可能存活）
        # 排除无编号的 output.txt（仅文件头，非轮次输出）
        try:
            now = time.time()
            recent_files = [
                f for f in task_dir.glob("output*.txt")
                if re.search(r'output(\d+)\.txt$', f.name)
                and now - f.stat().st_mtime < 180
            ]
            if recent_files:
                # 有最近更新的 output 文件 → 倾向认为还在运行
                is_alive = True
        except Exception:
            pass

    # 4. 判断运行阶段
    has_round_end = "[ROUND END]" in latest_output if latest_output else False
    has_reply_file = (task_dir / "reply.txt").exists()

    if is_alive:
        if has_round_end and not has_reply_file:
            status = "waiting"       # 等待用户回复
        else:
            status = "running"       # 正在执行
    else:
        if latest_output:
            status = "done"          # 已完成
        else:
            status = "stopped"       # 未正常启动

    # 估算运行时长
    runtime = 0
    if output_files:
        try:
            first_mtime = output_files[0].stat().st_mtime
            runtime = int(time.time() - first_mtime)
        except Exception:
            pass

    return (status, pid, runtime, latest_output_preview, all_outputs, stdout_log, stderr_log, input_text, enc_label)


def render_agent_card(task_dir: Path, status_info: tuple):
    """渲染单个 subagent 的状态卡片"""
    status, pid, runtime, latest_preview, all_outputs, stdout_log, stderr_log, input_text, enc_label = status_info

    status_emoji = {
        "running": "▶️", "waiting": "⏸️", "done": "✅", "stopped": "⏹️"
    }
    status_label = {
        "running": "运行中", "waiting": "等待回复", "done": "已完成", "stopped": "已停止"
    }

    agent_name = task_dir.name
    model_name = _extract_model_name(task_dir)
    emoji = status_emoji.get(status, "❓")
    label = status_label.get(status, "未知")

    # 检测是否有错误 (stderr.log 非空)
    has_error = bool(stderr_log and stderr_log.strip())
    card_class = status if status in status_label else "stopped"
    if has_error:
        card_class += " error"

    runtime_str = str(timedelta(seconds=runtime)) if runtime > 0 else "—"

    with st.container():
        st.markdown(f'<div class="agent-card {card_class}">', unsafe_allow_html=True)

        # ── 标题行（始终显示） ──
        cols = st.columns([3, 1, 1.2, 1, 1, 1, 0.5])
        with cols[0]:
            st.markdown(f"### {emoji} {agent_name}")
        with cols[1]:
            st.markdown(
                f'<span class="status-badge status-{status}">{label}</span>',
                unsafe_allow_html=True
            )
        with cols[2]:
            st.markdown(f'<div class="metric-box" style="font-size:0.8em;">🤖 {model_name}</div>', unsafe_allow_html=True)
        with cols[3]:
            st.markdown(
                f'<div class="metric-box">⏱ {runtime_str}</div>',
                unsafe_allow_html=True
            )
        if pid:
            with cols[4]:
                st.markdown(f'<div class="metric-box">🆔 {pid}</div>', unsafe_allow_html=True)
        with cols[5]:
            if status in ("running", "waiting"):
                if st.button(f"🛑 停止", key=f"stop_{agent_name}"):
                    (task_dir / "_stop").write_text("", encoding='utf-8')
                    st.rerun()

        # 错误提示角标
        if has_error:
            with cols[6]:
                st.markdown(
                    f'<div style="color:#f44336;font-size:1.2em;" title="stderr.log 有内容">⚠️</div>',
                    unsafe_allow_html=True
                )

        # ── 折叠展开详情（默认折叠） ──
        with st.expander("📋 详情", expanded=False):
            # ── 任务输入预览 ──
            with st.expander("📋 任务描述", expanded=False):
                st.code(input_text, language="text")

            # ── 最新输出摘要 ──
            st.markdown("**📄 最新输出**")
            st.text_area(
                label="最新输出",
                value=latest_preview,
                height=120,
                key=f"output_{agent_name}",
                label_visibility="collapsed",
            )

            # ── 日志与详情（折叠） ──
            log_tab, output_tab, intervene_tab = st.tabs(["📋 日志", "📚 全部输出", "✏️ 干预"])

            with log_tab:
                if enc_label:
                    st.caption(f"🔤 编码检测: {enc_label}")
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown("**stdout.log** (尾部)")
                    st.code(stdout_log[-2000:], language="text", line_numbers=True)
                with col2:
                    st.markdown("**stderr.log** (尾部)")
                    st.code(stderr_log[-2000:] if stderr_log else "(空)", language="text", line_numbers=True)
                # 刷新日志按钮
                if st.button(f"🔄 刷新日志", key=f"refresh_log_{agent_name}"):
                    st.rerun()

            with output_tab:
                for i, o in enumerate(all_outputs):
                    expand = (i == len(all_outputs) - 1)  # 最新一条默认展开
                    with st.expander(f"📄 {o['file']}", expanded=expand):
                        st.text_area(
                            label=f"完整输出 - {o['file']}",
                            value=o["content"][:5000],
                            height=200,
                            key=f"full_output_{agent_name}_{i}",
                            label_visibility="collapsed",
                        )

            with intervene_tab:
                st.markdown("**写入干预指令**（subagent 下轮执行时会读取）")
                intervene_text = st.text_area(
                    label="干预内容",
                    value="",
                    height=100,
                    placeholder="例如: 停止搜索，改为整理已有数据...",
                    key=f"intervene_input_{agent_name}",
                    label_visibility="collapsed",
                )
                col1, col2, col3 = st.columns(3)
                with col1:
                    if st.button(f"📨 发送干预", key=f"send_intervene_{agent_name}"):
                        if intervene_text.strip():
                            (task_dir / "_intervene").write_text(intervene_text.strip(), encoding='utf-8')
                            st.success("✅ 干预指令已发送，下轮生效")
                            st.rerun()
                with col2:
                    st.markdown("**注入工作记忆**")
                    keyinfo_text = st.text_input(
                        label="key_info",
                        value="",
                        placeholder="注入到 working memory 的信息",
                        key=f"keyinfo_{agent_name}",
                        label_visibility="collapsed",
                    )
                    if st.button(f"🧠 注入记忆", key=f"send_keyinfo_{agent_name}"):
                        if keyinfo_text.strip():
                            (task_dir / "_keyinfo").write_text(keyinfo_text.strip(), encoding='utf-8')
                            st.success("✅ 已注入工作记忆")
                            st.rerun()
                with col3:
                    if status == "waiting":
                        reply_text = st.text_input(
                            label="回复",
                            value="",
                            placeholder="给 subagent 的回复...",
                            key=f"reply_{agent_name}",
                            label_visibility="collapsed",
                        )
                        if st.button(f"💬 发送回复", key=f"send_reply_{agent_name}"):
                            if reply_text.strip():
                                (task_dir / "reply.txt").write_text(reply_text.strip(), encoding='utf-8')
                                st.success("✅ 回复已发送，subagent 将继续执行")
                                st.rerun()

        st.markdown('</div>', unsafe_allow_html=True)


def render_cluster_overview(agent_statuses):
    """渲染集群概览"""
    total = len(agent_statuses)
    running = sum(1 for s in agent_statuses if s == "running")
    waiting = sum(1 for s in agent_statuses if s == "waiting")
    done = sum(1 for s in agent_statuses if s == "done")
    stopped = sum(1 for s in agent_statuses if s == "stopped")

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("🧠 总数", total)
    with col2:
        st.metric("▶️ 运行中", running)
    with col3:
        st.metric("⏸️ 等待回复", waiting)
    with col4:
        st.metric("✅ 已完成", done)
    with col5:
        st.metric("⏹️ 已停止", stopped)


# ═══════════════════════════════════════════════════════════════
#  主界面
# ═══════════════════════════════════════════════════════════════

def main():
    st.title("🧠 Subagent 集群监控")
    st.markdown(f"> 代码根目录：`{CODE_ROOT}`  监控目录：`{TEMP_DIR}`")

    # ── 侧边栏 ──
    with st.sidebar:
        st.markdown("### ⚙️ 控制面板")

        # 自动刷新
        auto_refresh = st.checkbox("🔄 自动刷新 (3s)", value=True)
        refresh_interval = st.slider("刷新间隔(秒)", 1, 10, 3)

        st.divider()

        if st.button("🔄 手动刷新", use_container_width=True):
            st.rerun()

        st.divider()
        st.markdown("### 🚀 Agent 启动面板")

        with st.form("launch_agent_form", clear_on_submit=True):
            task_name = st.text_input("Task Name", placeholder="如：调研员", key="launch_name")
            task_prompt = st.text_area("Task Prompt", placeholder="输入任务描述...", height=100, key="launch_prompt")
            llm_no = st.selectbox(
                "模型选择",
                options=["默认 (0)", "模型1 (1)", "模型2 (2)", "模型3 (3)", "模型4 (4)"],
                index=0,
                key="launch_llm_no",
                help="对应 agentmain.py 的 --llm_no 参数，在 mykey.py 中定义多个 session config 后生效"
            )
            launched = st.form_submit_button("▶️ 启动 Agent", use_container_width=True, type="primary")

        if launched:
            if not task_name.strip():
                st.error("❌ Task Name 不能为空")
            elif not task_prompt.strip():
                st.error("❌ Task Prompt 不能为空")
            else:
                try:
                    agentmain_path = CODE_ROOT / "agentmain.py"
                    # 从 selectbox 的 label 中提取数字
                    selected_no = int(llm_no.split("(")[1].split(")")[0])
                    cmd = [
                        sys.executable, str(agentmain_path),
                        "--task", task_name.strip(),
                        "--input", task_prompt.strip(),
                        "--llm_no", str(selected_no),
                        "--bg"
                    ]
                    subprocess.Popen(
                        cmd,
                        cwd=str(CODE_ROOT),
                        creationflags=subprocess.CREATE_NO_WINDOW
                    )
                    st.success(f"✅ Agent「{task_name}」启动中… (llm_no={selected_no})")
                    time.sleep(0.5)
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ 启动失败: {e}")

        st.divider()
        st.markdown("### 📖 文件协议")

        st.markdown("""
        **干预文件** (位于 `temp/{任务名}/`):
        - `_stop` — 停止 subagent (空文件)
        - `_intervene` — 追加指令 (文本)
        - `_keyinfo` — 注入工作记忆 (文本)
        - `reply.txt` — 回复等待中的 agent

        **输出文件**:
        - `output{n}.txt` — 每轮输出
        - `stdout.log` — 控制台日志
        - `stderr.log` — 错误日志
        """)

        st.divider()
        st.markdown(f"🕐 上次刷新：{datetime.now():%H:%M:%S}")
        st.caption("💡 提示：自动刷新时不要操作干预控件，避免冲突")

    # ── 主区域 ──
    main_placeholder = st.empty()

    with main_placeholder.container():
        # 获取 subagent 列表
        agent_dirs = get_subagent_dirs()

        if not agent_dirs:
            st.info("📭 当前没有活跃的 subagent。启动 subagent 后状态会在此显示。")
            st.markdown("""
            **如何启动 subagent？**
            ```bash
            cd D:\\open_claw_agent\\GenericAgent
            python agentmain.py --task 调研员 --input "你是调研员，请搜索..." --bg
            python agentmain.py --task 程序员 --input "你是程序员，请编写..." --bg
            ```
            """)
            if auto_refresh:
                time.sleep(refresh_interval)
                st.rerun()
            return

        # 获取进程信息
        pid_map = get_running_pids()

        # 收集所有 agent 状态
        agent_statuses = []
        for d in agent_dirs:
            status_info = get_subagent_status(d, pid_map)
            agent_statuses.append((d.name, status_info))

        # ── 集群概览 ──
        st.markdown("### 📊 集群概览")
        statuses_only = [s[1][0] for s in agent_statuses]
        render_cluster_overview(statuses_only)

        st.divider()

        # ── 每个 Agent 卡片 ──
        st.markdown(f"### 🔍 详情 ({len(agent_dirs)} 个 agent)")

        for name, status_info in agent_statuses:
            task_dir = TEMP_DIR / name
            render_agent_card(task_dir, status_info)
            st.divider()

    # ── 自动刷新 ──
    if auto_refresh:
        time.sleep(refresh_interval)
        st.rerun()


if __name__ == "__main__":
    main()