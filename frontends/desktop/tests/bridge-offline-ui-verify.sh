#!/usr/bin/env bash
# Bridge offline UI graceful degradation verification
# Tests that StatusPanel/ChannelList show stale data + banner instead of clearing,
# and that the full-screen blocking overlay is removed.
#
# Usage: bash tests/bridge-offline-ui-verify.sh

SRC="$(cd "$(dirname "$0")/../src" && pwd)"
BRIDGE="http://localhost:5800"
PASS=0
FAIL=0

pass() { PASS=$((PASS + 1)); echo "  PASS: $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL: $1"; }

echo "=== Bridge Offline UI Graceful Degradation ==="
echo ""

# --- Check 1: No full-screen blocking overlay in App ---
echo "[1] App.tsx does NOT render ConnectingOverlay"
if grep -q "ConnectingOverlay" "$SRC/App.tsx"; then
  fail "App.tsx still imports/renders ConnectingOverlay"
else
  pass "ConnectingOverlay removed from App.tsx"
fi

# --- Check 2: StatusPanel has offline banner ---
echo "[2] StatusPanel has offline-banner"
if grep -q "ga-offline-banner" "$SRC/components/services/StatusPanel.tsx"; then
  pass "StatusPanel contains ga-offline-banner"
else
  fail "StatusPanel missing ga-offline-banner"
fi

# --- Check 3: ChannelList has offline banner ---
echo "[3] ChannelList has offline-banner"
if grep -q "ga-offline-banner" "$SRC/components/services/ChannelList.tsx"; then
  pass "ChannelList contains ga-offline-banner"
else
  fail "ChannelList missing ga-offline-banner"
fi

# --- Check 4: i18n zh has bridge.staleData ---
echo "[4] i18n zh has bridge.staleData"
if grep -q "bridge.staleData" "$SRC/i18n/zh.ts"; then
  pass "zh locale has bridge.staleData"
else
  fail "zh locale missing bridge.staleData"
fi

# --- Check 5: i18n en has bridge.staleData ---
echo "[5] i18n en has bridge.staleData"
if grep -q "bridge.staleData" "$SRC/i18n/en.ts"; then
  pass "en locale has bridge.staleData"
else
  fail "en locale missing bridge.staleData"
fi

# --- Check 6: CSS has .ga-offline-banner ---
echo "[6] CSS has .ga-offline-banner"
if grep -q "ga-offline-banner" "$SRC/components/services/services.css"; then
  pass "CSS has .ga-offline-banner rule"
else
  fail "CSS missing .ga-offline-banner rule"
fi

# --- Check 7: StatusPanel buttons disabled when offline ---
echo "[7] StatusPanel buttons disabled when offline"
if grep -q "disabled={isOffline}" "$SRC/components/services/StatusPanel.tsx"; then
  pass "Action buttons have disabled={isOffline}"
else
  fail "Action buttons missing disabled prop"
fi

# --- Check 8: ChannelList buttons disabled when offline ---
echo "[8] ChannelList buttons disabled when offline"
if grep -q "disabled={isOffline}" "$SRC/components/services/ChannelList.tsx"; then
  pass "Channel toggle buttons have disabled={isOffline}"
else
  fail "Channel toggle buttons missing disabled prop"
fi

# --- Check 9: Cold-start spinner is data-gated, not connection-gated ---
echo "[9] Cold-start spinner gated by data absence"
if grep -q "isOffline && services.length === 0" "$SRC/components/services/StatusPanel.tsx"; then
  pass "StatusPanel cold-start uses data check"
else
  fail "StatusPanel cold-start missing data check"
fi

if grep -q "isOffline && channels.length === 0" "$SRC/components/services/ChannelList.tsx"; then
  pass "ChannelList cold-start uses data check"
else
  fail "ChannelList cold-start missing data check"
fi

# --- Check 10: Bridge connectivity (informational) ---
echo "[10] Bridge health (informational)"
if curl -s --max-time 2 "$BRIDGE/health" > /dev/null 2>&1; then
  echo "  INFO: Bridge is running — manually test: exit bridge -> banner appears, data stays"
else
  echo "  INFO: Bridge not running — panels will show cold-start spinner (no stale data)"
fi

echo ""
echo "=== Results: $PASS passed, $FAIL failed (of $((PASS + FAIL))) ==="
if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
