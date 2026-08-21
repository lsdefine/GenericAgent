#!/usr/bin/env bash
# Bridge restart button verification
# Tests that restart button appears in offline state when Tauri env is detected

SRC="$(cd "$(dirname "$0")/../src" && pwd)"
PASS=0
FAIL=0

pass() { PASS=$((PASS + 1)); echo "  PASS: $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL: $1"; }

echo "=== Bridge Restart Button Verification ==="
echo ""

# --- Check 1: tauri.ts utility exists ---
echo "[1] utils/tauri.ts exists with isTauri + invokeStartBridge"
if grep -q "isTauri" "$SRC/utils/tauri.ts" && grep -q "invokeStartBridge" "$SRC/utils/tauri.ts"; then
  pass "tauri.ts has both exports"
else
  fail "tauri.ts missing expected exports"
fi

# --- Check 2: StatusPanel imports tauri utils ---
echo "[2] StatusPanel imports tauri utils"
if grep -q "isTauri.*invokeStartBridge" "$SRC/components/services/StatusPanel.tsx"; then
  pass "StatusPanel imports isTauri + invokeStartBridge"
else
  fail "StatusPanel missing tauri imports"
fi

# --- Check 3: ChannelList imports tauri utils ---
echo "[3] ChannelList imports tauri utils"
if grep -q "isTauri.*invokeStartBridge" "$SRC/components/services/ChannelList.tsx"; then
  pass "ChannelList imports isTauri + invokeStartBridge"
else
  fail "ChannelList missing tauri imports"
fi

# --- Check 4: StatusPanel has restart button gated by isTauri ---
echo "[4] StatusPanel restart button gated by isTauri()"
if grep -q "isTauri()" "$SRC/components/services/StatusPanel.tsx" && grep -q "handleRestartBridge" "$SRC/components/services/StatusPanel.tsx"; then
  pass "StatusPanel has isTauri-gated restart button"
else
  fail "StatusPanel missing isTauri-gated restart"
fi

# --- Check 5: ChannelList has restart button gated by isTauri ---
echo "[5] ChannelList restart button gated by isTauri()"
if grep -q "isTauri()" "$SRC/components/services/ChannelList.tsx" && grep -q "handleRestartBridge" "$SRC/components/services/ChannelList.tsx"; then
  pass "ChannelList has isTauri-gated restart button"
else
  fail "ChannelList missing isTauri-gated restart"
fi

# --- Check 6: Dev mode fallback (command hint when not Tauri) ---
echo "[6] Dev fallback shows command hint"
if grep -q "bridge.notRunningHint" "$SRC/components/services/StatusPanel.tsx"; then
  pass "StatusPanel has dev-mode command hint fallback"
else
  fail "StatusPanel missing dev-mode fallback"
fi

# --- Check 7: Error handling in restart handler ---
echo "[7] Error handling on invoke failure"
if grep -q "showError" "$SRC/components/services/StatusPanel.tsx" && grep -q "err.bridge" "$SRC/components/services/StatusPanel.tsx"; then
  pass "Restart failure shows error toast"
else
  fail "Missing error handling in restart"
fi

# --- Check 8: Offline banner also has restart button ---
echo "[8] Offline banner includes restart button"
if grep -A5 "ga-offline-banner" "$SRC/components/services/StatusPanel.tsx" | grep -q "handleRestartBridge"; then
  pass "Banner includes restart button"
else
  fail "Banner missing restart button"
fi

# --- Check 9: invokeStartBridge calls start_bridge command ---
echo "[9] invokeStartBridge invokes correct Tauri command"
if grep -q "'start_bridge'" "$SRC/utils/tauri.ts"; then
  pass "Calls invoke('start_bridge')"
else
  fail "Wrong Tauri command name"
fi

# --- Check 10: App.tsx has NO ConnectingOverlay ---
echo "[10] No full-screen blocking overlay"
if grep -q "ConnectingOverlay" "$SRC/App.tsx"; then
  fail "App.tsx still renders ConnectingOverlay"
else
  pass "ConnectingOverlay removed"
fi

echo ""
echo "=== Results: $PASS passed, $FAIL failed (of $((PASS + FAIL))) ==="
if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
