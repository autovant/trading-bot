# Microservices Architecture

The unified trading platform uses a microservices architecture with NATS messaging for inter-service communication. The Python FastAPI backend is the single source of truth; the React frontend (`trading-bot-ai-studio/`) is the single UI.

## Services Overview

### 1. API Server (Unified Gateway)
- **Port**: 8000
- **Language**: Python (FastAPI)
- **Purpose**: Unified REST + WebSocket gateway for the React frontend and external integrations
- **Endpoints**: `/api/agents`, `/api/backtests`, `/api/market`, `/api/strategies`, `/api/risk`, `/api/signals`, `/api/vault`, `/api/system`, `/api/data`, `/api/presets`
- **WebSocket**: `/ws` — real-time updates for positions, fills, alarms, agents, market data (NATS-bridged)
- **Middleware**: API key auth (`X-API-Key`), CORS, rate limiting, error handling
- **Metrics**: Prometheus at `/metrics`
- **Docker**: `api-server` service (`uvicorn src.api.main:app`)

### 2. Strategy Engine
- **Language**: Python
- **Purpose**: Core trading logic — regime detection, setup analysis, signal generation, confidence scoring, position sizing, ladder entries, dual stops
- **Communication**: Subscribes to market data from NATS, publishes order intents
- **Docker**: `strategy-engine` service (`python3 -m src.main`)

### 3. Execution Service
- **Port**: 8080
- **Language**: Python (FastAPI)
- **Purpose**: Order execution, PaperBroker simulation, fill callbacks, execution reports
- **Communication**: Subscribes to order requests via NATS, publishes execution reports
- **Docker**: `execution` service (`uvicorn src.services.execution:app`)

### 4. Feed Service (Feature Engine)
- **Port**: 8081
- **Language**: Python (FastAPI)
- **Purpose**: Market data ingestion — live ticker, order book, candle data from exchanges
- **Communication**: Publishes market data to NATS
- **Docker**: `feature-engine` service (`uvicorn src.services.feed:app`)

### 5. Reporter Service
- **Port**: 8083
- **Language**: Python (FastAPI)
- **Purpose**: Performance metrics aggregation, summary reports, PnL rollups
- **Communication**: Subscribes to performance metrics, publishes reports via NATS
- **Docker**: `reporter` service (`uvicorn src.services.reporter:app`)

### 6. Risk State Service
- **Port**: 8084
- **Language**: Python (FastAPI)
- **Purpose**: Risk monitoring, crisis mode, circuit breaker, drawdown tracking, alarm escalation
- **Communication**: Subscribes to risk management topics, publishes risk state via NATS
- **Docker**: `risk-state` service (`uvicorn src.services.risk:app`)

### 7. Replay Service
- **Port**: 8085
- **Language**: Python (FastAPI)
- **Purpose**: Streams historical data over NATS for deterministic paper trading and backtesting
- **Communication**: Publishes market data to NATS, listens for replay.control commands
- **HTTP**: `/status` for live state and `/control` (pause/resume)
- **Docker**: `replay-service` (`uvicorn src.services.replay:app`)

### 8. Signal Engine
- **Port**: 8086
- **Language**: Python (FastAPI)
- **Purpose**: Signal scoring, TradingView webhook ingestion, alert routing
- **Communication**: Publishes processed signals to NATS
- **Docker**: `signal-engine` service (`uvicorn src.signal_engine.main:app`)

### 9. Copilot LLM Proxy
- **Port**: 8087
- **Language**: Python (FastAPI)
- **Purpose**: OpenAI-compatible `/v1/chat/completions` proxy. Routes AI requests through GitHub Copilot (primary) or Gemini API (fallback). Implements token-bucket rate limiting (30 RPM) and response caching (5min TTL).
- **Docker**: `copilot-proxy` service (separate `Dockerfile.proxy`)

### 10. Agent Orchestrator
- **Port**: 8088
- **Language**: Python (FastAPI)
- **Purpose**: AI agent lifecycle management (CREATE → BACKTEST → PAPER → LIVE → RETIRE). Runs OODA decision loop per agent on configurable intervals. Enforces portfolio-level risk constraints.
- **Communication**: Subscribes to market data + execution reports via NATS. Publishes agent status.
- **Docker**: `agent-orchestrator` service (`uvicorn src.services.agent_orchestrator:app`)

### 11. React Frontend
- **Port**: 8080 (nginx)
- **Language**: TypeScript (React 19 + Vite 6 + Tailwind v4)
- **Purpose**: Institutional-grade trading workstation UI — dashboard, strategy builder, backtest playback, AI assistant, agent management, order book, signals, journal, portfolio, settings
- **Communication**: REST calls to `/api/*` (proxied to API server), WebSocket at `/ws`
- **Build**: `trading-bot-ai-studio/` — multi-stage Docker build (node → nginx static)
- **Docker**: `frontend` service

### 12. Infrastructure Services

| Service | Image | Port | Purpose |
|---------|-------|------|---------|
| PostgreSQL (TimescaleDB) | `timescale/timescaledb-ha:pg14-latest` | 5432 | Primary data store — orders, trades, positions, agents, PnL, config versions |
| NATS | `nats:latest` | 4222, 8222 | Message bus for all inter-service communication |
| Prometheus | `prom/prometheus:v2.37.0` | 9090 | Metrics collection from all services |
| Grafana | `grafana/grafana:8.5.2` | 3000 | Dashboards and alerting |
| DB Backup | `postgres:15-alpine` | — | Daily encrypted `pg_dump` with 7-day/4-week retention |

## NATS Messaging

### Subjects
- `market.data` — Market data updates (ticker, candles)
- `market.orderbook` — Order book snapshots
- `trading.orders` — Order intents (strategy → execution)
- `trading.executions` — Execution reports (fills, cancels)
- `risk.management` — Risk commands (kill switch, limit updates)
- `risk.state` — Risk state changes (ON/GUARDED/RISK_OFF/CRISIS)
- `agent.commands` — Agent lifecycle commands
- `agent.status` — Agent state transitions
- `performance.metrics` — Performance data for reporter
- `reports.performance` — Published summary reports
- `config.reload` — Broadcast configuration reload notification
- `backtest.jobs` — Backtest job submission
- `backtest.results` — Backtest results

### Message Format
All messages are JSON-encoded with a `type` field indicating the message type.

## Docker Deployment

### Full Stack (Paper Mode)
```bash
APP_MODE=paper docker compose up --build
```

### VPS Deployment (Latency-Sensitive Services Only)
```bash
docker compose -f docker-compose.yml -f docker-compose.vps.yml up -d
```
Deploys only strategy-engine, execution, feed, NATS (leaf node), and PostgreSQL on a VPS co-located with exchange servers.

## Health Checks

All FastAPI services expose `/health` endpoints:
- API Server: `http://localhost:8000/health`
- Execution: `http://localhost:8080/health`
- Feed: `http://localhost:8081/health`
- Reporter: `http://localhost:8083/health`
- Risk: `http://localhost:8084/health`
- Replay: `http://localhost:8085/health`
- Signal Engine: `http://localhost:8086/health`
- LLM Proxy: `http://localhost:8087/health`
- Agent Orchestrator: `http://localhost:8088/health`
- NATS: `http://localhost:8222`

## Configuration

Services are configured through:
- **Environment variables** (see `docker-compose.yml` for all vars)
- **Configuration files** (`config/strategy.yaml` — Pydantic-validated, hot-reloadable)
- **NATS messaging** (`config.reload` subject for dynamic updates)
- **Credential vault** (`/api/vault/credentials` — AES-256-GCM encrypted at rest)
