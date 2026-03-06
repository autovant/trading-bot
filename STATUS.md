# Unified Trading Platform — Status (2026-03-04)

## Current State

The platform has completed a full unification of the Python backend (`trading-bot/`) and the React frontend (`trading-bot-ai-studio/`). All 5 phases from the [unified platform plan](plans/unified-platform-plan.md) are implemented.

### What's Done

**Phase 1 — Foundation Merge** (Complete)
- FastAPI WebSocket endpoint (`/ws`) with NATS bridge, heartbeat, stale connection cleanup
- Python credential vault (AES-256-GCM at rest) with REST API
- All API route stubs wired: agents, backtest, data, market, presets, risk, signals, strategy, system, vault
- CORS, API key auth middleware, rate limiting, error handler
- Frontend containerized (nginx) and added to docker-compose
- Frontend rewired: all REST → FastAPI, all state → server-side (no localStorage)
- Integration tests validated

**Phase 2 — AI Agent Core** (Complete)
- Agent data model (Pydantic + DB tables: agents, agent_decisions, agent_performance)
- LLM proxy service (port 8087) with Copilot/Gemini routing, caching, rate limiting
- Agent orchestrator (port 8088) with OODA loop, lifecycle state machine, stage gates
- Portfolio risk manager (correlation, concentration, rate limit pooling)
- Agent UI (AgentManager + AgentDetail components)

**Phase 3 — Enhanced Backtesting** (Complete)
- Walk-forward optimizer (`src/backtest/walk_forward.py`)
- Monte Carlo simulation (`src/backtest/monte_carlo.py`)
- Strategy comparison endpoint with statistical significance testing

**Phase 4 — Production Hardening** (Complete)
- TradingView webhook ingestion with HMAC validation
- Signal service with auto-execution, scoring, history
- Discord webhook notifications with rich embeds
- Alert escalation (INFO → WARNING → CRITICAL → AUTO_SHUTDOWN)
- Remote kill switch via REST
- Encrypted daily database backups (7-day/4-week retention)

**Phase 5 — VPS Deployment** (Complete)
- `docker-compose.vps.yml` overlay for latency-sensitive services
- WireGuard VPN setup script
- Cold-start pre-warming script
- Latency benchmarking tool

### Service Inventory

| Service | Port | Status |
|---------|------|--------|
| API Server | 8000 | Running |
| Execution | 8080 | Running |
| Feed (Feature Engine) | 8081 | Running |
| Reporter | 8083 | Running |
| Risk State | 8084 | Running |
| Replay | 8085 | Running |
| Signal Engine | 8086 | Running |
| LLM Proxy | 8087 | Running |
| Agent Orchestrator | 8088 | Running |
| Frontend (nginx) | 8080 | Running |
| PostgreSQL | 5432 | Running |
| NATS | 4222 | Running |
| Prometheus | 9090 | Running |
| Grafana | 3000 | Running |

### Retired Components
- Streamlit dashboard (`dashboard/app.py`) — replaced by React frontend
- Express backend (`trading-bot-ai-studio/server/`) — replaced by FastAPI
- Go microservices — replaced by Python FastAPI services (Oct 2025)
- `frontend_v2/` — superseded by `trading-bot-ai-studio/`
- Ops API (`src/ops_api_service.py`) — merged into `src/api/main.py`

## Validation Commands

```bash
# Backend
python -m ruff check .
python -m black --check .
python -m mypy src
python -m pytest tests/

# Frontend (from trading-bot-ai-studio/)
npm run typecheck
npm run build
npm run test:e2e

# Docker
docker compose build
APP_MODE=paper docker compose up --build
```

## Key Documentation

| Doc | Purpose |
|-----|---------|
| [docs/UNIFIED_ARCHITECTURE.md](docs/UNIFIED_ARCHITECTURE.md) | Full architecture reference |
| [plans/unified-platform-plan.md](plans/unified-platform-plan.md) | Implementation plan with all epics |
| [SERVICES.md](SERVICES.md) | Service registry and ports |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Deployment guide |
| [STRATEGY.md](STRATEGY.md) | Trading strategy documentation |
