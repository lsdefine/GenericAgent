"""
桌面前端单文件版 – PySide6 聊天面板 + 悬浮按钮   thanks to GaoZhiCheng
依赖: pip install PySide6
可选: pip install markdown  (Markdown 渲染)
用法: python frontends/qtapp.py 
"""
from __future__ import annotations

import math, os, sys, json, glob, re, base64, time, threading
import queue as _queue
from datetime import datetime
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QTextEdit, QStackedWidget,
    QListWidget, QListWidgetItem, QSizePolicy, QFileDialog,
    QSplitter, QTextBrowser, QApplication, QMessageBox,
)
from PySide6.QtCore import (
    Qt, QTimer, QPoint, QPointF, QByteArray, QSize,
    Signal, QMetaObject, Q_ARG, QObject, QDateTime, QEvent,
)
from PySide6.QtGui import (
    QPainter, QColor, QLinearGradient, QRadialGradient,
    QPen, QPainterPath, QCursor, QFont, QIcon, QPixmap, QRegion,
)

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from agentmain import GeneraticAgent


# ══════════════════════════════════════════════════════════════════════
# FloatingButton
# ══════════════════════════════════════════════════════════════════════

class FloatingButton(QWidget):
    SIZE = 60       # circle diameter
    MARGIN = 14     # extra space for glow
    TOTAL = SIZE + MARGIN * 2

    def __init__(self, chat_panel: QWidget):
        super().__init__()
        self.chat_panel = chat_panel
        self._drag_origin_global: QPoint | None = None
        self._drag_origin_win: QPoint | None = None
        self._dragged = False
        self._glow = 0.5
        self._glow_dir = 1
        self._hovering = False
        self._hover_clock = 0.0
        self._hover_strength = 0.0
        self._flow_phase = 0.0
        self._running = False
        self._last_toggle_ms = 0  # debounce timestamp

        # Window flags: frameless, always on top, no taskbar entry
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(self.TOTAL, self.TOTAL)
        self.setCursor(QCursor(Qt.PointingHandCursor))

        # Smooth animation (~30 fps)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

        # Default position: bottom-right of the work area
        scr = QApplication.primaryScreen().availableGeometry()
        self.move(scr.right() - self.TOTAL - 20, scr.bottom() - self.TOTAL - 20)

    # ── Animation ────────────────────────────────────────
    def _tick(self):
        # running status: green when model is actively responding
        self._running = bool(
            getattr(self.chat_panel, "_is_streaming", False)
            or getattr(getattr(self.chat_panel, "agent", None), "is_running", False)
        )

        self._glow += self._glow_dir * 0.04
        if self._glow >= 1.0:
            self._glow, self._glow_dir = 1.0, -1
        elif self._glow <= 0.0:
            self._glow, self._glow_dir = 0.0, 1

        target = 1.0 if self._hovering else 0.0
        self._hover_strength += (target - self._hover_strength) * 0.20
        self._hover_clock += 0.033
        self._flow_phase += 0.16 + (0.06 if self._running else 0.0) + (0.05 if self._hovering else 0.0)
        self.update()

    # ── Painting ──────────────────────────────────────────
    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        m = self.MARGIN
        r = self.SIZE // 2
        cx = m + r
        # Rhythmic spring bounce: one main hop + one lighter rebound per beat.
        beat_t = self._hover_clock % 1.18
        spring = 0.0
        if beat_t < 0.70:
            spring += max(0.0, math.exp(-5.2 * beat_t) * math.sin(15.5 * beat_t))
        if beat_t > 0.20:
            rt = beat_t - 0.20
            spring += 0.52 * max(0.0, math.exp(-7.0 * rt) * math.sin(21.0 * rt))
        idle_sway = 0.20 * math.sin(self._hover_clock * 2.1)
        bounce = int(round((spring * 7.2 + idle_sway) * self._hover_strength))
        cy = m + r - bounce

        if self._running:
            # running: #2DFFF5 -> #FFF878
            g0 = QColor(45, 255, 245, 195)
            g1 = QColor(255, 248, 120, 195)
            glow_rgb = (96, 255, 216)
        else:
            # idle: #103CE7 -> #64E9FF
            g0 = QColor(16, 60, 231, 195)
            g1 = QColor(100, 233, 255, 195)
            glow_rgb = (74, 170, 255)

        # --- Outer glow rings (3 layers) ---
        base_alpha = int(45 + 25 * self._glow)
        for i, gr in enumerate([r + 10, r + 6, r + 2]):
            g = QRadialGradient(QPointF(cx, cy), gr)
            g.setColorAt(0.0, QColor(glow_rgb[0], glow_rgb[1], glow_rgb[2], max(0, base_alpha - i * 14)))
            g.setColorAt(1.0, QColor(glow_rgb[0], glow_rgb[1], glow_rgb[2], 0))
            p.setBrush(g)
            p.setPen(Qt.NoPen)
            p.drawEllipse(int(cx - gr), int(cy - gr), int(gr * 2), int(gr * 2))

        # --- Frosted glass disc behind main circle ---
        frost = QRadialGradient(QPointF(cx, cy), r)
        frost.setColorAt(0.0, QColor(30, 30, 45, 140))
        frost.setColorAt(0.85, QColor(20, 20, 32, 160))
        frost.setColorAt(1.0, QColor(14, 14, 20, 100))
        p.setBrush(frost)
        p.setPen(Qt.NoPen)
        p.drawEllipse(cx - r, cy - r, r * 2, r * 2)

        # --- Main circle (flowing state gradient) ---
        spin = self._flow_phase
        dx = math.cos(spin) * r
        dy = math.sin(spin) * r
        grad = QLinearGradient(cx - dx, cy - dy, cx + dx, cy + dy)
        grad.setColorAt(0.0, g0)
        grad.setColorAt(1.0, g1)
        p.setBrush(grad)
        p.setPen(QPen(QColor(255, 255, 255, 50), 1.5))
        p.drawEllipse(cx - r, cy - r, r * 2, r * 2)

        # --- Flowing glass streaks ---
        clip = QPainterPath()
        clip.addEllipse(float(cx - r), float(cy - r), float(r * 2), float(r * 2))
        p.setClipPath(clip)

        flow_shift = math.sin(self._flow_phase * 0.85) * (r * 0.7)
        streak1 = QLinearGradient(cx - r + flow_shift, cy - r, cx + r + flow_shift, cy + r)
        streak1.setColorAt(0.00, QColor(255, 255, 255, 0))
        streak1.setColorAt(0.45, QColor(255, 255, 255, 42))
        streak1.setColorAt(0.52, QColor(255, 255, 255, 78))
        streak1.setColorAt(0.60, QColor(255, 255, 255, 24))
        streak1.setColorAt(1.00, QColor(255, 255, 255, 0))
        p.setBrush(streak1)
        p.setPen(Qt.NoPen)
        p.drawEllipse(cx - r, cy - r, r * 2, r * 2)

        flow_shift_2 = math.cos(self._flow_phase * 1.2) * (r * 0.5)
        streak2 = QLinearGradient(cx - r, cy + flow_shift_2, cx + r, cy - flow_shift_2)
        streak2.setColorAt(0.00, QColor(255, 255, 255, 0))
        streak2.setColorAt(0.35, QColor(255, 255, 255, 16))
        streak2.setColorAt(0.50, QColor(255, 255, 255, 46))
        streak2.setColorAt(0.65, QColor(255, 255, 255, 16))
        streak2.setColorAt(1.00, QColor(255, 255, 255, 0))
        p.setBrush(streak2)
        p.drawEllipse(cx - r, cy - r, r * 2, r * 2)

        # --- Top highlight ---
        hl = QLinearGradient(cx, cy - r, cx, cy)
        hl.setColorAt(0.0, QColor(255, 255, 255, 72))
        hl.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setBrush(hl)
        p.drawRect(cx - r, cy - r, r * 2, r)
        p.setClipping(False)

        # --- Bot icon ---
        p.setPen(QPen(QColor(255, 255, 255, 220), 1.8))
        p.setBrush(Qt.NoBrush)
        # Head
        p.drawRoundedRect(cx - 9, cy - 6, 18, 12, 2, 2)
        # Eyes
        p.setBrush(QColor(255, 255, 255, 220))
        p.setPen(Qt.NoPen)
        p.drawEllipse(cx - 6, cy - 3, 4, 4)
        p.drawEllipse(cx + 2, cy - 3, 4, 4)
        # Antenna stem
        p.setPen(QPen(QColor(255, 255, 255, 220), 1.8))
        p.drawLine(cx, cy - 6, cx, cy - 10)
        # Antenna tip
        p.setBrush(QColor(255, 255, 255, 190))
        p.setPen(Qt.NoPen)
        p.drawEllipse(cx - 2, cy - 13, 4, 4)

    def enterEvent(self, event):
        self._hovering = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovering = False
        self.update()
        super().leaveEvent(event)

    # ── Mouse events (drag + click) ───────────────────────
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_origin_global = event.globalPosition().toPoint()
            self._drag_origin_win = self.pos()
            self._dragged = False

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and self._drag_origin_global:
            delta = event.globalPosition().toPoint() - self._drag_origin_global
            if abs(delta.x()) > 5 or abs(delta.y()) > 5:
                self._dragged = True
            if self._dragged:
                new = self._drag_origin_win + delta
                scr = QApplication.primaryScreen().availableGeometry()
                new.setX(max(scr.left(), min(new.x(), scr.right() - self.width())))
                new.setY(max(scr.top(), min(new.y(), scr.bottom() - self.height())))
                self.move(new)

    def mouseDoubleClickEvent(self, event):
        # Qt sends Press→Release→DoubleClick→Release on double-click.
        # The first Release already toggled the panel; swallow the DoubleClick
        # so the second Release does NOT trigger a second toggle.
        self._dragged = True   # mark as "dragged" → Release will be ignored
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            if not self._dragged:
                self._toggle()
            self._dragged = False
        self._drag_origin_global = None

    # ── Toggle panel ──────────────────────────────────────
    def _toggle(self):
        from PySide6.QtCore import QDateTime
        now = QDateTime.currentMSecsSinceEpoch()
        if now - self._last_toggle_ms < 500:   # 500 ms debounce
            return
        self._last_toggle_ms = now

        if self.chat_panel.isVisible():
            self.chat_panel.hide()
        else:
            self._position_panel()
            self.chat_panel.show()
            self.chat_panel.raise_()
            self.chat_panel.activateWindow()

    def _position_panel(self):
        scr = QApplication.primaryScreen().availableGeometry()
        btn = self.geometry()
        pw = self.chat_panel.width()
        ph = self.chat_panel.height()
        # Prefer left of button, bottom-aligned
        x = btn.left() - pw - 12
        y = btn.bottom() - ph
        x = max(scr.left() + 10, min(x, scr.right() - pw - 10))
        y = max(scr.top() + 10, min(y, scr.bottom() - ph - 10))
        self.chat_panel.move(x, y)


# ══════════════════════════════════════════════════════════════════════
# ChatPanel
# ══════════════════════════════════════════════════════════════════════

# ── constants ─────────────────────────────────────────────────────────────────
HISTORY_FILE = "memory/chat_history.json"
TEXT_FILE_EXTS = {
    ".txt", ".md", ".py", ".json", ".csv", ".yaml", ".yml",
    ".log", ".ini", ".toml", ".xml", ".html", ".js", ".ts", ".sql",
}
MAX_INLINE_CHARS = 6000

C = {
    "bg":       QColor(14, 14, 18),
    "panel":    QColor(20, 20, 24, 248),
    "border":   QColor(45, 45, 50),
    "accent":   "#7c3aed",
    "text":     "#e4e4e7",
    "muted":    "#71717a",
    "user_g0":  QColor(79, 70, 229),
    "user_g1":  QColor(124, 58, 237),
    "asst_bg":  QColor(39, 39, 42, 210),
    "asst_bdr": QColor(63, 63, 70),
    "send_g0":  QColor(220, 38, 38),
    "send_g1":  QColor(239, 68, 68),
    "green":    "#22c55e",
}

SCROLLBAR_STYLE = """
QScrollBar:vertical { width: 5px; background: transparent; border: none; }
QScrollBar::handle:vertical {
    background: rgba(255,255,255,0.12); border-radius: 2px; min-height: 20px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
"""

_SVG_COPY = '<svg viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>'
_SVG_REGEN = '<svg viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg>'
_SVG_CHAT = '<svg viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>'
_SVG_CLOCK = '<svg viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>'
_SVG_BOOK = '<svg viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20"/></svg>'
_SVG_GEAR = '<svg viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/></svg>'
_SVG_CLIP = '<svg viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.446 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>'
_SVG_STOP = '<svg viewBox="0 0 24 24" fill="{c}" stroke="none"><rect width="10" height="10" x="7" y="7" rx="1.5" ry="1.5"/></svg>'
_SVG_RESET = _SVG_REGEN
_SVG_SAVE = '<svg viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>'
_SVG_TRASH = '<svg viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/><line x1="10" x2="10" y1="11" y2="17"/><line x1="14" x2="14" y1="11" y2="17"/></svg>'
_SVG_BOLT = '<svg viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>'
_SVG_PLAY = '<svg viewBox="0 0 24 24" fill="{c}" stroke="none"><polygon points="6 3 20 12 6 21 6 3"/></svg>'
_SVG_FILE = '<svg viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"/><polyline points="14 2 14 8 20 8"/><line x1="16" x2="8" y1="13" y2="13"/><line x1="16" x2="8" y1="17" y2="17"/><line x1="10" x2="8" y1="9" y2="9"/></svg>'
_SVG_USER = '<svg viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>'
_SVG_BOT = '<svg viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z"/><path d="M5 3v4"/><path d="M7 5H3"/></svg>'
_SVG_SEND = '<svg viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 2 11 13"/><path d="m22 2-7 20-4-9-9-4Z"/></svg>'
_SVG_PLUS = '<svg viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" x2="12" y1="5" y2="19"/><line x1="5" x2="19" y1="12" y2="12"/></svg>'

_MD_CSS = """
body { color: #e4e4e7; font-family: "Arial", "Microsoft YaHei", sans-serif; font-size: 13px; line-height: 1.6; font-weight: 400; }
h1 { color: #f4f4f5; font-size: 20px; font-weight: 700; border-bottom: 1px solid #3f3f46; padding-bottom: 4px; margin-top: 16px; }
h2 { color: #f4f4f5; font-size: 17px; font-weight: 700; border-bottom: 1px solid #3f3f46; padding-bottom: 3px; margin-top: 14px; }
h3 { color: #f4f4f5; font-size: 15px; font-weight: 600; margin-top: 12px; }
h4,h5,h6 { color: #d4d4d8; font-size: 13px; font-weight: 600; margin-top: 10px; }
code { background: rgba(63,63,70,0.6); color: #c4b5fd; padding: 1px 4px; border-radius: 3px;
       font-family: Consolas, "Courier New", monospace; font-size: 12px; }
pre  { background: rgba(24,24,30,0.95); border: 1px solid #3f3f46; border-radius: 6px;
       padding: 10px 12px; margin: 8px 0; }
pre code { background: transparent; padding: 0; color: #d4d4d8; }
a { color: #818cf8; text-decoration: none; }
a:hover { text-decoration: underline; }
blockquote { border-left: 3px solid #7c3aed; margin: 8px 0 8px 0; padding: 4px 0 4px 12px; color: #a1a1aa; }
table { border-collapse: collapse; margin: 8px 0; }
th, td { border: 1px solid #3f3f46; padding: 5px 10px; }
th { background: rgba(63,63,70,0.35); color: #d4d4d8; font-weight: 700; }
hr { border: none; border-top: 1px solid #3f3f46; margin: 12px 0; }
ul, ol { padding-left: 22px; margin: 4px 0; }
li { margin: 2px 0; }
p { margin: 6px 0; }
"""


def _md_to_html(text: str) -> str:
    try:
        import markdown
        return markdown.markdown(
            text, extensions=["fenced_code", "tables", "nl2br", "sane_lists"]
        )
    except ImportError:
        pass
    html, in_code, in_ul = [], False, False
    for raw in text.split("\n"):
        if raw.strip().startswith("```"):
            if in_code:
                html.append("</code></pre>")
            else:
                html.append("<pre><code>")
            in_code = not in_code
            continue
        if in_code:
            html.append(raw.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
            continue
        line = raw
        line = re.sub(r"`([^`]+)`", r"<code>\1</code>", line)
        line = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", line)
        line = re.sub(r"\*(.+?)\*", r"<i>\1</i>", line)
        line = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', line)
        if re.match(r"^#{1,6}\s", line):
            lvl = len(line.split()[0])
            line = f"<h{lvl}>{line[lvl:].strip()}</h{lvl}>"
        elif re.match(r"^-{3,}$|^_{3,}$|^\*{3,}$", line.strip()):
            line = "<hr>"
        elif re.match(r"^\s*[-*+]\s", line):
            content = re.sub(r"^\s*[-*+]\s", "", line)
            if not in_ul:
                html.append("<ul>")
                in_ul = True
            line = f"<li>{content}</li>"
        else:
            if in_ul:
                html.append("</ul>")
                in_ul = False
            line = f"<p>{line}</p>" if line.strip() else ""
        html.append(line)
    if in_code:
        html.append("</code></pre>")
    if in_ul:
        html.append("</ul>")
    return "\n".join(html)


_icon_cache: dict[str, QIcon] = {}

def _svg_icon(key: str, svg_template: str, color: str = "#a1a1aa",
              size: int = 16) -> QIcon:
    cache_key = f"{key}_{color}_{size}"
    if cache_key not in _icon_cache:
        try:
            from PySide6.QtSvg import QSvgRenderer
        except ImportError:
            return QIcon()
        data = QByteArray(svg_template.format(c=color).encode("utf-8"))
        renderer = QSvgRenderer(data)
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        _icon_cache[cache_key] = QIcon(pixmap)
    return _icon_cache[cache_key]


# ── utilities ─────────────────────────────────────────────────────────────────
def _make_session_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")


def _load_history() -> list:
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _save_history(history: list):
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def _build_prompt_with_uploads(prompt: str, files: list) -> tuple:
    """
    files: list of {'name': str, 'type': str, 'raw': bytes}
    returns (full_prompt, display_prompt, display_attachments)
    """
    if not files:
        return prompt, prompt, []

    os.makedirs("temp/uploaded", exist_ok=True)
    attachment_chunks = ["\n\n[用户上传附件 — 文件已保存到本地磁盘，可用 file_read 工具读取]"]
    display_attachments = []
    img_count, file_names = 0, []

    for f in files:
        raw, name, mime = f["raw"], f["name"], f.get("type", "")
        size = len(raw)
        ext = os.path.splitext(name)[1].lower()
        safe = re.sub(r"[^A-Za-z0-9._\-]", "_", name)
        saved = os.path.join(
            "temp", "uploaded",
            f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{safe}",
        )
        try:
            with open(saved, "wb") as out:
                out.write(raw)
        except Exception:
            saved = "(保存失败)"

        if mime.startswith("image/"):
            b64 = base64.b64encode(raw).decode()
            attachment_chunks.append(
                f"\n- [图片附件] {name} ({size} bytes)\n  磁盘路径: {saved}"
                f"\n  data:{mime};base64,{b64}"
            )
            display_attachments.append({"type": "image", "name": name})
            img_count += 1
        elif ext in TEXT_FILE_EXTS:
            text = raw.decode("utf-8", errors="replace")
            attachment_chunks.append(
                f"\n--- 文本文件: {name} ({size} bytes) ---\n磁盘路径: {saved}\n{text[:MAX_INLINE_CHARS]}"
                + ("\n[内容已截断，请用 file_read 读取完整内容]" if len(text) > MAX_INLINE_CHARS else "")
            )
            display_attachments.append({"type": "file", "name": name})
            file_names.append(name)
        else:
            attachment_chunks.append(
                f"\n- 文件: {name} ({size} bytes)\n  磁盘路径: {saved}"
            )
            display_attachments.append({"type": "file", "name": name})
            file_names.append(name)

    parts = []
    if img_count:
        parts.append(f"{img_count} 张图片")
    if file_names:
        parts.append(f"{len(file_names)} 个文件（{'、'.join(file_names)}）")
    display_prompt = f"{prompt}\n\n📎 已附带：{'，'.join(parts)}" if parts else prompt
    return prompt + "\n".join(attachment_chunks), display_prompt, display_attachments


# ── small reusable widgets ────────────────────────────────────────────────────
class _Separator(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(1)
        self.setStyleSheet(f"background: {C['border'].name()};")


class _Badge(QLabel):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setStyleSheet(
            "QLabel { background: rgba(63,63,70,0.9); color: #a1a1aa;"
            " border: 1px solid #3f3f46; border-radius: 9px;"
            " padding: 1px 8px; font-size: 11px; }"
        )


class _StreamingBadge(QLabel):
    def __init__(self, parent=None):
        super().__init__("处理中…", parent)
        self.setStyleSheet(
            "QLabel { background: rgba(124,58,237,0.18); color: #c4b5fd;"
            " border: 1px solid rgba(124,58,237,0.35); border-radius: 9px;"
            " padding: 1px 8px; font-size: 11px; }"
        )
        self.hide()


class _MsgRow(QWidget):
    """A single message row – flat layout with avatar, inspired by ChatGPT / Qwen."""

    _ACTION_BTN = """
        QPushButton {
            background: transparent; border: none; border-radius: 4px; padding: 3px;
        }
        QPushButton:hover { background: rgba(63,63,70,0.6); }
    """

    def __init__(self, text: str, role: str, parent=None, on_resend=None):
        super().__init__(parent)
        self._text = text
        self._role = role
        self._on_resend = on_resend
        self._action_row = None
        self._finished = True

        is_user = role == "user"
        self.setStyleSheet(
            "background: rgba(255,255,255,0.03);" if is_user else "background: transparent;"
        )

        outer = QHBoxLayout(self)
        outer.setContentsMargins(20, 10, 20, 10)
        outer.setSpacing(12)
        outer.setAlignment(Qt.AlignTop)

        avatar = QLabel()
        avatar.setFixedSize(30, 30)
        avatar.setAlignment(Qt.AlignCenter)
        svg_data = _SVG_USER if is_user else _SVG_BOT
        avatar_color = "#c8c8d0" if is_user else "#9eb4d0"
        pm = QPixmap(30, 30)
        pm.fill(QColor(0, 0, 0, 0))
        from PySide6.QtSvg import QSvgRenderer
        renderer = QSvgRenderer(QByteArray(svg_data.replace("{c}", avatar_color).encode()))
        p = QPainter(pm)
        renderer.render(p)
        p.end()
        avatar.setPixmap(pm)
        avatar.setStyleSheet(
            "QLabel { background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.10);"
            " border-radius: 15px; }"
        )
        outer.addWidget(avatar, 0, Qt.AlignTop)

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(2)

        role_lbl = QLabel("你" if is_user else "助手")
        role_lbl.setStyleSheet(
            "color: #d4d4d8; font-size: 12px; font-weight: 700; background: transparent;"
        )
        right.addWidget(role_lbl)

        if is_user:
            label = QLabel(text)
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
            label.setStyleSheet(
                "QLabel { background: transparent; color: #e4e4e7;"
                " padding: 2px 0; font-size: 14px; line-height: 1.6; }"
            )
            right.addWidget(label)
            self._label = label
        else:
            browser = QTextBrowser()
            browser.setReadOnly(True)
            browser.setOpenExternalLinks(True)
            browser.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            browser.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            browser.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
            browser.document().setDefaultStyleSheet(_MD_CSS)
            browser.setStyleSheet(
                "QTextBrowser { background: transparent; color: #e4e4e7;"
                " border: none; padding: 0; font-size: 14px; }"
            )
            browser.setHtml(_md_to_html(text))
            self._label = browser
            right.addWidget(browser)
            self._adjust_browser_height()

            self._action_row = QWidget()
            self._action_row.setStyleSheet("background: transparent;")
            alayout = QHBoxLayout(self._action_row)
            alayout.setContentsMargins(0, 4, 0, 0)
            alayout.setSpacing(4)

            icon_sz = QSize(15, 15)

            copy_btn = QPushButton()
            copy_btn.setIcon(_svg_icon("copy", _SVG_COPY))
            copy_btn.setIconSize(icon_sz)
            copy_btn.setFixedSize(26, 24)
            copy_btn.setStyleSheet(self._ACTION_BTN)
            copy_btn.setToolTip("复制")
            copy_btn.setCursor(QCursor(Qt.PointingHandCursor))
            copy_btn.clicked.connect(self._copy_text)
            alayout.addWidget(copy_btn)

            if on_resend:
                regen_btn = QPushButton()
                regen_btn.setIcon(_svg_icon("regen", _SVG_REGEN))
                regen_btn.setIconSize(icon_sz)
                regen_btn.setFixedSize(26, 24)
                regen_btn.setStyleSheet(self._ACTION_BTN)
                regen_btn.setToolTip("重新生成")
                regen_btn.setCursor(QCursor(Qt.PointingHandCursor))
                regen_btn.clicked.connect(self._do_resend)
                alayout.addWidget(regen_btn)

            alayout.addStretch()
            self._action_row.hide()
            right.addWidget(self._action_row)

        outer.addLayout(right, 1)

    def _copy_text(self):
        QApplication.clipboard().setText(self._text)

    def _do_resend(self):
        if self._on_resend:
            self._on_resend()

    def enterEvent(self, event):
        if self._action_row and self._finished:
            self._action_row.show()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self._action_row:
            self._action_row.hide()
        super().leaveEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._role != "user" and hasattr(self, '_label'):
            self._adjust_browser_height()

    def set_finished(self, done: bool):
        self._finished = done
        if not done and self._action_row:
            self._action_row.hide()

    def _adjust_browser_height(self):
        doc = self._label.document()
        w = self._label.width()
        if w < 50:
            w = 460
        doc.setTextWidth(w - 6)
        self._label.setFixedHeight(int(doc.size().height() + 8))

    def set_text(self, text: str):
        self._text = text
        if self._role == "user":
            self._label.setText(text)
            self._label.adjustSize()
        else:
            self._label.setHtml(_md_to_html(text))
            self._adjust_browser_height()


class _TabButton(QPushButton):
    _STYLE = """
    QPushButton {{
        background: transparent; color: {muted};
        border: none; border-radius: 8px;
        padding: 0 14px; font-size: 12px; font-weight: 700;
    }}
    QPushButton:hover {{
        background: rgba(63,63,70,0.6); color: {text};
    }}
    QPushButton:checked {{
        background: #7c3aed; color: white;
    }}
    """.format(muted=C["muted"], text=C["text"])

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setCheckable(True)
        self.setFixedHeight(30)
        self.setStyleSheet(self._STYLE)


def _action_btn(label: str, color: str, icon: QIcon | None = None) -> QPushButton:
    btn = QPushButton(label)
    if icon and not icon.isNull():
        btn.setIcon(icon)
        btn.setIconSize(QSize(16, 16))
    btn.setFixedHeight(36)
    btn.setStyleSheet(f"""
        QPushButton {{
            background: rgba(35,35,40,0.8); color: {C['text']};
            border: 1px solid {C['border'].name()};
            border-left: 3px solid {color};
            border-radius: 8px; padding: 0 14px;
            font-size: 13px; font-weight: 700; text-align: left;
        }}
        QPushButton:hover {{ background: rgba(55,55,62,0.9); }}
        QPushButton:checked {{ color: {color}; background: rgba(35,35,40,0.95); }}
    """)
    return btn


# ── Main panel ────────────────────────────────────────────────────────────────
class ChatPanel(QWidget):
    """Frameless always-on-top chat window."""

    def __init__(self, agent):
        super().__init__()
        self.agent = agent

        # session state
        self._messages: list[dict] = []
        self._session = {"id": _make_session_id(), "title": "新对话", "messages": []}
        self._history: list[dict] = _load_history()
        self._pending_files: list[dict] = []  # {'name','type','raw'}
        self._settings_health_checked = False

        # streaming state
        self._display_queue: Optional[_queue.Queue] = None
        self._streaming_row: Optional[_MsgRow] = None
        self._streaming_text = ""
        self._user_scrolled_up = False
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_queue)

        # autonomous mode
        self.autonomous_enabled = False
        self.last_reply_time = time.time()

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(530, 700)

        # drag state (title bar)
        self._drag_pos: Optional[QPoint] = None

        self._build_ui()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0.5, 0.5, self.width() - 1.0, self.height() - 1.0,
                            20.0, 20.0)
        grad = QLinearGradient(0, 0, 0, self.height())
        grad.setColorAt(0.0, QColor(20, 20, 28, 228))
        grad.setColorAt(1.0, QColor(10, 10, 14, 242))
        p.fillPath(path, grad)
        p.setPen(QPen(QColor(99, 102, 241, 80), 1.0))
        p.drawPath(path)

    def resizeEvent(self, event):
        path = QPainterPath()
        path.addRoundedRect(0, 0, float(self.width()), float(self.height()),
                            20.0, 20.0)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))
        super().resizeEvent(event)

    # ── UI construction ───────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_titlebar())
        root.addWidget(_Separator())
        root.addWidget(self._build_tabbar())
        root.addWidget(_Separator())

        self._stack = QStackedWidget()
        self._stack.setStyleSheet("background: transparent;")
        self._stack.addWidget(self._build_chat_page())    # 0
        self._stack.addWidget(self._build_history_page()) # 1
        self._stack.addWidget(self._build_sop_page())     # 2
        self._stack.addWidget(self._build_settings_page())# 3
        root.addWidget(self._stack)

        # Now that _stack exists, activate the first tab
        self._switch_tab(0)

    # ── title bar ─────────────────────────────────────────────────────────────
    def _build_titlebar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(48)
        bar.setStyleSheet("background: transparent;")
        bar.setCursor(QCursor(Qt.SizeAllCursor))

        ly = QHBoxLayout(bar)
        ly.setContentsMargins(16, 0, 10, 0)
        ly.setSpacing(8)

        # Status dot
        dot = QLabel("●")
        dot.setStyleSheet(f"color: {C['green']}; font-size: 9px;")
        dot.setFixedWidth(12)
        ly.addWidget(dot)

        # Title
        t = QLabel("GenericAgent")
        t.setStyleSheet("color: #f4f4f5; font-weight: 700; font-size: 14px;")
        ly.addWidget(t)

        # Model badge
        self._model_badge = _Badge(self._model_name())
        ly.addWidget(self._model_badge)

        self._streaming_badge = _StreamingBadge()
        ly.addWidget(self._streaming_badge)

        ly.addStretch()

        # Close button
        close = QPushButton("×")
        close.setFixedSize(26, 26)
        close.setStyleSheet("""
            QPushButton { background: rgba(63,63,70,0.6); color: #a1a1aa;
                border: none; border-radius: 13px; font-size: 15px; font-weight: bold; }
            QPushButton:hover { background: rgba(220,38,38,0.85); color: white; }
        """)
        close.clicked.connect(self.hide)
        ly.addWidget(close)

        # Drag
        bar.mousePressEvent   = self._tb_press
        bar.mouseMoveEvent    = self._tb_move
        bar.mouseReleaseEvent = self._tb_release
        return bar

    def _tb_press(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.pos()

    def _tb_move(self, e):
        if e.buttons() == Qt.LeftButton and self._drag_pos is not None:
            self.move(e.globalPosition().toPoint() - self._drag_pos)

    def _tb_release(self, _e):
        self._drag_pos = None

    # ── tab bar ───────────────────────────────────────────────────────────────
    def _build_tabbar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(40)
        bar.setStyleSheet("background: rgba(10,10,14,0.6);")

        ly = QHBoxLayout(bar)
        ly.setContentsMargins(12, 5, 12, 5)
        ly.setSpacing(4)

        self._tabs: list[_TabButton] = []
        tab_defs = [
            (_SVG_CHAT,  "对话"),
            (_SVG_CLOCK, "历史"),
            (_SVG_BOOK,  "SOP"),
            (_SVG_GEAR,  "设置"),
        ]
        for i, (svg, text) in enumerate(tab_defs):
            btn = _TabButton(text)
            btn.setIcon(_svg_icon(text, svg, "#b0b0b8"))
            btn.setIconSize(QSize(14, 14))
            btn.clicked.connect(lambda _checked, idx=i: self._switch_tab(idx))
            ly.addWidget(btn)
            self._tabs.append(btn)

        ly.addStretch()

        new_btn = QPushButton("新对话")
        new_btn.setIcon(_svg_icon("plus", _SVG_PLUS, "#a78bfa"))
        new_btn.setIconSize(QSize(12, 12))
        new_btn.setFixedHeight(27)
        new_btn.setStyleSheet(f"""
            QPushButton {{ background: rgba(124,58,237,0.18); color: #a78bfa;
                border: 1px solid rgba(124,58,237,0.3); border-radius: 7px;
                padding: 0 10px; font-size: 12px; font-weight: 700; }}
            QPushButton:hover {{ background: rgba(124,58,237,0.35); color: white; }}
        """)
        new_btn.clicked.connect(self._new_session)
        ly.addWidget(new_btn)

        # NOTE: _switch_tab(0) is called in _build_ui() after _stack is created
        return bar

    def _switch_tab(self, idx: int):
        self._stack.setCurrentIndex(idx)
        for i, btn in enumerate(self._tabs):
            btn.setChecked(i == idx)
        if idx == 1:
            self._refresh_history()
        if idx == 2:
            self._refresh_sop()
        if idx == 3:
            self._refresh_model_rows_style()
            if not self._settings_health_checked:
                self._start_health_checks()
                self._settings_health_checked = True

    # ── chat page ─────────────────────────────────────────────────────────────
    def _build_chat_page(self) -> QWidget:
        page = QWidget()
        page.setStyleSheet("background: transparent;")
        ly = QVBoxLayout(page)
        ly.setContentsMargins(0, 0, 0, 0)
        ly.setSpacing(0)

        # ── message scroll area ──
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(f"QScrollArea {{ background: transparent; border: none; }} {SCROLLBAR_STYLE}")

        self._msg_container = QWidget()
        self._msg_container.setStyleSheet("background: transparent;")
        self._msg_layout = QVBoxLayout(self._msg_container)
        self._msg_layout.setContentsMargins(0, 12, 0, 12)
        self._msg_layout.setSpacing(4)
        self._msg_layout.addStretch()

        self._scroll.setWidget(self._msg_container)
        self._scroll.verticalScrollBar().valueChanged.connect(self._on_scroll)
        ly.addWidget(self._scroll, 1)

        ly.addWidget(_Separator())

        # ── input area ──
        ly.addWidget(self._build_input_area())
        return page

    def _build_input_area(self) -> QWidget:
        wrap = QWidget()
        wrap.setStyleSheet("background: transparent;")
        ly = QVBoxLayout(wrap)
        ly.setContentsMargins(20, 6, 20, 14)
        ly.setSpacing(0)

        self._chips_row = QWidget()
        self._chips_row.setStyleSheet("background: transparent;")
        self._chips_ly = QHBoxLayout(self._chips_row)
        self._chips_ly.setContentsMargins(0, 0, 0, 6)
        self._chips_ly.setSpacing(6)
        self._chips_row.hide()
        ly.addWidget(self._chips_row)

        card = QWidget()
        card.setStyleSheet(f"""
            QWidget#inputCard {{
                background: rgba(32,32,38,0.85);
                border: 1px solid {C['border'].name()};
                border-radius: 16px;
            }}
            QWidget#inputCard:focus-within {{
                border-color: rgba(124,58,237,0.55);
            }}
        """)
        card.setObjectName("inputCard")
        card_ly = QVBoxLayout(card)
        card_ly.setContentsMargins(14, 10, 10, 10)
        card_ly.setSpacing(6)

        self._input = QTextEdit()
        self._input.setFixedHeight(64)
        self._input.setPlaceholderText("给助手发送消息...")
        self._input.setStyleSheet(f"""
            QTextEdit {{
                background: transparent; color: {C['text']};
                border: none; padding: 0; font-size: 14px;
                selection-background-color: rgba(124,58,237,0.4);
            }}
        """)
        self._input.installEventFilter(self)
        self._input.textChanged.connect(self._on_text_changed)
        card_ly.addWidget(self._input)

        bottom = QHBoxLayout()
        bottom.setSpacing(6)

        attach = QPushButton()
        attach.setIcon(_svg_icon("clip", _SVG_CLIP, "#a1a1aa"))
        attach.setIconSize(QSize(17, 17))
        attach.setFixedSize(30, 30)
        attach.setToolTip("上传附件")
        attach.setCursor(QCursor(Qt.PointingHandCursor))
        attach.setStyleSheet("""
            QPushButton { background: transparent; border: none; border-radius: 15px; }
            QPushButton:hover { background: rgba(63,63,70,0.6); }
        """)
        attach.clicked.connect(self._attach_files)
        bottom.addWidget(attach)

        self._char_lbl = QLabel("0 / 2000")
        self._char_lbl.setStyleSheet(f"color: {C['muted']}; font-size: 11px;")
        bottom.addWidget(self._char_lbl)

        self._token_lbl = QLabel("")
        self._token_lbl.setStyleSheet(f"color: {C['muted']}; font-size: 11px; margin-left: 10px;")
        bottom.addWidget(self._token_lbl)

        bottom.addStretch()

        self._is_streaming = False
        self._send_btn = QPushButton()
        self._send_btn.setFixedSize(34, 34)
        self._send_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self._send_btn.clicked.connect(self._on_send_btn_click)
        self._set_send_mode()
        bottom.addWidget(self._send_btn)

        card_ly.addLayout(bottom)
        ly.addWidget(card)
        return wrap

    # ── history page ──────────────────────────────────────────────────────────
    def _build_history_page(self) -> QWidget:
        page = QWidget()
        page.setStyleSheet("background: transparent;")
        ly = QVBoxLayout(page)
        ly.setContentsMargins(12, 12, 12, 12)
        ly.setSpacing(8)

        header = QHBoxLayout()
        lbl = QLabel("历史记录")
        lbl.setStyleSheet("color: #f4f4f5; font-weight: 600; font-size: 14px;")
        header.addWidget(lbl)
        header.addStretch()

        restore_btn = QPushButton("恢复会话")
        restore_btn.setStyleSheet(self._small_btn_style(C["accent"]))
        restore_btn.clicked.connect(self._restore_selected)
        header.addWidget(restore_btn)

        del_btn = QPushButton("删除")
        del_btn.setStyleSheet(self._small_btn_style("#dc2626"))
        del_btn.clicked.connect(self._delete_selected)
        header.addWidget(del_btn)
        ly.addLayout(header)

        self._hist_list = QListWidget()
        self._hist_list.setStyleSheet(f"""
            QListWidget {{ background: transparent; border: none; outline: none; }}
            QListWidget::item {{
                background: rgba(35,35,42,0.6); color: {C['text']};
                border: 1px solid {C['border'].name()}; border-radius: 8px;
                padding: 8px 12px; margin: 2px 0;
            }}
            QListWidget::item:hover {{ background: rgba(55,55,65,0.8);
                border-color: rgba(124,58,237,0.4); }}
            QListWidget::item:selected {{ background: rgba(124,58,237,0.25);
                border-color: rgba(124,58,237,0.6); }}
            {SCROLLBAR_STYLE}
        """)
        self._hist_list.itemDoubleClicked.connect(self._restore_selected)
        ly.addWidget(self._hist_list)
        return page

    # ── SOP page ──────────────────────────────────────────────────────────────
    def _build_sop_page(self) -> QWidget:
        page = QWidget()
        page.setStyleSheet("background: transparent;")
        ly = QVBoxLayout(page)
        ly.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Horizontal)

        self._sop_list = QListWidget()
        self._sop_list.setMaximumWidth(175)
        self._sop_list.setStyleSheet(f"""
            QListWidget {{ background: rgba(10,10,14,0.7); border: none;
                border-right: 1px solid {C['border'].name()}; outline: none; }}
            QListWidget::item {{ color: {C['muted']}; padding: 7px 10px;
                border-radius: 4px; margin: 1px 4px; }}
            QListWidget::item:hover {{ background: rgba(55,55,65,0.7); color: {C['text']}; }}
            QListWidget::item:selected {{ background: rgba(124,58,237,0.28); color: white; }}
            {SCROLLBAR_STYLE}
        """)
        self._sop_list.currentItemChanged.connect(self._load_sop)
        splitter.addWidget(self._sop_list)

        self._sop_viewer = QTextBrowser()
        self._sop_viewer.setOpenExternalLinks(True)
        self._sop_viewer.document().setDefaultStyleSheet(_MD_CSS)
        self._sop_viewer.setStyleSheet(f"""
            QTextBrowser {{ background: transparent; color: {C['text']};
                border: none; padding: 10px 14px;
                font-family: "Arial", "Microsoft YaHei", sans-serif;
                font-size: 13px; }}
            {SCROLLBAR_STYLE}
        """)
        splitter.addWidget(self._sop_viewer)
        splitter.setSizes([165, 340])
        ly.addWidget(splitter)
        return page

    # ── settings page ─────────────────────────────────────────────────────────
    def _build_settings_page(self) -> QWidget:
        page = QWidget()
        page.setStyleSheet("background: transparent;")
        ly = QVBoxLayout(page)
        ly.setContentsMargins(16, 16, 16, 16)
        ly.setSpacing(8)

        lbl = QLabel("控制面板")
        lbl.setStyleSheet("color: #f4f4f5; font-weight: 600; font-size: 14px;")
        ly.addWidget(lbl)

        self._model_info = QLabel(f"当前模型：{self._model_name()} (#{self.agent.llm_no})")
        self._model_info.setStyleSheet(f"color: {C['muted']}; font-size: 12px;")
        ly.addWidget(self._model_info)
        ly.addSpacing(4)

        model_hdr = QLabel("模型列表")
        model_hdr.setStyleSheet("color: #d4d4d8; font-weight: 600; font-size: 13px;")
        ly.addWidget(model_hdr)

        self._model_rows_container = QWidget()
        self._model_rows_container.setStyleSheet("background: transparent;")
        self._model_rows_layout = QVBoxLayout(self._model_rows_container)
        self._model_rows_layout.setContentsMargins(0, 0, 0, 0)
        self._model_rows_layout.setSpacing(3)
        ly.addWidget(self._model_rows_container)

        self._model_row_widgets: list[dict] = []
        self._health_results: dict[int, bool | None] = {}
        self._build_model_rows()

        ly.addSpacing(6)

        for (lbl_text, color, handler, svg) in [
            ("重置提示词", "#059669", self._do_reset_prompt,  _SVG_RESET),
            ("保存当前会话","#0ea5e9", self._do_save,         _SVG_SAVE),
            ("清空对话",   "#78716c", self._do_clear,         _SVG_TRASH),
        ]:
            b = _action_btn(lbl_text, color, _svg_icon(lbl_text, svg))
            b.clicked.connect(handler)
            ly.addWidget(b)

        ly.addSpacing(10)
        sep = QLabel("自主行动")
        sep.setStyleSheet("color: #f4f4f5; font-weight: 600; font-size: 13px;")
        ly.addWidget(sep)

        self._auto_btn = _action_btn("开启自主行动 (idle > 30 min 自动触发)", "#f59e0b",
                                      _svg_icon("bolt", _SVG_BOLT))
        self._auto_btn.setCheckable(True)
        self._auto_btn.clicked.connect(self._do_toggle_auto)
        ly.addWidget(self._auto_btn)

        trigger_btn = _action_btn("立即触发一次", "#f59e0b",
                                  _svg_icon("play", _SVG_PLAY))
        trigger_btn.clicked.connect(self._do_trigger_auto)
        ly.addWidget(trigger_btn)

        ly.addStretch()
        return page

    # ── model list ────────────────────────────────────────────────────────────
    _MODEL_ROW_STYLE = (
        "QPushButton { background: rgba(39,39,42,0.7); color: #e4e4e7;"
        " border: 1px solid #3f3f46; border-radius: 8px;"
        " padding: 6px 10px; font-size: 12px; font-weight: 700; text-align: left; }"
        " QPushButton:hover { background: rgba(63,63,70,0.8); }"
    )
    _MODEL_ROW_ACTIVE = (
        "QPushButton { background: rgba(124,58,237,0.25); color: #c4b5fd;"
        " border: 1px solid rgba(124,58,237,0.5); border-radius: 8px;"
        " padding: 6px 10px; font-size: 12px; font-weight: 700; text-align: left; }"
        " QPushButton:hover { background: rgba(124,58,237,0.35); }"
    )

    def _build_model_rows(self):
        while self._model_rows_layout.count():
            w = self._model_rows_layout.takeAt(0).widget()
            if w:
                w.deleteLater()
        self._model_row_widgets.clear()

        for idx, tc in enumerate(self.agent.llmclients):
            b = tc.backend
            name = f"{type(b).__name__}/{b.default_model}"
            is_current = idx == self.agent.llm_no

            row = QWidget()
            row.setStyleSheet("background: transparent;")
            rlay = QHBoxLayout(row)
            rlay.setContentsMargins(0, 0, 0, 0)
            rlay.setSpacing(6)

            dot = QLabel("●")
            dot.setFixedWidth(14)
            dot.setAlignment(Qt.AlignCenter)
            dot.setStyleSheet("color: #71717a; font-size: 11px;")
            rlay.addWidget(dot)

            btn = QPushButton(f"  #{idx}  {name}")
            btn.setCursor(QCursor(Qt.PointingHandCursor))
            btn.setStyleSheet(self._MODEL_ROW_ACTIVE if is_current else self._MODEL_ROW_STYLE)
            btn.clicked.connect(lambda checked, i=idx: self._do_switch_to(i))
            rlay.addWidget(btn, 1)

            self._model_rows_layout.addWidget(row)
            self._model_row_widgets.append({"dot": dot, "btn": btn, "idx": idx})

    def _refresh_model_rows_style(self):
        for entry in self._model_row_widgets:
            is_current = entry["idx"] == self.agent.llm_no
            entry["btn"].setStyleSheet(
                self._MODEL_ROW_ACTIVE if is_current else self._MODEL_ROW_STYLE
            )
            status = self._health_results.get(entry["idx"])
            if status is True:
                entry["dot"].setStyleSheet("color: #22c55e; font-size: 11px;")
            elif status is False:
                entry["dot"].setStyleSheet("color: #ef4444; font-size: 11px;")
            else:
                entry["dot"].setStyleSheet("color: #71717a; font-size: 11px;")

    def _do_switch_to(self, idx: int):
        if idx == self.agent.llm_no:
            return
        self.agent.next_llm(n=idx)
        name = self._model_name()
        self._model_badge.setText(name)
        self._model_info.setText(f"当前模型：{name} (#{self.agent.llm_no})")
        self._add_system_notice(f"已切换至 {name}，对话上下文已保留")
        self._refresh_model_rows_style()

    def _start_health_checks(self):
        self._health_results.clear()
        self._health_pending = 0
        for entry in self._model_row_widgets:
            entry["dot"].setStyleSheet("color: #71717a; font-size: 11px;")
            entry["dot"].setText("◌")
        for idx, tc in enumerate(self.agent.llmclients):
            self._health_pending += 1
            t = threading.Thread(target=self._check_backend, args=(idx, tc.backend), daemon=True)
            t.start()
        if not hasattr(self, '_health_poll_timer'):
            self._health_poll_timer = QTimer(self)
            self._health_poll_timer.timeout.connect(self._poll_health_results)
        self._health_poll_timer.start(500)

    def _poll_health_results(self):
        self._refresh_model_rows_style()
        if len(self._health_results) >= self._health_pending:
            self._health_poll_timer.stop()

    def _check_backend(self, idx: int, backend):
        ok = False
        try:
            reply = backend.ask("你好", stream=False)
            text = str(reply).strip() if reply else ""
            ok = len(text) > 0 and not text.startswith("Error") and not text.startswith("[")
            print(f"[HealthCheck] Backend #{idx} {type(backend).__name__}/{backend.default_model}: {'OK' if ok else 'FAIL'} -> {text[:60]}")
        except Exception as e:
            print(f"[HealthCheck] Backend #{idx} {type(backend).__name__}/{backend.default_model}: ERROR -> {e}")
            ok = False
        if hasattr(backend, 'raw_msgs') and backend.raw_msgs:
            backend.raw_msgs = [m for m in backend.raw_msgs if m.get("prompt") != "你好"]
        self._health_results[idx] = ok

    # ── event filter (Enter key in text edit) ─────────────────────────────────
    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        if obj is self._input and event.type() == QEvent.KeyPress:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                if not (event.modifiers() & Qt.ShiftModifier):
                    self._handle_send()
                    return True
        return super().eventFilter(obj, event)

    def _on_text_changed(self):
        n = len(self._input.toPlainText())
        self._char_lbl.setText(f"{n} / 2000")

    # ── file attachment ────────────────────────────────────────────────────────
    def _attach_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择附件", "",
            "All Files (*);;"
            "Images (*.png *.jpg *.jpeg *.gif *.webp *.bmp);;"
            "Text (*.txt *.md *.py *.json *.csv *.yaml *.yml *.log *.js *.ts *.sql)",
        )
        for path in paths:
            name = os.path.basename(path)
            if any(f["name"] == name for f in self._pending_files):
                continue
            ext = os.path.splitext(path)[1].lower()
            img_exts = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
            mime = (f"image/{ext[1:]}" if ext in img_exts else
                    "text/plain" if ext in TEXT_FILE_EXTS else
                    "application/octet-stream")
            try:
                with open(path, "rb") as fh:
                    raw = fh.read()
                self._pending_files.append({"name": name, "type": mime, "raw": raw})
            except Exception as e:
                print(f"[Attach] Failed to read {path}: {e}")
        self._refresh_chips()

    def _refresh_chips(self):
        while self._chips_ly.count():
            item = self._chips_ly.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not self._pending_files:
            self._chips_row.hide()
            return
        for f in self._pending_files:
            chip = QLabel(f['name'])
            chip.setStyleSheet(f"""
                QLabel {{ background: rgba(55,55,65,0.7); color: {C['text']};
                    border: 1px solid {C['border'].name()}; border-radius: 6px;
                    padding: 3px 8px; font-size: 11px; }}
            """)
            self._chips_ly.addWidget(chip)
        self._chips_ly.addStretch()
        self._chips_row.show()

    # ── send / streaming ───────────────────────────────────────────────────────
    _SEND_BTN_STYLE = """
        QPushButton { background: #e4e4e7; border: none; border-radius: 17px; }
        QPushButton:hover { background: #f4f4f5; }
        QPushButton:pressed { background: #d4d4d8; }
    """
    _STOP_BTN_STYLE = """
        QPushButton { background: rgba(239,68,68,0.85); border: none; border-radius: 17px; }
        QPushButton:hover { background: rgba(248,113,113,0.9); }
        QPushButton:pressed { background: rgba(220,38,38,0.9); }
    """

    def _set_send_mode(self):
        self._is_streaming = False
        self._send_btn.setText("")
        self._send_btn.setIcon(_svg_icon("send_arrow", _SVG_SEND, "#18181b"))
        self._send_btn.setIconSize(QSize(18, 18))
        self._send_btn.setStyleSheet(self._SEND_BTN_STYLE)

    def _set_stop_mode(self):
        self._is_streaming = True
        self._send_btn.setText("")
        self._send_btn.setIcon(_svg_icon("stop_circle", _SVG_STOP, "#ffffff"))
        self._send_btn.setIconSize(QSize(16, 16))
        self._send_btn.setStyleSheet(self._STOP_BTN_STYLE)

    def _on_send_btn_click(self):
        if self._is_streaming:
            self._do_stop()
        else:
            self._handle_send()

    def _handle_send(self):
        text = self._input.toPlainText().strip()
        files = self._pending_files.copy()
        if not text and not files:
            return

        prompt = text or "请分析我上传的附件。"
        full_prompt, display_prompt, _ = _build_prompt_with_uploads(prompt, files)

        # Clear input state
        self._input.clear()
        self._pending_files.clear()
        self._refresh_chips()

        # Update session title
        if self._session["title"] == "新对话" and prompt:
            self._session["title"] = prompt[:20] + ("..." if len(prompt) > 20 else "")

        self._add_msg_row("user", display_prompt)
        self._messages.append({"role": "user", "content": display_prompt})
        self._update_token_usage()

        # Start streaming — reset scroll lock so new output auto-scrolls
        self._user_scrolled_up = False
        self._streaming_text = ""
        self._streaming_row = self._add_msg_row("assistant", "▌")
        self._streaming_row.set_finished(False)
        self._set_stop_mode()
        self._streaming_badge.show()

        self._display_queue = self.agent.put_task(full_prompt, source="user")
        self._poll_timer.start(40)

    def _poll_queue(self):
        if not self._display_queue:
            return
        try:
            while True:
                item = self._display_queue.get_nowait()
                if "next" in item:
                    self._streaming_text = item["next"]
                    if self._streaming_row:
                        self._streaming_row.set_text(self._streaming_text + " ▌")
                    self._update_token_usage()
                    self._scroll_bottom()
                if "done" in item:
                    final = item["done"]
                    if self._streaming_row:
                        self._streaming_row.set_text(final)
                        self._streaming_row.set_finished(True)
                    self._messages.append({"role": "assistant", "content": final})
                    self._streaming_row = None
                    self._poll_timer.stop()
                    self._set_send_mode()
                    self._streaming_badge.hide()
                    self.last_reply_time = time.time()
                    self._update_token_usage()
                    self._scroll_bottom()
                    self._auto_save()
                    break
        except _queue.Empty:
            pass

    def _add_msg_row(self, role: str, text: str) -> _MsgRow:
        row = _MsgRow(text, role, on_resend=self._regenerate_response if role != "user" else None)
        self._msg_layout.insertWidget(self._msg_layout.count() - 1, row)
        self._scroll_bottom()
        return row

    def _regenerate_response(self):
        """Resend the last user message to regenerate the assistant response."""
        if self._is_streaming:
            return
        for msg in reversed(self._messages):
            if msg["role"] == "user":
                self._input.setPlainText(msg["content"])
                self._handle_send()
                break

    def _on_scroll(self, value):
        sb = self._scroll.verticalScrollBar()
        self._user_scrolled_up = value < sb.maximum() - 30

    def _scroll_bottom(self):
        if self._user_scrolled_up:
            return
        QTimer.singleShot(60, lambda: (
            self._scroll.verticalScrollBar().setValue(
                self._scroll.verticalScrollBar().maximum()
            )
        ))

    # ── inject (autonomous mode) ───────────────────────────────────────────────
    def inject_message(self, text: str):
        """Programmatically send a message (called by idle monitor)."""
        self._input.setPlainText(text)
        self._handle_send()

    # ── history ────────────────────────────────────────────────────────────────
    def _refresh_history(self):
        self._history = _load_history()
        self._hist_list.clear()
        for s in reversed(self._history[-20:]):
            n = len(s.get("messages", []))
            item = QListWidgetItem(f"  {s.get('title','未命名')}   ({n} 条)")
            item.setData(Qt.UserRole, s)
            self._hist_list.addItem(item)

    def _restore_selected(self, item=None):
        item = item or self._hist_list.currentItem()
        if not item:
            return
        s = item.data(Qt.UserRole)
        if s:
            self._session = s.copy()
            self._messages = s.get("messages", []).copy()
            self._rebuild_messages()
            self._switch_tab(0)
            self._update_token_usage()

    def _delete_selected(self):
        item = self._hist_list.currentItem()
        if not item:
            return
        s = item.data(Qt.UserRole)
        if s:
            self._history = [h for h in self._history if h.get("id") != s.get("id")]
            _save_history(self._history)
            self._refresh_history()

    def _rebuild_messages(self):
        while self._msg_layout.count() > 1:
            it = self._msg_layout.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for m in self._messages:
            self._add_msg_row(m["role"], m["content"])
        self._update_token_usage()

    def _update_token_usage(self):
        in_chars = sum(len(m.get("content", "")) for m in self._messages if m.get("role") == "user")
        out_chars = sum(len(m.get("content", "")) for m in self._messages if m.get("role") == "assistant")
        if getattr(self, "_is_streaming", False) and getattr(self, "_streaming_text", ""):
            out_chars += len(self._streaming_text)
        
        in_tokens = int(in_chars / 2.5)
        out_tokens = int(out_chars / 2.5)
        
        if in_tokens == 0 and out_tokens == 0:
            self._token_lbl.setText("")
        else:
            self._token_lbl.setText(f"|   会话上下文消耗: 入 {in_tokens}  出 {out_tokens} tokens")

    # ── SOP ────────────────────────────────────────────────────────────────────
    def _refresh_sop(self):
        self._sop_list.clear()
        file_icon = _svg_icon("sop_file_item", _SVG_FILE, C["muted"])
        for path in sorted(glob.glob("memory/*.md")):
            name = os.path.basename(path)
            size = os.path.getsize(path)
            it = QListWidgetItem(name)
            it.setIcon(file_icon)
            it.setData(Qt.UserRole, path)
            it.setToolTip(f"{size:,} 字节")
            self._sop_list.addItem(it)

    def _load_sop(self, item):
        if not item:
            return
        path = item.data(Qt.UserRole)
        try:
            with open(path, "r", encoding="utf-8") as f:
                self._sop_viewer.setHtml(_md_to_html(f.read()))
        except Exception as e:
            self._sop_viewer.setPlainText(f"读取失败: {e}")

    # ── settings actions ───────────────────────────────────────────────────────
    def _model_name(self) -> str:
        try:
            return self.agent.get_llm_name()
        except Exception:
            return "未知"

    def _add_system_notice(self, text: str):
        """Insert a small centered notice label (not tracked as a message)."""
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet(
            "QLabel { background: transparent; color: #71717a;"
            " border: none; padding: 6px 20px; font-size: 12px; }"
        )
        self._msg_layout.insertWidget(self._msg_layout.count() - 1, lbl)
        self._scroll_bottom()

    def _do_switch_model(self):
        nxt = (self.agent.llm_no + 1) % len(self.agent.llmclients)
        self._do_switch_to(nxt)

    def _do_stop(self):
        self.agent.abort()
        self._poll_timer.stop()
        self._set_send_mode()
        self._streaming_badge.hide()
        if self._streaming_row:
            self._streaming_row.set_text(self._streaming_text or "（已停止）")
            self._streaming_row.set_finished(True)
            self._streaming_row = None
        self._update_token_usage()

    def _do_reset_prompt(self):
        try:
            self.agent.llmclient.last_tools = ""
        except Exception:
            pass

    def _auto_save(self):
        if not self._messages:
            return
        if self._session.get("title") == "新对话":
            first_user = next(
                (m["content"] for m in self._messages if m["role"] == "user"), ""
            )
            if first_user:
                self._session["title"] = first_user[:30].replace("\n", " ")
        self._do_save()

    def _do_save(self):
        if not self._messages:
            return
        self._session["messages"] = self._messages.copy()
        self._session["updatedAt"] = datetime.now().isoformat()
        self._history = _load_history()
        for i, s in enumerate(self._history):
            if s.get("id") == self._session["id"]:
                self._history[i] = self._session.copy()
                break
        else:
            self._history.append(self._session.copy())
        _save_history(self._history)

    def _do_clear(self):
        self._messages.clear()
        self._session = {"id": _make_session_id(), "title": "新对话", "messages": []}
        self._rebuild_messages()
        self._switch_tab(0)
        self._update_token_usage()

    def _new_session(self):
        if self._messages:
            self._do_save()
        self._do_clear()

    def _do_toggle_auto(self):
        self.autonomous_enabled = not self.autonomous_enabled
        self._auto_btn.setChecked(self.autonomous_enabled)
        lbl = "暂停自主行动" if self.autonomous_enabled else "开启自主行动 (idle > 30 min 自动触发)"
        self._auto_btn.setText(lbl)

    def _do_trigger_auto(self):
        self.inject_message(
            "[AUTO]🤖 用户触发了自主行动，请阅读自动化sop，选择并执行一项有价值的任务。"
        )

    # ── helpers ────────────────────────────────────────────────────────────────
    @staticmethod
    def _small_btn_style(color: str) -> str:
        return (
            f"QPushButton {{ background: {color}; color: white; border: none;"
            f" border-radius: 7px; padding: 4px 12px; font-size: 12px; font-weight: 600; }}"
            f"QPushButton:hover {{ opacity: 0.85; }}"
        )


# ══════════════════════════════════════════════════════════════════════
# Entry Point
# ══════════════════════════════════════════════════════════════════════

def main():
    # High-DPI support
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("GenericAgent")

    # Font
    font = QFont()
    # Keep English glyphs in Arial; Chinese falls back to Microsoft YaHei.
    try:
        font.setFamilies(["Arial", "Microsoft YaHei"])
    except Exception:
        font.setFamily("Microsoft YaHei")
    font.setPointSize(10)
    app.setFont(font)

    # ── Agent initialisation ──────────────────────────────
    agent = GeneraticAgent()
    if agent.llmclient is None:
        QMessageBox.critical(
            None,
            "未配置 LLM",
            "未在 mykey.py 中发现任何可用的 LLM 接口配置，\n程序将在无 LLM 模式下运行。",
        )
    else:
        threading.Thread(target=agent.run, daemon=True).start()

    # ── Windows ───────────────────────────────────────────
    panel = ChatPanel(agent)
    button = FloatingButton(panel)
    button.show()

    # Position panel next to button and show it on first launch
    button._position_panel()
    panel.show()

    scr = QApplication.primaryScreen().availableGeometry()
    print(f"[GenericAgent] 启动成功")
    print(f"  屏幕分辨率: {scr.width()}x{scr.height()}")
    print(f"  悬浮按钮: ({button.x()}, {button.y()})")
    print(f"  聊天面板: ({panel.x()}, {panel.y()})")
    print(f"  关闭面板后可点击右下角发光按钮重新打开")

    # ── Idle monitor (autonomous mode) ────────────────────
    _last_trigger = [0.0]

    def idle_check():
        import time
        if not panel.autonomous_enabled:
            return
        now = time.time()
        if now - _last_trigger[0] < 120:
            return
        idle = now - panel.last_reply_time
        if idle > 1800:
            _last_trigger[0] = now
            panel.inject_message(
                "[AUTO]🤖 用户已经离开超过30分钟，作为自主智能体，请阅读自动化sop，执行自动任务。"
            )

    idle_timer = QTimer()
    idle_timer.timeout.connect(idle_check)
    idle_timer.start(5000)  # check every 5 s

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
