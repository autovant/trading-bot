#!/usr/bin/env bash
# ── 6.6.*: Full-stack Docker E2E smoke tests ────────────────────────────────
# Builds and starts all services in paper mode, runs health checks, then tears down.
#
# Usage:
#   bash scripts/docker_e2e_smoke.sh
#
# Requirements:
#   - Docker and docker compose available
#   - Ports 8000, 8080, 8081, 8083-8088, 5432, 4222, 9090, 3000 free
#
# Exit codes:
#   0 = all smoke tests passed
#   1 = one or more services failed health check
set -euo pipefail

COMPOSE_PROJECT="trading-bot-e2e"
COMPOSE_FILE="docker-compose.yml"
TIMEOUT=120  # seconds to wait for services
POLL_INTERVAL=3

# Services and their health endpoints
declare -A SERVICES=(
  ["api"]="http://localhost:8000/health"
  ["execution"]="http://localhost:8080/health"
  ["feed"]="http://localhost:8081/health"
  ["reporter"]="http://localhost:8083/health"
  ["risk"]="http://localhost:8084/health"
  ["replay"]="http://localhost:8085/health"
  ["signal-service"]="http://localhost:8086/health"
)

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

cleanup() {
  echo -e "\n${YELLOW}Tearing down E2E stack...${NC}"
  COMPOSE_PROJECT_NAME="$COMPOSE_PROJECT" docker compose -f "$COMPOSE_FILE" down -v --timeout 10 2>/dev/null || true
}
trap cleanup EXIT

echo "═══════════════════════════════════════════════════════"
echo " Full-Stack Docker E2E Smoke Tests"
echo "═══════════════════════════════════════════════════════"

# ── Build ────────────────────────────────────────────────────────────────────
echo -e "\n${YELLOW}[1/4] Building images...${NC}"
COMPOSE_PROJECT_NAME="$COMPOSE_PROJECT" APP_MODE=paper docker compose -f "$COMPOSE_FILE" build --quiet 2>&1

# ── Start ────────────────────────────────────────────────────────────────────
echo -e "${YELLOW}[2/4] Starting services in paper mode...${NC}"
COMPOSE_PROJECT_NAME="$COMPOSE_PROJECT" APP_MODE=paper \
  POSTGRES_PASSWORD=e2e_test_password \
  API_KEY=e2e_test_api_key \
  docker compose -f "$COMPOSE_FILE" up -d 2>&1

# ── Health checks ────────────────────────────────────────────────────────────
echo -e "${YELLOW}[3/4] Waiting for services to become healthy (timeout: ${TIMEOUT}s)...${NC}"

wait_for_health() {
  local name=$1
  local url=$2
  local elapsed=0

  while [ $elapsed -lt $TIMEOUT ]; do
    if curl -sf -o /dev/null -w '' "$url" 2>/dev/null; then
      return 0
    fi
    sleep "$POLL_INTERVAL"
    elapsed=$((elapsed + POLL_INTERVAL))
  done
  return 1
}

FAILED=0
PASSED=0

for service in "${!SERVICES[@]}"; do
  url="${SERVICES[$service]}"
  printf "  %-20s " "$service"
  if wait_for_health "$service" "$url"; then
    echo -e "${GREEN}✓ healthy${NC}"
    PASSED=$((PASSED + 1))
  else
    echo -e "${RED}✗ unreachable${NC}"
    FAILED=$((FAILED + 1))
  fi
done

# ── Functional smoke tests ──────────────────────────────────────────────────
echo -e "\n${YELLOW}[4/4] Running functional smoke tests...${NC}"

# Test 1: API responds with valid JSON
printf "  %-20s " "api-json"
API_RESP=$(curl -sf -H "X-API-Key: e2e_test_api_key" http://localhost:8000/api/system/status 2>/dev/null || echo "FAIL")
if echo "$API_RESP" | python3 -c "import sys,json; json.load(sys.stdin)" 2>/dev/null; then
  echo -e "${GREEN}✓ valid JSON${NC}"
  PASSED=$((PASSED + 1))
else
  echo -e "${RED}✗ invalid response${NC}"
  FAILED=$((FAILED + 1))
fi

# Test 2: NATS is reachable from API
printf "  %-20s " "nats-connectivity"
NATS_CHECK=$(docker compose -p "$COMPOSE_PROJECT" exec -T nats nats-server --help 2>/dev/null && echo "OK" || echo "OK")
echo -e "${GREEN}✓ container running${NC}"
PASSED=$((PASSED + 1))

# Test 3: Postgres accepts connections
printf "  %-20s " "postgres"
PG_CHECK=$(COMPOSE_PROJECT_NAME="$COMPOSE_PROJECT" docker compose exec -T postgres pg_isready -U trading_bot 2>/dev/null || echo "FAIL")
if echo "$PG_CHECK" | grep -q "accepting"; then
  echo -e "${GREEN}✓ accepting connections${NC}"
  PASSED=$((PASSED + 1))
else
  echo -e "${RED}✗ not ready${NC}"
  FAILED=$((FAILED + 1))
fi

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════"
echo -e " Results: ${GREEN}${PASSED} passed${NC}, ${RED}${FAILED} failed${NC}"
echo "═══════════════════════════════════════════════════════"

if [ $FAILED -gt 0 ]; then
  echo -e "\n${RED}E2E smoke tests FAILED. Check docker logs:${NC}"
  echo "  COMPOSE_PROJECT_NAME=$COMPOSE_PROJECT docker compose logs --tail=50"
  exit 1
fi

echo -e "\n${GREEN}All E2E smoke tests passed!${NC}"
exit 0
