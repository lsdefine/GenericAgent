#!/usr/bin/env bash
# bridge-log-verify.sh — Verify bridge ring buffer logging works correctly.
# Run with bridge already started from worktree:
#   cd .claude/worktrees/frontend-react && bash frontends/desktop/tests/bridge-log-verify.sh
#
# Exit codes: 0 = PASS, 1 = FAIL

BRIDGE="http://127.0.0.1:14168"
PASS=0
FAIL=0

pass() { echo "  ✓ $1"; PASS=$((PASS + 1)); }
fail() { echo "  ✗ $1"; FAIL=$((FAIL + 1)); }

echo "=== Bridge Log Verify ==="

# 1. Check bridge is online
echo ""
echo "[1] Bridge connectivity"
if curl -sf "$BRIDGE/status" >/dev/null 2>&1; then
  pass "Bridge is online"
else
  fail "Bridge not reachable at $BRIDGE"
  echo "RESULT: FAIL ($FAIL failures)"
  exit 1
fi

# 2. Fetch initial logs
echo ""
echo "[2] Initial log content"
LOGS=$(curl -sf "$BRIDGE/services/logs?id=__bridge__&tail=200")
LINE_COUNT=$(echo "$LOGS" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('lines',[])))")

if [ "$LINE_COUNT" -ge 1 ]; then
  pass "Log has $LINE_COUNT lines (>= 1)"
else
  fail "Log is empty"
fi

# Check startup banner exists
echo "$LOGS" | python3 -c "
import sys, json
lines = json.load(sys.stdin).get('lines', [])
has_banner = any('GenericAgent' in l or 'bridge' in l.lower() for l in lines)
sys.exit(0 if has_banner else 1)
" && pass "Startup banner present" || fail "No startup banner found"

# Check timestamp format [HH:MM:SS]
echo "$LOGS" | python3 -c "
import sys, json, re
lines = json.load(sys.stdin).get('lines', [])
has_ts = any(re.match(r'^\[\d{2}:\d{2}:\d{2}\]', l) for l in lines)
sys.exit(0 if has_ts else 1)
" && pass "Timestamp format [HH:MM:SS] present" || fail "No timestamped lines"

# 3. Trigger a conversation turn
echo ""
echo "[3] Trigger session event"
NEW_RESP=$(curl -sf -X POST "$BRIDGE/session/new" -H "Content-Type: application/json" -d '{}')
SID=$(echo "$NEW_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('session',{}).get('id',''))")

if [ -z "$SID" ]; then
  fail "Could not create session"
else
  pass "Created session $SID"
  # Send a minimal prompt to trigger turn started/complete
  curl -sf -X POST "$BRIDGE/session/$SID/prompt" \
    -H "Content-Type: application/json" \
    -d '{"message":"test","images":[],"files":[]}' >/dev/null 2>&1 || true
  pass "Sent test prompt"

  # Wait for turn to complete
  sleep 5

  # 4. Check logs now contain [session] lines
  echo ""
  echo "[4] Session event in log"
  LOGS2=$(curl -sf "$BRIDGE/services/logs?id=__bridge__&tail=200")
  echo "$LOGS2" | python3 -c "
import sys, json
lines = json.load(sys.stdin).get('lines', [])
has_session = any('[session]' in l for l in lines)
sys.exit(0 if has_session else 1)
" && pass "[session] event recorded in ring buffer" || fail "No [session] event in log after conversation"

  # Show session lines for debugging
  echo ""
  echo "  Session-related log lines:"
  echo "$LOGS2" | python3 -c "
import sys, json
lines = json.load(sys.stdin).get('lines', [])
for l in lines:
    if '[session]' in l:
        print(f'    {l}')
"

  # Cleanup: delete test session
  curl -sf -X DELETE "$BRIDGE/session/$SID" >/dev/null 2>&1 || true
fi

# 5. Buffer size check
echo ""
echo "[5] Buffer size limit"
LOGS3=$(curl -sf "$BRIDGE/services/logs?id=__bridge__&tail=2000")
TOTAL=$(echo "$LOGS3" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('lines',[])))")
if [ "$TOTAL" -le 500 ]; then
  pass "Buffer size $TOTAL <= 500 limit"
else
  fail "Buffer size $TOTAL exceeds 500 limit"
fi

# Summary
echo ""
echo "=== Results ==="
echo "  PASS: $PASS"
echo "  FAIL: $FAIL"

if [ "$FAIL" -gt 0 ]; then
  echo "RESULT: FAIL"
  exit 1
else
  echo "RESULT: PASS"
  exit 0
fi
