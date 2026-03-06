#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────
# Docker Compose Smoke Test
#
# Usage:  scripts/smoke_test.sh [--no-teardown]
#
# Starts all services via docker compose, waits for health, verifies
# API + frontend respond, then tears down (unless --no-teardown).
# ──────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
TEARDOWN=true

for arg in "$@"; do
  case "$arg" in
    --no-teardown) TEARDOWN=false ;;
  esac
done

cd "$PROJECT_DIR"

# ── Helpers ───────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

pass() { echo -e "  ${GREEN}✓${NC} $1"; }
fail() { echo -e "  ${RED}✗${NC} $1"; FAILURES=$((FAILURES + 1)); }
info() { echo -e "  ${YELLOW}…${NC} $1"; }

FAILURES=0

wait_for_url() {
  local url="$1"
  local label="$2"
  local max_wait="${3:-60}"
  local elapsed=0

  info "Waiting for $label ($url) ..."
  while ! curl -sf --max-time 3 "$url" > /dev/null 2>&1; do
    sleep 2
    elapsed=$((elapsed + 2))
    if [ "$elapsed" -ge "$max_wait" ]; then
      fail "$label did not respond within ${max_wait}s"
      return 1
    fi
  done
  pass "$label is up (${elapsed}s)"
  return 0
}

# ── Teardown on exit (unless --no-teardown) ───────────────────────────

cleanup() {
  if [ "$TEARDOWN" = true ]; then
    info "Tearing down containers ..."
    docker compose down --volumes --remove-orphans 2>/dev/null || true
  else
    info "Leaving containers running (--no-teardown)"
  fi
}
trap cleanup EXIT

# ── Start services ────────────────────────────────────────────────────

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║          Docker Compose Smoke Test                  ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

info "Building and starting services ..."
docker compose up -d --build 2>&1 | tail -5

echo ""
echo "── Service Health Checks ──"

# Core infrastructure
wait_for_url "http://localhost:5432" "PostgreSQL" 30 || true
# NATS monitoring
wait_for_url "http://localhost:8222" "NATS monitoring" 20

# API server (most important)
wait_for_url "http://localhost:8000/health" "API Server" 90

# Frontend
wait_for_url "http://localhost:8080" "Frontend (nginx)" 60

echo ""
echo "── API Endpoint Verification ──"

# Health
HEALTH=$(curl -sf http://localhost:8000/health 2>/dev/null)
if [ -n "$HEALTH" ]; then
  pass "GET /health → $HEALTH"
else
  fail "GET /health returned empty"
fi

# Account (GET, no auth needed)
ACCOUNT=$(curl -sf -o /dev/null -w "%{http_code}" http://localhost:8000/api/account 2>/dev/null)
if [ "$ACCOUNT" = "200" ]; then
  pass "GET /api/account → 200"
else
  fail "GET /api/account → $ACCOUNT (expected 200)"
fi

# Strategies
STRATEGIES=$(curl -sf -o /dev/null -w "%{http_code}" http://localhost:8000/api/strategies 2>/dev/null)
if [ "$STRATEGIES" = "200" ]; then
  pass "GET /api/strategies → 200"
else
  fail "GET /api/strategies → $STRATEGIES (expected 200)"
fi

# Backtests history
BT=$(curl -sf -o /dev/null -w "%{http_code}" http://localhost:8000/api/backtests/history 2>/dev/null)
if [ "$BT" = "200" ]; then
  pass "GET /api/backtests/history → 200"
else
  fail "GET /api/backtests/history → $BT (expected 200)"
fi

# Vault credentials (GET list)
VAULT=$(curl -sf -o /dev/null -w "%{http_code}" http://localhost:8000/api/vault/credentials 2>/dev/null)
if [ "$VAULT" = "200" ]; then
  pass "GET /api/vault/credentials → 200"
else
  fail "GET /api/vault/credentials → $VAULT (expected 200)"
fi

echo ""
echo "── Frontend Verification ──"

# Check that the frontend returns HTML
FRONTEND_CT=$(curl -sf -o /dev/null -w "%{content_type}" http://localhost:8080/ 2>/dev/null)
if echo "$FRONTEND_CT" | grep -qi "text/html"; then
  pass "Frontend serves HTML"
else
  fail "Frontend content-type: $FRONTEND_CT (expected text/html)"
fi

echo ""
echo "── Container Status ──"
docker compose ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null | head -20

echo ""
echo "══════════════════════════════════════════════════════"
if [ "$FAILURES" -eq 0 ]; then
  echo -e "${GREEN}All smoke tests passed.${NC}"
else
  echo -e "${RED}${FAILURES} check(s) failed.${NC}"
fi
echo "══════════════════════════════════════════════════════"

exit "$FAILURES"
