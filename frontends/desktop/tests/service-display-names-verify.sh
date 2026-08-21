#!/usr/bin/env bash
# Service display names verification
# Tests that StatusPanel uses product-friendly names with tooltips

SRC="$(cd "$(dirname "$0")/../src" && pwd)"
PASS=0
FAIL=0

pass() { PASS=$((PASS + 1)); echo "  PASS: $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL: $1"; }

echo "=== Service Display Names Verification ==="
echo ""

# --- Check 1: SERVICE_META mapping exists ---
echo "[1] SERVICE_META mapping in StatusPanel"
if grep -q "SERVICE_META" "$SRC/components/services/StatusPanel.tsx"; then
  pass "SERVICE_META defined"
else
  fail "SERVICE_META missing"
fi

# --- Check 2: Bridge mapped to proc.bridge ---
echo "[2] Bridge mapped to proc.bridge"
if grep -q "'__bridge__'.*'proc.bridge'" "$SRC/components/services/StatusPanel.tsx"; then
  pass "__bridge__ -> proc.bridge"
else
  fail "Bridge mapping missing"
fi

# --- Check 3: Conductor mapped ---
echo "[3] Conductor mapped to proc.conductor"
if grep -q "'frontends/conductor.py'.*'proc.conductor'" "$SRC/components/services/StatusPanel.tsx"; then
  pass "conductor -> proc.conductor"
else
  fail "Conductor mapping missing"
fi

# --- Check 4: Scheduler mapped ---
echo "[4] Scheduler mapped to proc.scheduler"
if grep -q "'reflect/scheduler.py'.*'proc.scheduler'" "$SRC/components/services/StatusPanel.tsx"; then
  pass "scheduler -> proc.scheduler"
else
  fail "Scheduler mapping missing"
fi

# --- Check 5: Tooltip used ---
echo "[5] Tooltip wraps service name"
if grep -q "Tooltip" "$SRC/components/services/StatusPanel.tsx" && grep -q "content={record.id}" "$SRC/components/services/StatusPanel.tsx"; then
  pass "Tooltip with record.id as content"
else
  fail "Tooltip missing or wrong content"
fi

# --- Check 6: i18n zh has proc.bridge ---
echo "[6] zh has proc.bridge"
if grep -q "'proc.bridge'" "$SRC/i18n/zh.ts"; then
  pass "proc.bridge in zh"
else
  fail "proc.bridge missing in zh"
fi

# --- Check 7: i18n en has proc.bridge ---
echo "[7] en has proc.bridge"
if grep -q "'proc.bridge'" "$SRC/i18n/en.ts"; then
  pass "proc.bridge in en"
else
  fail "proc.bridge missing in en"
fi

# --- Check 8: Column title uses svc.colName ---
echo "[8] Column title uses svc.colName"
if grep -q "svc.colName" "$SRC/components/services/StatusPanel.tsx"; then
  pass "Column title is svc.colName"
else
  fail "Column title still uses old key"
fi

# --- Check 9: i18n keys for svc.colName ---
echo "[9] svc.colName in both locales"
if grep -q "'svc.colName'" "$SRC/i18n/zh.ts" && grep -q "'svc.colName'" "$SRC/i18n/en.ts"; then
  pass "svc.colName in zh + en"
else
  fail "svc.colName missing"
fi

echo ""
echo "=== Results: $PASS passed, $FAIL failed (of $((PASS + FAIL))) ==="
if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
