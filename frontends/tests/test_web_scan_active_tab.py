"""web_scan should follow the browser's real active tab, not the last operated one."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
BRIDGE = (ROOT / "assets" / "tmwd_cdp_bridge" / "background.js").read_text(encoding="utf-8")
DRIVER = (ROOT / "TMWebDriver.py").read_text(encoding="utf-8")
GA = (ROOT / "ga.py").read_text(encoding="utf-8")


def test_bridge_pushes_active_and_listens_for_tab_activation():
    assert "active: !!t.active" in BRIDGE
    assert "chrome.tabs.onActivated.addListener" in BRIDGE
    assert "chrome.windows.onFocusChanged.addListener" in BRIDGE


def test_driver_promotes_active_tab_to_default_session():
    assert "if tab.get('active'):" in DRIVER
    assert "driver.default_session_id = session_id" in DRIVER
    assert "'active': bool(tab.get('active'))" in DRIVER


def test_web_scan_marks_the_active_tab():
    assert "sess['active'] = str(sess.get('id')) == str(driver.default_session_id)" in GA
