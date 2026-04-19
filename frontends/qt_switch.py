from __future__ import annotations

import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QDoubleSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ga_switch.models import PROVIDER_BACKEND_KINDS, ROUTE_KINDS
from ga_switch.viewmodel import build_provider_payload, build_route_payload, build_ui_viewmodel

# 设计令牌
COLORS = {
    # 背景
    "bg_primary": "#0a0a0e",
    "bg_secondary": "#12121a",
    "bg_tertiary": "#1a1a24",
    # 文本
    "text_primary": "#ececf1",
    "text_secondary": "#a1a1aa",
    "text_muted": "#71717a",
    # 边框
    "border_subtle": "#27272a",
    "border_default": "#3f3f46",
    # 强调色（蓝色系，更专业）
    "accent": "#3b82f6",
    "accent_hover": "#2563eb",
    "accent_bg": "rgba(59, 130, 246, 0.12)",
    "accent_border": "rgba(59, 130, 246, 0.3)",
    # 状态色
    "success": "#10b981",
    "success_bg": "rgba(16, 185, 129, 0.12)",
    "warning": "#f59e0b",
    "warning_bg": "rgba(245, 158, 11, 0.12)",
    "error": "#ef4444",
    "error_bg": "rgba(239, 68, 68, 0.12)",
}

SPACING = {
    "xs": "4px",
    "sm": "8px",
    "md": "12px",
    "lg": "16px",
    "xl": "24px",
}

RADIUS = {
    "sm": "6px",
    "md": "8px",
    "lg": "10px",
}

ROUTE_KIND_LABELS = {
    "single": "单路由",
    "failover": "备用链路",
}

PROVIDER_KIND_LABELS = {
    "native_claude": "原生 Claude",
    "native_oai": "原生 OpenAI",
    "claude_text": "Claude 文本接口",
    "oai_text": "OpenAI 文本接口",
}

API_MODE_LABELS = {
    "chat_completions": "聊天补全",
    "responses": "响应接口",
}


CARD_STYLE = f"""
QFrame {{
    background: {COLORS['bg_secondary']};
    border: 1px solid {COLORS['border_subtle']};
    border-radius: {RADIUS['md']};
}}
"""

LIST_STYLE = f"""
QListWidget {{
    background: {COLORS['bg_primary']};
    border: 1px solid {COLORS['border_subtle']};
    outline: none;
    color: {COLORS['text_primary']};
    border-radius: {RADIUS['md']};
    padding: 8px;
}}
QListWidget::item {{
    margin: 4px 0;
    padding: 10px 12px;
    border-radius: {RADIUS['sm']};
}}
QListWidget::item:hover {{
    background: rgba(62, 62, 75, 0.72);
}}
QListWidget::item:selected {{
    background: {COLORS['accent_bg']};
    color: white;
}}
"""

INPUT_STYLE = f"""
QLineEdit, QComboBox, QPlainTextEdit, QSpinBox, QDoubleSpinBox {{
    background: {COLORS['bg_primary']};
    color: {COLORS['text_primary']};
    border: 1px solid {COLORS['border_default']};
    border-radius: {RADIUS['sm']};
    padding: 6px 9px;
    selection-background-color: {COLORS['accent_bg']};
}}
QComboBox::drop-down {{
    border: none;
    width: 24px;
}}
QComboBox QAbstractItemView {{
    background: #111217;
    color: {COLORS['text_primary']};
    border: 1px solid {COLORS['border_default']};
    selection-background-color: {COLORS['accent_bg']};
}}
QPlainTextEdit {{
    padding: 8px 10px;
}}
"""

BUTTON_STYLE = f"""
QPushButton {{
    background: rgba(39, 39, 42, 0.82);
    color: {COLORS['text_primary']};
    border: 1px solid {COLORS['border_default']};
    border-radius: {RADIUS['sm']};
    padding: 7px 12px;
    font-weight: 600;
}}
QPushButton:hover {{
    background: rgba(63, 63, 70, 0.82);
}}
"""

PRIMARY_BUTTON_STYLE = f"""
QPushButton {{
    background: {COLORS['accent_bg']};
    color: {COLORS['text_primary']};
    border: 1px solid {COLORS['accent_border']};
    border-radius: {RADIUS['sm']};
    padding: 7px 12px;
    font-weight: 600;
}}
QPushButton:hover {{
    background: rgba(59, 130, 246, 0.18);
    border: 1px solid rgba(59, 130, 246, 0.4);
}}
"""

DANGER_BUTTON_STYLE = f"""
QPushButton {{
    background: {COLORS['error_bg']};
    color: #fee2e2;
    border: 1px solid rgba(239, 68, 68, 0.3);
    border-radius: {RADIUS['sm']};
    padding: 7px 12px;
    font-weight: 600;
}}
QPushButton:hover {{
    background: rgba(239, 68, 68, 0.18);
}}
"""

SECTION_STYLE = f"""
QPushButton {{
    background: rgba(20, 20, 24, 0.86);
    color: {COLORS['text_secondary']};
    border: 1px solid {COLORS['border_subtle']};
    border-radius: {RADIUS['md']};
    padding: 9px 16px;
    font-size: 13px;
    font-weight: 700;
}}
QPushButton:hover {{
    background: rgba(45, 45, 56, 0.92);
    color: #f4f4f5;
}}
"""

SECTION_ACTIVE_STYLE = f"""
QPushButton {{
    background: {COLORS['accent_bg']};
    color: {COLORS['text_primary']};
    border: 1px solid {COLORS['accent_border']};
    border-radius: {RADIUS['md']};
    padding: 9px 16px;
    font-size: 13px;
    font-weight: 700;
}}
QPushButton:hover {{
    background: rgba(59, 130, 246, 0.18);
}}
"""


def _clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()
        child = item.layout()
        if child is not None:
            _clear_layout(child)


def _card(title: str | None = None):
    frame = QFrame()
    frame.setStyleSheet(CARD_STYLE)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 16, 16, 16)
    layout.setSpacing(10)
    if title:
        label = QLabel(title)
        label.setStyleSheet("color: #f4f4f5; font-size: 14px; font-weight: 700;")
        layout.addWidget(label)
    return frame, layout


def _title(text):
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 20px; font-weight: 700;")
    return label


def _muted(text="", *, wrap=True):
    label = QLabel(text)
    label.setWordWrap(wrap)
    label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 13px;")
    return label


def _chip(text, tone="neutral"):
    styles = {
        "active": f"background: {COLORS['success_bg']}; color: #86efac; border: 1px solid rgba(16,185,129,0.3);",
        "warn": f"background: {COLORS['warning_bg']}; color: #fcd34d; border: 1px solid rgba(245,158,11,0.3);",
        "error": f"background: {COLORS['error_bg']}; color: #fca5a5; border: 1px solid rgba(239,68,68,0.3);",
        "blue": f"background: {COLORS['accent_bg']}; color: #93c5fd; border: 1px solid {COLORS['accent_border']};",
        "neutral": f"background: rgba(63,63,70,0.5); color: {COLORS['text_secondary']}; border: 1px solid {COLORS['border_default']};",
    }
    label = QLabel(text)
    label.setStyleSheet(
        f"QLabel {{ border-radius: {RADIUS['sm']}; padding: 4px 8px; font-size: 11px; font-weight: 600; "
        + styles.get(tone, styles["neutral"])
        + " }"
    )
    return label


def _button(text, *, primary=False, danger=False):
    btn = QPushButton(text)
    btn.setCursor(Qt.PointingHandCursor)
    if danger:
        btn.setStyleSheet(DANGER_BUTTON_STYLE)
    elif primary:
        btn.setStyleSheet(PRIMARY_BUTTON_STYLE)
    else:
        btn.setStyleSheet(BUTTON_STYLE)
    return btn


def _apply_input_style(widget):
    widget.setStyleSheet(INPUT_STYLE)
    return widget


def _make_scroll_page():
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(12)
    scroll.setWidget(container)
    return scroll, layout


class _MemberOrderList(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(LIST_STYLE)
        self.setMaximumHeight(180)

    def load_options(self, providers, selected_ids):
        selected_ids = list(selected_ids or [])
        provider_by_id = {provider["id"]: provider for provider in providers}
        ordered = [provider_by_id[pid] for pid in selected_ids if pid in provider_by_id]
        ordered.extend(provider for provider in providers if provider["id"] not in selected_ids)
        self.clear()
        for provider in ordered:
            item = QListWidgetItem(f"{provider['name']} · {provider.get('model') or '未设置模型'}")
            item.setData(Qt.UserRole, provider["id"])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            item.setCheckState(Qt.Checked if provider["id"] in selected_ids else Qt.Unchecked)
            self.addItem(item)

    def selected_ids(self):
        result = []
        for idx in range(self.count()):
            item = self.item(idx)
            if item.checkState() == Qt.Checked:
                result.append(item.data(Qt.UserRole))
        return result

    def move_current(self, delta):
        row = self.currentRow()
        target = row + delta
        if row < 0 or target < 0 or target >= self.count():
            return
        item = self.takeItem(row)
        self.insertItem(target, item)
        self.setCurrentRow(target)


class RouteCenterPage(QWidget):
    runtime_changed = Signal(object, object)
    request_chat_focus = Signal()

    def __init__(self, agent, service, parent=None):
        super().__init__(parent)
        self.agent = agent
        self.service = service
        self.page_id = "overview"
        self.snapshot = {}
        self.viewmodel = {}
        self._selected_route_id = None
        self._selected_provider_id = None
        self._selected_event_id = None
        self._route_edit_open = False
        self._route_create_open = False
        self._route_advanced_open = False
        self._route_create_advanced_open = False
        self._provider_edit_open = False
        self._provider_create_open = False
        self._provider_advanced_open = False
        self._provider_create_advanced_open = False
        self._diagnostic_raw_open = False
        self._overview_more_open = False
        self._last_test_result = None
        self._build_ui()
        self.refresh_snapshot()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        summary_card, summary_layout = _card()
        self._summary_title = _title("当前模型")
        self._summary_meta = _muted("继续使用当前模型")
        self._summary_notice = _muted("")
        self._summary_notice.hide()
        self._summary_chips = QHBoxLayout()
        self._summary_chips.setSpacing(8)
        self._summary_chips.addStretch()
        summary_layout.addWidget(self._summary_title)
        summary_layout.addWidget(self._summary_meta)
        summary_layout.addLayout(self._summary_chips)
        summary_layout.addWidget(self._summary_notice)
        root.addWidget(summary_card)

        nav_row = QHBoxLayout()
        nav_row.setSpacing(8)
        self._page_buttons = {}
        for page_id, label in self._page_defs():
            btn = QPushButton(label)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _checked=False, pid=page_id: self._set_page(pid))
            nav_row.addWidget(btn)
            self._page_buttons[page_id] = btn
        nav_row.addStretch()
        root.addLayout(nav_row)

        self._stack = QStackedWidget()
        self._pages = {}
        for page_id, _label in self._page_defs():
            scroll, layout = _make_scroll_page()
            self._stack.addWidget(scroll)
            self._pages[page_id] = {"widget": scroll, "layout": layout}
        root.addWidget(self._stack, 1)
        self._update_page_buttons()

    def _page_defs(self):
        return (
            ("overview", "总览"),
            ("routes", "全部路由"),
            ("providers", "模型服务"),
            ("diagnostics", "诊断记录"),
        )

    def _set_notice(self, text="", *, error=False):
        if not text:
            self._summary_notice.hide()
            self._summary_notice.setText("")
            return
        self._summary_notice.setText(text)
        self._summary_notice.setStyleSheet("color: #fecaca; font-size: 12px;" if error else "color: #bbf7d0; font-size: 12px;")
        self._summary_notice.show()

    def _set_page(self, page_id):
        if page_id == self.page_id:
            return
        self.page_id = page_id
        self._update_page_buttons()
        self._stack.setCurrentIndex(dict((pid, idx) for idx, (pid, _label) in enumerate(self._page_defs()))[page_id])

    def _update_page_buttons(self):
        for pid, btn in self._page_buttons.items():
            btn.setStyleSheet(SECTION_ACTIVE_STYLE if pid == self.page_id else SECTION_STYLE)

    def _run_action(self, func, success="", refresh=True):
        try:
            result = func()
        except Exception as exc:
            self._set_notice(str(exc), error=True)
            return None
        if refresh:
            self.refresh_snapshot(success)
        elif success:
            self._set_notice(success)
        return result

    def _ensure_selection(self):
        route_ids = [item["id"] for item in self.viewmodel.get("routes", [])]
        provider_ids = [item["id"] for item in self.viewmodel.get("providers", [])]
        event_ids = [item["id"] for item in self.viewmodel.get("events", [])]
        if self._selected_route_id not in route_ids:
            self._selected_route_id = route_ids[0] if route_ids else None
            self._route_edit_open = False
        if self._selected_provider_id not in provider_ids:
            self._selected_provider_id = provider_ids[0] if provider_ids else None
            self._provider_edit_open = False
        if self._selected_event_id not in event_ids:
            self._selected_event_id = event_ids[0] if event_ids else None

    def refresh_snapshot(self, notice="", *, error=False):
        if notice:
            self._set_notice(notice, error=error)
        self.snapshot = self.service.get_ui_snapshot(self.agent)
        self.viewmodel = build_ui_viewmodel(self.snapshot)
        self._ensure_selection()
        self._refresh_summary()
        self._render_overview_page()
        self._render_routes_page()
        self._render_providers_page()
        self._render_diagnostics_page()
        self.runtime_changed.emit(self.snapshot, self.viewmodel)

    def _refresh_summary(self):
        summary = self.viewmodel.get("summary", {})
        self._summary_title.setText(summary.get("headline") or "当前模型")
        self._summary_meta.setText(summary.get("meta") or "继续使用当前模型")
        while self._summary_chips.count():
            item = self._summary_chips.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        tone = summary.get("health_tone") or "neutral"
        chips = [
            _chip(summary.get("route_kind_label") or "单路由", "blue"),
            _chip(summary.get("health_label") or "状态未知", tone),
        ]
        if summary.get("active_member_name"):
            chips.append(_chip(summary["active_member_name"], "active"))
        if summary.get("native_tools"):
            chips.append(_chip("原生工具", "blue"))
        for widget in chips:
            self._summary_chips.addWidget(widget)
        self._summary_chips.addStretch()

    def _selected_route(self):
        return next((item for item in self.viewmodel.get("routes", []) if item["id"] == self._selected_route_id), None)

    def _selected_provider(self):
        return next((item for item in self.viewmodel.get("providers", []) if item["id"] == self._selected_provider_id), None)

    def _selected_event(self):
        return next((item for item in self.viewmodel.get("events", []) if item["id"] == self._selected_event_id), None)

    def _render_overview_page(self):
        layout = self._pages["overview"]["layout"]
        _clear_layout(layout)
        empty_state = self.viewmodel.get("empty_state")
        overview = self.viewmodel.get("overview", {})

        if empty_state:
            current_card, current_layout = _card("当前模型")
            current_layout.addWidget(_title(self.viewmodel["summary"].get("headline") or "当前模型"))
            current_layout.addWidget(_muted(self.viewmodel["summary"].get("meta") or "继续使用当前模型"))
            keep_btn = _button("继续使用当前模型", primary=True)
            keep_btn.clicked.connect(self.request_chat_focus.emit)
            current_layout.addWidget(keep_btn)
            layout.addWidget(current_card)

            card, card_layout = _card("开始配置路由")
            card_layout.addWidget(_title(empty_state["title"]))
            card_layout.addWidget(_muted(empty_state["message"]))
            action_row = QHBoxLayout()
            action_row.setSpacing(8)
            for action in empty_state["actions"]:
                btn = _button(action["label"], primary=action.get("primary", False))
                btn.clicked.connect(lambda _checked=False, aid=action["id"]: self._handle_overview_action(aid, None, None, None))
                action_row.addWidget(btn)
            action_row.addStretch()
            card_layout.addLayout(action_row)
            layout.addWidget(card)
            layout.addStretch()
            return

        current_card, current_layout = _card("当前路由")
        current = overview.get("current_route_card", {})
        current_layout.addWidget(_title(current.get("headline") or "当前路由"))
        current_layout.addWidget(_muted(current.get("subtitle") or "暂无说明"))
        chip_row = QHBoxLayout()
        chip_row.setSpacing(8)
        chip_row.addWidget(_chip(current.get("status_label") or "状态未知", current.get("status_tone") or "neutral"))
        for badge in current.get("badges", []):
            if badge:
                chip_row.addWidget(_chip(badge, "blue"))
        chip_row.addStretch()
        current_layout.addLayout(chip_row)
        layout.addWidget(current_card)

        top_row = QHBoxLayout()
        top_row.setSpacing(12)

        health_card, health_layout = _card("健康状态")
        health = overview.get("health_card", {})
        health_layout.addWidget(_title(health.get("headline") or "状态未知"))
        health_layout.addWidget(_muted(health.get("detail") or "暂无诊断信息"))
        top_row.addWidget(health_card, 1)

        action_card, action_layout = _card("快捷操作")
        route_combo = _apply_input_style(QComboBox())
        for route in self.viewmodel.get("routes", []):
            route_combo.addItem(f"{route['title']} · {route['subtitle']}", route["id"])
        current_route_id = self.viewmodel["summary"].get("route_id")
        idx = route_combo.findData(current_route_id)
        if idx >= 0:
            route_combo.setCurrentIndex(idx)
        action_layout.addWidget(route_combo)
        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        actions = overview.get("quick_actions", [])
        primary_done = False
        for action in actions:
            is_primary = action.get("primary", False) and not primary_done
            if is_primary:
                primary_done = True
            btn = _button(action["label"], primary=is_primary)
            btn.clicked.connect(
                lambda _checked=False, aid=action["id"], combo=route_combo: self._handle_overview_action(
                    aid, combo.currentData(), None, None
                )
            )
            action_row.addWidget(btn)
        action_row.addStretch()
        action_layout.addLayout(action_row)
        if self._overview_more_open:
            more = self._build_runtime_more_panel()
            action_layout.addWidget(more)
        top_row.addWidget(action_card, 1)
        layout.addLayout(top_row)

        summary_card, summary_layout = _card("路由列表摘要")
        for route in overview.get("route_summary_items", []):
            row = QHBoxLayout()
            row.setSpacing(8)
            row.addWidget(_chip(route.get("status_label") or "待命", "active" if route.get("active") else "neutral"))
            text = QLabel(f"{route['title']}  ·  {route['subtitle']}")
            text.setWordWrap(True)
            text.setStyleSheet("color: #ececf1; font-size: 13px; font-weight: 600;")
            row.addWidget(text, 1)
            btn = _button("查看详情")
            btn.clicked.connect(lambda _checked=False, rid=route["id"]: self._open_route_detail(rid))
            row.addWidget(btn)
            summary_layout.addLayout(row)
        all_btn = _button("查看全部路由")
        all_btn.clicked.connect(lambda: self._set_page("routes"))
        summary_layout.addWidget(all_btn)
        layout.addWidget(summary_card)
        layout.addStretch()

    def _render_routes_page(self):
        layout = self._pages["routes"]["layout"]
        _clear_layout(layout)
        routes = self.viewmodel.get("routes", [])

        head, head_layout = _card("全部路由")
        head_layout.addWidget(_muted("先看摘要，再决定是否展开编辑。"))
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        create_btn = _button("新建路由", primary=True)
        create_btn.clicked.connect(self._toggle_route_create)
        toolbar.addWidget(create_btn)
        toolbar.addStretch()
        head_layout.addLayout(toolbar)
        layout.addWidget(head)

        if not routes:
            empty, empty_layout = _card()
            empty_layout.addWidget(_title("还没有路由"))
            empty_layout.addWidget(_muted("先导入 mykey 或新建路由。"))
            layout.addWidget(empty)
            if self._route_create_open:
                layout.addWidget(self._build_route_form_panel(None, create_mode=True))
            layout.addStretch()
            return

        list_card, list_layout = _card("路由列表")
        list_widget = QListWidget()
        list_widget.setStyleSheet(LIST_STYLE)
        list_widget.setMaximumHeight(230)
        current_row = 0
        for idx, route in enumerate(routes):
            item = QListWidgetItem(f"{route['title']}\n{route['subtitle']} · {route['status_label']} · {route['health_label']}")
            item.setData(Qt.UserRole, route["id"])
            list_widget.addItem(item)
            if route["id"] == self._selected_route_id:
                current_row = idx
        list_widget.setCurrentRow(current_row)
        list_widget.currentItemChanged.connect(lambda current, _previous: self._select_route_item(current))
        list_layout.addWidget(list_widget)
        layout.addWidget(list_card)

        route = self._selected_route()
        if route:
            detail, detail_layout = _card("路由摘要")
            detail_layout.addWidget(_title(route["title"]))
            detail_layout.addWidget(_muted(route["subtitle"]))
            chips = QHBoxLayout()
            chips.setSpacing(8)
            chips.addWidget(_chip(route["kind_label"], "blue"))
            chips.addWidget(_chip(route["status_label"], "active" if route["active"] else "neutral"))
            chips.addWidget(_chip(route["health_label"], route["health_tone"]))
            if route.get("active_member_name"):
                chips.addWidget(_chip(route["active_member_name"], "active"))
            chips.addStretch()
            detail_layout.addLayout(chips)
            if route.get("last_error_message"):
                detail_layout.addWidget(_muted(route["last_error_message"]))
            action_row = QHBoxLayout()
            action_row.setSpacing(8)
            activate_btn = _button("设为当前")
            activate_btn.clicked.connect(lambda: self._activate_route(route["id"], route["title"]))
            edit_btn = _button("编辑路由")
            edit_btn.clicked.connect(self._toggle_route_edit)
            delete_btn = _button("删除路由", danger=True)
            delete_btn.clicked.connect(lambda: self._delete_route(route["id"], route["title"]))
            action_row.addWidget(activate_btn)
            action_row.addWidget(edit_btn)
            action_row.addWidget(delete_btn)
            action_row.addStretch()
            detail_layout.addLayout(action_row)
            layout.addWidget(detail)
            if self._route_edit_open:
                layout.addWidget(self._build_route_form_panel(route["id"], create_mode=False))

        if self._route_create_open:
            layout.addWidget(self._build_route_form_panel(None, create_mode=True))
        layout.addStretch()

    def _render_providers_page(self):
        layout = self._pages["providers"]["layout"]
        _clear_layout(layout)
        providers = self.viewmodel.get("providers", [])

        head, head_layout = _card("模型服务")
        head_layout.addWidget(_muted("默认只显示摘要和高频动作，编辑时再展开完整配置。"))
        toolbar = QHBoxLayout()
        create_btn = _button("新建模型服务", primary=True)
        create_btn.clicked.connect(self._toggle_provider_create)
        toolbar.addWidget(create_btn)
        toolbar.addStretch()
        head_layout.addLayout(toolbar)
        layout.addWidget(head)

        if not providers:
            empty, empty_layout = _card()
            empty_layout.addWidget(_title("还没有模型服务"))
            empty_layout.addWidget(_muted("先新建模型服务，再创建路由。"))
            layout.addWidget(empty)
            if self._provider_create_open:
                layout.addWidget(self._build_provider_form_panel(None, create_mode=True))
            layout.addStretch()
            return

        list_card, list_layout = _card("模型服务列表")
        list_widget = QListWidget()
        list_widget.setStyleSheet(LIST_STYLE)
        list_widget.setMaximumHeight(230)
        current_row = 0
        for idx, provider in enumerate(providers):
            item = QListWidgetItem(f"{provider['title']}\n{provider['subtitle']} · {provider['health_label']}")
            item.setData(Qt.UserRole, provider["id"])
            list_widget.addItem(item)
            if provider["id"] == self._selected_provider_id:
                current_row = idx
        list_widget.setCurrentRow(current_row)
        list_widget.currentItemChanged.connect(lambda current, _previous: self._select_provider_item(current))
        list_layout.addWidget(list_widget)
        layout.addWidget(list_card)

        provider = self._selected_provider()
        if provider:
            detail, detail_layout = _card("模型服务摘要")
            detail_layout.addWidget(_title(provider["title"]))
            detail_layout.addWidget(_muted(provider["subtitle"]))
            chips = QHBoxLayout()
            chips.setSpacing(8)
            chips.addWidget(_chip(provider["health_label"], provider["health_tone"]))
            chips.addWidget(_chip("原生工具" if provider["is_native"] else "文本接口", "blue"))
            chips.addWidget(_chip(f"延迟 {provider.get('latency_ms') or '-'} ms"))
            chips.addStretch()
            detail_layout.addLayout(chips)
            if provider.get("last_error"):
                detail_layout.addWidget(_muted(provider["last_error"]))
            if self._last_test_result and self._last_test_result.get("provider_id") == provider["id"]:
                detail_layout.addWidget(_muted(f"最近测试：{self._last_test_result.get('status', '完成')}"))
            action_row = QHBoxLayout()
            test_btn = _button("连通性测试", primary=True)
            test_btn.clicked.connect(lambda: self._run_model_test(provider["id"], provider["title"]))
            edit_btn = _button("编辑模型服务")
            edit_btn.clicked.connect(self._toggle_provider_edit)
            delete_btn = _button("删除模型服务", danger=True)
            delete_btn.clicked.connect(lambda: self._delete_provider(provider["id"], provider["title"]))
            action_row.addWidget(test_btn)
            action_row.addWidget(edit_btn)
            action_row.addWidget(delete_btn)
            action_row.addStretch()
            detail_layout.addLayout(action_row)
            layout.addWidget(detail)
            if self._provider_edit_open:
                layout.addWidget(self._build_provider_form_panel(provider["id"], create_mode=False))

        if self._provider_create_open:
            layout.addWidget(self._build_provider_form_panel(None, create_mode=True))
        layout.addStretch()

    def _render_diagnostics_page(self):
        layout = self._pages["diagnostics"]["layout"]
        _clear_layout(layout)
        events = self.viewmodel.get("events", [])

        head, head_layout = _card("诊断记录")
        head_layout.addWidget(_muted("默认只看摘要；需要时再展开原始详情。"))
        layout.addWidget(head)

        if not events:
            empty, empty_layout = _card()
            empty_layout.addWidget(_title("还没有诊断记录"))
            empty_layout.addWidget(_muted("调用模型、切换路由或连通性测试后，这里会出现记录。"))
            layout.addWidget(empty)
            layout.addStretch()
            return

        list_card, list_layout = _card("事件列表")
        list_widget = QListWidget()
        list_widget.setStyleSheet(LIST_STYLE)
        list_widget.setMaximumHeight(250)
        current_row = 0
        for idx, event in enumerate(events):
            prefix = "● " if event.get("tone") == "active" else "!"
            item = QListWidgetItem(f"{prefix}{event['title']}\n{event['subtitle']}")
            item.setData(Qt.UserRole, event["id"])
            list_widget.addItem(item)
            if event["id"] == self._selected_event_id:
                current_row = idx
        list_widget.setCurrentRow(current_row)
        list_widget.currentItemChanged.connect(lambda current, _previous: self._select_event_item(current))
        list_layout.addWidget(list_widget)
        layout.addWidget(list_card)

        event = self._selected_event()
        if event:
            detail, detail_layout = _card("记录摘要")
            detail_layout.addWidget(_title(event["title"]))
            detail_layout.addWidget(_muted(event["subtitle"]))
            chips = QHBoxLayout()
            chips.setSpacing(8)
            chips.addWidget(_chip(event.get("error_kind") or ("成功" if event.get("tone") == "active" else "异常"), "active" if event.get("tone") == "active" else "error"))
            if event.get("status_code") is not None:
                chips.addWidget(_chip(str(event["status_code"]), "blue"))
            if event.get("created_at"):
                chips.addWidget(_chip(event["created_at"]))
            chips.addStretch()
            detail_layout.addLayout(chips)
            raw_btn = _button("查看原始详情" if not self._diagnostic_raw_open else "收起原始详情")
            raw_btn.clicked.connect(self._toggle_diagnostic_raw)
            detail_layout.addWidget(raw_btn)
            if self._diagnostic_raw_open:
                raw = QPlainTextEdit()
                raw.setReadOnly(True)
                raw.setMaximumHeight(220)
                _apply_input_style(raw)
                raw.setPlainText(json.dumps(event["payload"], ensure_ascii=False, indent=2))
                detail_layout.addWidget(raw)
            layout.addWidget(detail)
        layout.addStretch()

    def _handle_overview_action(self, action_id, route_id, _one, _two):
        if action_id == "switch_route":
            self._activate_route(route_id, "所选路由")
        elif action_id == "soft_reload":
            self._run_action(lambda: self.agent.reload_llm_config(preserve_history=True), success="已完成软重载。")
        elif action_id == "import_legacy":
            self._pick_and_import_legacy()
        elif action_id == "create_provider":
            self._provider_create_open = True
            self._set_page("providers")
            self._render_providers_page()
        elif action_id == "continue_chat":
            self.request_chat_focus.emit()
        elif action_id == "more_actions":
            self._overview_more_open = not self._overview_more_open
            self._render_overview_page()

    def _build_runtime_more_panel(self):
        panel, layout = _card("更多操作")
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)

        structured_box = QCheckBox("启用结构化路由")
        structured_box.setChecked(bool(self.snapshot.get("use_structured_config")))
        structured_box.setStyleSheet("color: #d4d4d8;")

        preserve_box = QCheckBox("软重载时保留上下文")
        preserve_box.setChecked(True)
        preserve_box.setStyleSheet("color: #d4d4d8;")

        import_path = _apply_input_style(QLineEdit(""))
        browse_btn = _button("选择文件")
        path_row = QWidget()
        path_layout = QHBoxLayout(path_row)
        path_layout.setContentsMargins(0, 0, 0, 0)
        path_layout.setSpacing(8)
        path_layout.addWidget(import_path, 1)
        path_layout.addWidget(browse_btn)
        browse_btn.clicked.connect(lambda: self._browse_import_path(import_path))

        form.addRow("结构化路由", structured_box)
        form.addRow("软重载", preserve_box)
        form.addRow("导入文件", path_row)
        layout.addLayout(form)

        row = QHBoxLayout()
        apply_btn = _button("保存模式")
        apply_btn.clicked.connect(
            lambda: self._run_action(
                lambda: self.service.set_structured_config_enabled(structured_box.isChecked()),
                success="已更新结构化路由开关。",
            )
        )
        import_btn = _button("导入并应用")
        import_btn.clicked.connect(
            lambda: self._run_action(
                lambda: self.service.import_legacy_mykey(import_path.text().strip() or None),
                success="已导入旧版配置。",
            )
        )
        reload_btn = _button("立即软重载")
        reload_btn.clicked.connect(
            lambda: self._run_action(
                lambda: self.agent.reload_llm_config(preserve_history=preserve_box.isChecked()),
                success="已完成软重载。",
            )
        )
        row.addWidget(apply_btn)
        row.addWidget(import_btn)
        row.addWidget(reload_btn)
        row.addStretch()
        layout.addLayout(row)
        return panel

    def _build_route_form_panel(self, route_id, *, create_mode):
        route = next((item for item in self.viewmodel.get("routes", []) if item["id"] == route_id), None) if route_id is not None else None
        payload = self.snapshot.get("routes_by_id", {}).get(route_id) if route_id is not None else None
        panel, layout = _card("新建路由" if create_mode else "编辑路由")
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)

        name_edit = _apply_input_style(QLineEdit((route or {}).get("title", "")))
        kind_combo = _apply_input_style(QComboBox())
        for route_kind in ROUTE_KINDS:
            kind_combo.addItem(ROUTE_KIND_LABELS.get(route_kind, route_kind), route_kind)
        current_kind = (route or {}).get("kind", "single")
        kind_idx = kind_combo.findData(current_kind)
        kind_combo.setCurrentIndex(kind_idx if kind_idx >= 0 else 0)

        provider_combo = _apply_input_style(QComboBox())
        provider_combo.addItem("请选择模型服务", None)
        for provider in self.snapshot.get("providers", []):
            provider_combo.addItem(f"{provider['name']} · {provider.get('model') or '未设置模型'}", provider["id"])
        if route and route.get("provider_id") is not None:
            idx = provider_combo.findData(route["provider_id"])
            if idx >= 0:
                provider_combo.setCurrentIndex(idx)

        member_list = _MemberOrderList()
        member_list.load_options(self.snapshot.get("providers", []), (route or {}).get("member_provider_ids", []))
        member_row = QHBoxLayout()
        move_up = _button("上移")
        move_up.clicked.connect(lambda: member_list.move_current(-1))
        move_down = _button("下移")
        move_down.clicked.connect(lambda: member_list.move_current(1))
        member_row.addWidget(move_up)
        member_row.addWidget(move_down)
        member_row.addStretch()

        default_box = QCheckBox("设为默认路由")
        default_box.setChecked(bool((route or {}).get("is_default", False)))
        default_box.setStyleSheet("color: #d4d4d8;")
        enabled_box = QCheckBox("启用此路由")
        enabled_box.setChecked(bool((route or {}).get("enabled", True)))
        enabled_box.setStyleSheet("color: #d4d4d8;")

        form.addRow("路由名称", name_edit)
        form.addRow("路由类型", kind_combo)
        form.addRow("主要模型服务", provider_combo)
        flags = QWidget()
        flags_layout = QHBoxLayout(flags)
        flags_layout.setContentsMargins(0, 0, 0, 0)
        flags_layout.addWidget(default_box)
        flags_layout.addWidget(enabled_box)
        flags_layout.addStretch()
        form.addRow("路由状态", flags)
        layout.addLayout(form)

        advanced_open = self._route_create_advanced_open if create_mode else self._route_advanced_open
        advanced_btn = _button("展开高级设置" if not advanced_open else "收起高级设置")
        advanced_btn.clicked.connect(lambda: self._toggle_route_advanced(create_mode))
        layout.addWidget(advanced_btn)

        if advanced_open:
            adv, adv_layout = _card("高级设置")
            hint = _muted("备用链路的成员顺序会按列表上下顺序生效。")
            adv_layout.addWidget(hint)
            single_box = QWidget()
            single_layout = QVBoxLayout(single_box)
            single_layout.setContentsMargins(0, 0, 0, 0)
            single_layout.addWidget(_muted("单路由只使用上面的“主要模型服务”。"))

            failover_box = QWidget()
            failover_layout = QVBoxLayout(failover_box)
            failover_layout.setContentsMargins(0, 0, 0, 0)
            failover_layout.setSpacing(8)
            failover_layout.addWidget(_muted("勾选成员后可用“上移 / 下移”调整备用链路顺序。"))
            failover_layout.addWidget(member_list)
            failover_layout.addLayout(member_row)

            retries_spin = _apply_input_style(QSpinBox())
            retries_spin.setRange(0, 100)
            retries_spin.setValue(int(((route or {}).get("config") or {}).get("max_retries", 3)))
            delay_spin = _apply_input_style(QDoubleSpinBox())
            delay_spin.setRange(0.0, 999.0)
            delay_spin.setDecimals(2)
            delay_spin.setSingleStep(0.25)
            delay_spin.setValue(float(((route or {}).get("config") or {}).get("base_delay", 1.5)))
            spring_spin = _apply_input_style(QSpinBox())
            spring_spin.setRange(0, 86400)
            spring_spin.setValue(int(((route or {}).get("config") or {}).get("spring_back", 300)))

            adv_form = QFormLayout()
            adv_form.setLabelAlignment(Qt.AlignLeft)
            adv_form.setHorizontalSpacing(14)
            adv_form.setVerticalSpacing(10)
            adv_form.addRow("备用链路成员", failover_box)
            adv_form.addRow("最大重试次数", retries_spin)
            adv_form.addRow("基础退避秒数", delay_spin)
            adv_form.addRow("回弹时间（秒）", spring_spin)
            adv_layout.addLayout(adv_form)

            def submit_values():
                try:
                    values = {
                        "name": name_edit.text(),
                        "kind": kind_combo.currentData(),
                        "is_default": default_box.isChecked(),
                        "is_enabled": enabled_box.isChecked(),
                        "provider_id": provider_combo.currentData(),
                        "member_provider_ids": member_list.selected_ids(),
                        "max_retries": retries_spin.value(),
                        "base_delay": delay_spin.value(),
                        "spring_back": spring_spin.value(),
                    }
                    return build_route_payload(values, route_id=(payload or {}).get("id"))
                except Exception as exc:
                    self._set_notice(str(exc), error=True)
                    return None

            submit_builder = submit_values
            layout.addWidget(adv)
        else:
            def submit_values():
                try:
                    existing_config = dict((payload or {}).get("config") or {})
                    selected_kind = kind_combo.currentData() or "single"
                    values = {
                        "name": name_edit.text(),
                        "kind": selected_kind,
                        "is_default": default_box.isChecked(),
                        "is_enabled": enabled_box.isChecked(),
                        "provider_id": provider_combo.currentData() if selected_kind == "single" else None,
                        "member_provider_ids": [] if selected_kind == "single" else list((payload or {}).get("member_provider_ids") or []),
                        "max_retries": existing_config.get("max_retries", 3),
                        "base_delay": existing_config.get("base_delay", 1.5),
                        "spring_back": existing_config.get("spring_back", 300),
                    }
                    return build_route_payload(values, route_id=(payload or {}).get("id"))
                except Exception as exc:
                    self._set_notice(str(exc), error=True)
                    return None

            submit_builder = submit_values

        def sync_kind():
            is_single = kind_combo.currentData() == "single"
            provider_combo.setEnabled(True)
            if not advanced_open:
                return
            member_list.setVisible(not is_single)
            move_up.setVisible(not is_single)
            move_down.setVisible(not is_single)
        kind_combo.currentIndexChanged.connect(lambda _idx: sync_kind())
        sync_kind()

        actions = QHBoxLayout()
        save_btn = _button("创建路由" if create_mode else "保存路由", primary=True)
        save_btn.clicked.connect(
            lambda: self._submit_route(submit_builder(), create_mode=create_mode)
        )
        actions.addWidget(save_btn)
        actions.addStretch()
        layout.addLayout(actions)
        return panel

    def _submit_route(self, payload, *, create_mode):
        if not payload:
            return
        result = self._run_action(
            lambda: self.service.upsert_route(payload),
            success="已保存路由配置。若需立即生效，请执行软重载。",
            refresh=False,
        )
        if not result:
            return
        if create_mode:
            self._route_create_open = False
            self._route_create_advanced_open = False
        else:
            self._route_edit_open = False
            self._route_advanced_open = False
        self.refresh_snapshot()

    def _build_provider_form_panel(self, provider_id, *, create_mode):
        provider_vm = next((item for item in self.viewmodel.get("providers", []) if item["id"] == provider_id), None) if provider_id is not None else None
        provider = self.snapshot.get("providers_by_id", {}).get(provider_id) if provider_id is not None else None
        panel, layout = _card("新建模型服务" if create_mode else "编辑模型服务")
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)

        name_edit = _apply_input_style(QLineEdit((provider or {}).get("name", "")))
        kind_combo = _apply_input_style(QComboBox())
        for backend_kind in PROVIDER_BACKEND_KINDS:
            kind_combo.addItem(PROVIDER_KIND_LABELS.get(backend_kind, backend_kind), backend_kind)
        current_backend_kind = (provider or {}).get("backend_kind", "oai_text")
        kind_idx = kind_combo.findData(current_backend_kind)
        kind_combo.setCurrentIndex(kind_idx if kind_idx >= 0 else 0)
        model_edit = _apply_input_style(QLineEdit((provider or {}).get("model", "")))
        base_edit = _apply_input_style(QLineEdit((provider or {}).get("apibase", "")))
        form.addRow("名称", name_edit)
        form.addRow("接口类型", kind_combo)
        form.addRow("模型 ID", model_edit)
        form.addRow("接口地址", base_edit)
        layout.addLayout(form)

        advanced_open = self._provider_create_advanced_open if create_mode else self._provider_advanced_open
        advanced_btn = _button("展开高级设置" if not advanced_open else "收起高级设置")
        advanced_btn.clicked.connect(lambda: self._toggle_provider_advanced(create_mode))
        layout.addWidget(advanced_btn)

        if advanced_open:
            adv, adv_layout = _card("高级设置")
            adv_form = QFormLayout()
            adv_form.setLabelAlignment(Qt.AlignLeft)
            adv_form.setHorizontalSpacing(14)
            adv_form.setVerticalSpacing(10)

            apikey_edit = _apply_input_style(QLineEdit((provider or {}).get("apikey", "")))
            apikey_edit.setEchoMode(QLineEdit.Password)
            api_mode_combo = _apply_input_style(QComboBox())
            for api_mode in ("chat_completions", "responses"):
                api_mode_combo.addItem(API_MODE_LABELS.get(api_mode, api_mode), api_mode)
            current_api_mode = (provider or {}).get("api_mode", "chat_completions")
            api_mode_idx = api_mode_combo.findData(current_api_mode)
            api_mode_combo.setCurrentIndex(api_mode_idx if api_mode_idx >= 0 else 0)
            temperature_spin = _apply_input_style(QDoubleSpinBox())
            temperature_spin.setRange(0.0, 2.0)
            temperature_spin.setDecimals(2)
            temperature_spin.setSingleStep(0.1)
            temperature_spin.setValue(float((provider or {}).get("temperature", 1.0)))
            max_tokens_spin = _apply_input_style(QSpinBox())
            max_tokens_spin.setRange(1, 1000000)
            max_tokens_spin.setValue(int((provider or {}).get("max_tokens", 8192)))
            timeout_spin = _apply_input_style(QSpinBox())
            timeout_spin.setRange(1, 300)
            timeout_spin.setValue(int((provider or {}).get("timeout", 5)))
            read_timeout_spin = _apply_input_style(QSpinBox())
            read_timeout_spin.setRange(1, 600)
            read_timeout_spin.setValue(int((provider or {}).get("read_timeout", 30)))
            proxy_edit = _apply_input_style(QLineEdit((provider or {}).get("proxy", "") or ""))
            extra_edit = _apply_input_style(QPlainTextEdit())
            extra_edit.setMaximumHeight(120)
            extra_edit.setPlainText(json.dumps((provider or {}).get("extra", {}), ensure_ascii=False, indent=2))

            adv_form.addRow("密钥", apikey_edit)
            adv_form.addRow("请求模式", api_mode_combo)
            adv_form.addRow("温度", temperature_spin)
            adv_form.addRow("最大词元", max_tokens_spin)
            adv_form.addRow("连接超时", timeout_spin)
            adv_form.addRow("读取超时", read_timeout_spin)
            adv_form.addRow("代理", proxy_edit)
            adv_form.addRow("附加 JSON", extra_edit)
            adv_layout.addLayout(adv_form)
            layout.addWidget(adv)

            def submit_values():
                try:
                    values = {
                        "name": name_edit.text(),
                        "backend_kind": kind_combo.currentData(),
                        "apikey": apikey_edit.text(),
                        "apibase": base_edit.text(),
                        "model": model_edit.text(),
                        "api_mode": api_mode_combo.currentData(),
                        "temperature": temperature_spin.value(),
                        "max_tokens": max_tokens_spin.value(),
                        "timeout": timeout_spin.value(),
                        "read_timeout": read_timeout_spin.value(),
                        "proxy": proxy_edit.text(),
                        "extra": extra_edit.toPlainText(),
                    }
                    return build_provider_payload(values, provider_id=(provider or {}).get("id"))
                except Exception as exc:
                    self._set_notice(str(exc), error=True)
                    return None

            submit_builder = submit_values
        else:
            def submit_values():
                try:
                    existing_provider = provider or {}
                    values = {
                        "name": name_edit.text(),
                        "backend_kind": kind_combo.currentData(),
                        "apikey": existing_provider.get("apikey", ""),
                        "apibase": base_edit.text(),
                        "model": model_edit.text(),
                        "api_mode": existing_provider.get("api_mode", "chat_completions"),
                        "temperature": existing_provider.get("temperature", 1.0),
                        "max_tokens": existing_provider.get("max_tokens", 8192),
                        "timeout": existing_provider.get("timeout", 5),
                        "read_timeout": existing_provider.get("read_timeout", 30),
                        "proxy": existing_provider.get("proxy", "") or "",
                        "extra": json.dumps(existing_provider.get("extra", {}), ensure_ascii=False),
                    }
                    return build_provider_payload(values, provider_id=(provider or {}).get("id"))
                except Exception as exc:
                    self._set_notice(str(exc), error=True)
                    return None

            submit_builder = submit_values

        if provider_vm and provider_vm.get("last_error"):
            layout.addWidget(_muted(f"最近错误：{provider_vm['last_error']}"))

        actions = QHBoxLayout()
        save_btn = _button("创建模型服务" if create_mode else "保存模型服务", primary=True)
        save_btn.clicked.connect(lambda: self._submit_provider(submit_builder(), create_mode=create_mode))
        actions.addWidget(save_btn)
        actions.addStretch()
        layout.addLayout(actions)
        return panel

    def _submit_provider(self, payload, *, create_mode):
        if not payload:
            return
        result = self._run_action(
            lambda: self.service.upsert_provider(payload),
            success="已保存模型服务。若需立即生效，请执行软重载。",
            refresh=False,
        )
        if not result:
            return
        if create_mode:
            self._provider_create_open = False
            self._provider_create_advanced_open = False
        else:
            self._provider_edit_open = False
            self._provider_advanced_open = False
        self.refresh_snapshot()

    def _activate_route(self, route_id, route_name):
        self._run_action(lambda: self.agent.set_active_route(route_id), success=f"已切换到 {route_name}。")

    def _delete_route(self, route_id, route_name):
        self._run_action(lambda: self.service.delete_route(route_id), success=f"已删除路由 {route_name}。")

    def _delete_provider(self, provider_id, provider_name):
        self._run_action(lambda: self.service.delete_provider(provider_id), success=f"已删除模型服务 {provider_name}。")

    def _run_model_test(self, provider_id, provider_name):
        def _action():
            result = self.service.run_model_test(provider_id)
            result["provider_id"] = provider_id
            self._last_test_result = result
            return result

        result = self._run_action(_action, success=f"已完成 {provider_name} 的连通性测试。")
        if result:
            self._set_notice(f"连通性测试结果：{result.get('status', '完成')}")

    def _pick_and_import_legacy(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择旧版配置文件",
            "",
            "配置文件 (*.py *.json);;所有文件 (*)",
        )
        if path:
            self._run_action(lambda: self.service.import_legacy_mykey(path), success="已导入旧版配置。")

    def _browse_import_path(self, line_edit):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择旧版配置文件",
            "",
            "配置文件 (*.py *.json);;所有文件 (*)",
        )
        if path:
            line_edit.setText(path)

    def _open_route_detail(self, route_id):
        self._selected_route_id = route_id
        self._set_page("routes")
        self._render_routes_page()

    def _toggle_route_edit(self):
        self._route_create_open = False
        self._route_create_advanced_open = False
        self._route_edit_open = not self._route_edit_open
        if not self._route_edit_open:
            self._route_advanced_open = False
        self._render_routes_page()

    def _toggle_route_create(self):
        self._route_edit_open = False
        self._route_advanced_open = False
        self._route_create_open = not self._route_create_open
        if not self._route_create_open:
            self._route_create_advanced_open = False
        self._render_routes_page()

    def _toggle_route_advanced(self, create_mode):
        if create_mode:
            self._route_create_advanced_open = not self._route_create_advanced_open
        else:
            self._route_advanced_open = not self._route_advanced_open
        self._render_routes_page()

    def _toggle_provider_edit(self):
        self._provider_create_open = False
        self._provider_create_advanced_open = False
        self._provider_edit_open = not self._provider_edit_open
        if not self._provider_edit_open:
            self._provider_advanced_open = False
        self._render_providers_page()

    def _toggle_provider_create(self):
        self._provider_edit_open = False
        self._provider_advanced_open = False
        self._provider_create_open = not self._provider_create_open
        if not self._provider_create_open:
            self._provider_create_advanced_open = False
        self._render_providers_page()

    def _toggle_provider_advanced(self, create_mode):
        if create_mode:
            self._provider_create_advanced_open = not self._provider_create_advanced_open
        else:
            self._provider_advanced_open = not self._provider_advanced_open
        self._render_providers_page()

    def _toggle_diagnostic_raw(self):
        self._diagnostic_raw_open = not self._diagnostic_raw_open
        self._render_diagnostics_page()

    def _select_route_item(self, current):
        if current is None:
            return
        self._selected_route_id = current.data(Qt.UserRole)
        self._route_edit_open = False
        self._route_advanced_open = False
        self._render_routes_page()

    def _select_provider_item(self, current):
        if current is None:
            return
        self._selected_provider_id = current.data(Qt.UserRole)
        self._provider_edit_open = False
        self._provider_advanced_open = False
        self._render_providers_page()

    def _select_event_item(self, current):
        if current is None:
            return
        self._selected_event_id = current.data(Qt.UserRole)
        self._diagnostic_raw_open = False
        self._render_diagnostics_page()
