# Trading Bot AI Coding Conventions

This document provides essential guidance for AI agents working on this trading bot codebase.

## Architecture Overview

The system is a **unified trading platform** combining a Python microservices backend (`trading-bot/`) with a React/Vite institutional-grade frontend (`trading-bot-ai-studio/`). The Python backend is the single source of truth for all trading state; the React frontend is the single UI.

### Workspace Structure

| Folder | Role |
|--------|------|
| `trading-bot/` | **Primary repo.** All backend code (FastAPI API, strategy engine, microservices), database, config, docker-compose, tests. |
| `trading-bot-ai-studio/` | **Frontend source only.** React/Vite app built into static files and served by nginx. Its `server/` (Express backend) is **retired** — all API calls route to `trading-bot/src/api/`. |

### Backend (Python)

- **Strategy Engine (`src/main.py`)**: Orchestrates the trading strategy. Loads configuration (`src/config.py`), connects to exchanges (`src/exchange.py`), executes strategy logic (`src/strategy.py`), stores data (`src/database.py`), communicates via NATS (`src/messaging.py`).

- **FastAPI API Server (`src/api/`)**: Unified gateway (port 8000) with REST + WebSocket endpoints for all frontend communication:
  - Routes: `agents`, `auth`, `backtest`, `data`, `intelligence`, `market`, `notifications`, `portfolio`, `presets`, `risk`, `signals`, `strategy`, `system`, `vault`
  - Middleware: API key auth, CORS, rate limiting, error handling
  - WebSocket: `/ws` for real-time updates (positions, fills, alarms, agents, market data)
  - Prometheus metrics at `/metrics`

- **FastAPI Microservices (`src/services/`)**:
  - `execution.py` — Order execution, PaperBroker simulation, execution reports (port 8080)
  - `feed.py` — Live ticker and order book data from exchanges via NATS (port 8081)
  - `reporter.py` — Performance metrics aggregation and summary reports (port 8083)
  - `risk.py` — Risk metrics, circuit breaker status, crisis mode (port 8084)
  - `replay.py` — Historical data streaming from Parquet files for backtesting (port 8085)
  - `signal_service.py` — TradingView webhook ingestion, signal scoring (port 8086 via `src/signal_engine/main.py`)
  - `llm_proxy.py` — OpenAI-compatible LLM proxy to Copilot/Gemini (port 8087)
  - `agent_orchestrator.py` — AI agent lifecycle management, OODA loop (port 8088)

- **Security (`src/security/`)**: Credential vault (AES-256-GCM at rest), mode guard for live/paper switching.

- **Risk (`src/risk/`)**: Portfolio-level risk manager, per-agent risk controls, correlation limits.

- **Backtesting (`src/backtest/`)**: Walk-forward optimizer, Monte Carlo simulation.

- **Notifications (`src/notifications/`)**: Discord webhook integration, alert escalation (INFO → WARNING → CRITICAL → AUTO_SHUTDOWN).

### Frontend (TypeScript/React)

- **Location**: `trading-bot-ai-studio/`
- **Stack**: React 19 + Vite 6 + Tailwind v4
- **Key tabs**: Market, Strategy Builder, Backtest, Signals, Agents, Presets, Journal, Portfolio, Data, Settings
- **API communication**: All REST calls route to `/api/*` (nginx-proxied to FastAPI). WebSocket at `/ws`.
- **Note**: The Express backend (`server/`) is retired. Do not add features there.

## Key Files

- `src/main.py`: Entry point of the Python strategy engine.
- `src/strategy.py`: Core trading logic (regime detection, confidence scoring, ladders, dual stops).
- `src/api/main.py`: FastAPI unified API server — mounts all routers, middleware, WebSocket.
- `src/api/routes/`: REST endpoint modules (agents, backtest, market, risk, signals, strategy, vault, etc.).
- `src/api/ws.py`: WebSocket manager with NATS bridge for real-time UI updates.
- `src/services/`: Python FastAPI microservices for execution, feed, risk, reporting, replay, signals, LLM proxy, agent orchestrator.
- `src/security/credential_vault.py`: AES-256-GCM credential encryption/decryption.
- `src/risk/portfolio_risk.py`: Portfolio-level risk with correlation and concentration limits.
- `src/services/agent_orchestrator.py`: AI agent lifecycle (CREATE → BACKTEST → PAPER → LIVE → RETIRE).
- `config/strategy.yaml`: Main configuration file (Pydantic-validated, hot-reloadable).
- `docker-compose.yml`: Full-stack orchestration (13+ services).
- `docker-compose.vps.yml`: VPS override for latency-sensitive deployment.
- `tools/backtest.py`: Historical backtesting engine.

## Developer Workflow

### Running the Bot

1.  **Activate the virtual environment**:
    ```bash
    source venv/bin/activate
    ```
2.  **Run the main application**:
    ```bash
    python src/main.py
    ```
3.  **Run the React dashboard** (from `trading-bot-ai-studio/`):
    ```bash
    npm install && npm run dev
    ```
    Visit `http://localhost:5173`.

### Testing

- **Unit Tests**: `pytest tests/` (60+ test files covering strategy, risk, agents, vault, API, etc.)
- **Integration Tests**: `test_integration.py`
- **Frontend E2E**: `npm run test:e2e` (Playwright, from `trading-bot-ai-studio/`)
- **Backtesting**:
  ```bash
  python tools/backtest.py --symbol BTCUSDT --start 2023-01-01 --end 2024-01-01
  ```

### Docker

The application is fully containerized. To run all services:

```bash
APP_MODE=paper docker compose up --build
```

This starts:
- **Infrastructure**: PostgreSQL (TimescaleDB), NATS messaging
- **Core Engine**: Strategy engine, Execution service (port 8080), Feed service (port 8081)
- **API & Frontend**: FastAPI API server (port 8000), React frontend via nginx (port 8080)
- **Risk & Reporting**: Risk state (port 8084), Reporter (port 8083)
- **AI & Signals**: Signal engine (port 8086), Copilot LLM proxy (port 8087), Agent orchestrator (port 8088)
- **Replay**: Replay service (port 8085)
- **Monitoring**: Prometheus (port 9090), Grafana (port 3000)
- **Operations**: DB backup (daily encrypted backups)

### Required Environment Variables

```bash
# Mandatory
POSTGRES_PASSWORD=<secure-password>
API_KEY=<api-key-for-fastapi-auth>

# Exchange (for live/testnet)
EXCHANGE_API_KEY=<key>
EXCHANGE_SECRET_KEY=<secret>

# Optional
APP_MODE=paper|live|replay
VAULT_MASTER_KEY=<32-byte-key-base64>
ALERT_WEBHOOK_URL=<discord/slack-webhook>
GEMINI_API_KEY=<for-ai-features>
CORS_ORIGINS=http://localhost:3000,http://localhost:8080
```

## Conventions

- **Configuration**: All configuration is managed through `config/strategy.yaml`. Do not hardcode values. The `src/config.py` module loads and validates via Pydantic.
- **Database**: PostgreSQL (TimescaleDB) is the primary store. SQLite is used for local dev/testing. Schema is managed in `src/database.py`.
- **Messaging**: NATS pub/sub for inter-service communication (`src/messaging.py`). Falls back to MockMessagingClient if NATS is unavailable.
- **Code Style**: PEP 8 with type hints. Validate with `ruff`, `black`, `mypy`.
- **Microservices**: Single-purpose FastAPI apps managed via `docker-compose.yml`. All expose `/health` endpoints.
- **Credentials**: Never in code or config files. Use the credential vault (`/api/vault/credentials`) or environment variables.
- **Frontend**: React components in `trading-bot-ai-studio/components/`. All data access is via REST (`/api/*`) and WebSocket (`/ws`). No localStorage persistence for trading state.
