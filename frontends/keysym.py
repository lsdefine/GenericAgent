"""Cross-platform keyboard-shortcut display formatter.

One job: turn a Textual binding string like ``"ctrl+b"`` into a human-facing
label such as ``"Ctrl+B"`` on Win/Linux or ``"⌃B"`` on macOS.

Binding strings (the *physical* keys Textual captures) are NOT touched —
this module only formats labels for tips / footers / help panels.

Override with env ``GA_KEYSYM_STYLE=auto|mac|ascii`` (default ``auto``).
"""
from __future__ import annotations

import os
import sys

_STYLE = os.environ.get("GA_KEYSYM_STYLE", "auto").lower()
IS_MAC = _STYLE == "mac" or (_STYLE != "ascii" and sys.platform == "darwin")

# Modifier display per style. mac uses Apple HIG glyphs; others use words.
_MOD = {
    "ctrl":  "⌃" if IS_MAC else "Ctrl",
    "shift": "⇧" if IS_MAC else "Shift",
    "alt":   "⌥" if IS_MAC else "Alt",
    "meta":  "⌘" if IS_MAC else "Alt",
    "super": "⌘" if IS_MAC else "Win",
    "cmd":   "⌘" if IS_MAC else "Win",
}

# Bare-key display. Arrows / slash are universal; rest mac-glyphs vs words.
_KEY = {
    "enter":     "⏎" if IS_MAC else "Enter",
    "tab":       "⇥" if IS_MAC else "Tab",
    "escape":    "⎋" if IS_MAC else "Esc",
    "esc":       "⎋" if IS_MAC else "Esc",
    "backspace": "⌫" if IS_MAC else "Backspace",
    "delete":    "⌦" if IS_MAC else "Del",
    "space":     "␣" if IS_MAC else "Space",
    "up": "↑", "down": "↓", "left": "←", "right": "→",
    "slash": "/", "underscore": "_",
}

# Joiner between modifier and key. mac concatenates (⌃B); others use '+'.
_JOIN = "" if IS_MAC else "+"


def fmt_key(combo: str) -> str:
    """``"ctrl+b"`` → ``"⌃B"`` (mac) / ``"Ctrl+B"`` (Win/Linux).

    Unknown single-char keys are upper-cased (``"b"`` → ``"B"``);
    multi-char names fall back to the original token unchanged.
    """
    parts = [p.strip() for p in combo.lower().split("+") if p.strip()]
    if not parts:
        return combo
    mods, key = parts[:-1], parts[-1]
    key_disp = _KEY.get(key) or (key.upper() if len(key) == 1 else key)
    mod_disp = [_MOD.get(m, m) for m in mods]
    if not mod_disp:
        return key_disp
    return _JOIN.join(mod_disp) + _JOIN + key_disp


def fmt_keys(*combos: str, sep: str = " / ") -> str:
    """Join multiple combos: ``fmt_keys("ctrl+j", "ctrl+enter")`` →
    ``"Ctrl+J / Ctrl+Enter"`` or ``"⌃J / ⌃⏎"``."""
    return sep.join(fmt_key(c) for c in combos)


# Convenience constants for f-string templates.
CTRL  = _MOD["ctrl"]
SHIFT = _MOD["shift"]
ALT   = _MOD["alt"]
