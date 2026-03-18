# Trading Bot AI Coding Conventions

This document provides essential guidance for AI agents working on this trading bot codebase. Rely on these instructions first; only grep or browse the codebase when specific details (e.g. a file path or symbol name) are not covered here.

## Repository Summary

A **unified algorithmic trading platform**: Python microservices backend (FastAPI, strategy engine, risk, execution) + React/Vite institutional-grade frontend. Supports paper, testnet, and live trading modes. **Python ≥ 3.11** is required.

## Workspace Layout

| Path | Role |
|------|------|
| `src/` | All Python backend source code |
| `src/api/` | FastAPI unified API server (port 8000) |
| `src/api/routes/` | REST endpoint modules (agents, backtest, market, risk, signals, strategy, vault, …) |
| `src/api/ws.py` | WebSocket manager with NATS bridge |
| `src/services/` | FastAPI microservices: execution (8080), feed (8081), reporter (8083), risk (8084), replay (8085), signal_service (8086), llm_proxy (8087), agent_orchestrator (8088) |
| `src/strategy.py` | Core trading logic: regime detection, confidence scoring, ladders, dual stops |
| `src/security/` | Credential vault (AES-256-GCM at rest), mode guard |
| `src/risk/` | Portfolio-level risk manager, correlation limits |
| `src/backtest/` | Walk-forward optimizer, Monte Carlo simulation |
| `src/notifications/` | Discord webhook, alert escalation (INFO→WARNING→CRITICAL→AUTO_SHUTDOWN) |
| `config/strategy.yaml` | Main Pydantic-validated config (hot-reloadable) |
| `tests/` | 60+ pytest unit/integration test files |
| `tools/` | CLI utilities: `backtest.py`, `production_readiness_check.py` |
| `scripts/` | Helper scripts, including `check_migrations.py` |
| `trading-bot-ai-studio/` | React 19 + Vite 6 + Tailwind v4 frontend (built to static files) |
| `docker-compose.yml` | Full-stack orchestration (13+ services) |
| `alembic/` | Database migration scripts |
| `pyproject.toml` | Ruff + pytest configuration |
| `pytest.ini` | Pytest settings (asyncio_mode=auto, coverage ≥ 40%) |
| `mypy.ini` | Mypy settings |
| `.pre-commit-config.yaml` | Pre-commit hooks: ruff, ruff-format, mypy |

**Key files**: `src/main.py` (strategy engine entry point), `src/config.py` (config loader), `src/exchange.py` (exchange connector), `src/database.py` (schema), `src/messaging.py` (NATS, falls back to MockMessagingClient), `src/api/main.py` (API server entry point), `src/security/credential_vault.py`, `src/risk/portfolio_risk.py`, `src/services/agent_orchestrator.py`.

## Build & Validation — Exact Command Sequences

Always run these commands from the **repository root** with an active virtual environment.

### 1. Bootstrap (one-time)

```bash
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 2. Lint (must pass before every commit)

```bash
python -m ruff check .            # style + import checks
python -m black --check .         # formatting check (use `python -m black .` to auto-fix)
```

Auto-fix shorthand: `python -m ruff check --fix . && python -m black .`

### 3. Type-check

```bash
mypy src
```

`mypy.ini` sets `ignore_missing_imports = True`; stubs for `requests`, `PyYAML`, and `pydantic` are included via pre-commit.

### 4. Run tests

```bash
pytest tests/ -v
```

- **asyncio_mode = auto** — no need to mark async tests manually.
- Coverage minimum is **40%** (enforced by `--cov-fail-under=40` in `pytest.ini`). HTML report is written to `htmlcov/`.
- Slow / exchange tests are skipped by default; run with `-m "not testnet"` to be explicit.

### 5. Database migration check

```bash
python scripts/check_migrations.py
```

Always run after modifying `src/database.py` or adding Alembic migrations. This is enforced by CI.

### 6. Config validation

```bash
make validate-config
```

This runs a YAML syntax check across `config/strategy.yaml`, `docker-compose.yml`, and `prometheus.yml`.

### 7. Full pre-commit check (mirrors CI)

```bash
python -m ruff check . && python -m black --check . && pytest tests/ -v && python scripts/check_migrations.py
```

## CI Workflows (`.github/workflows/`)

| Workflow | File | Jobs |
|----------|------|------|
| CI | `ci.yml` | lint (`ruff`, `black`), typecheck (`mypy src`), test (`pytest`), migration-check, build (Docker), scan (Trivy) |
| Production Readiness | `production-readiness.yml` | `python tools/production_readiness_check.py --mode paper --strict` |

All jobs target **Python 3.11** and install from `requirements.txt`. PRs must pass all CI jobs before merging.

## Running Locally

```bash
# Backend strategy engine
source venv/bin/activate
python src/main.py

# Full stack (all services)
APP_MODE=paper docker compose up --build

# Frontend only (dev server at http://localhost:5173)
cd trading-bot-ai-studio && npm install && npm run dev
```

## Required Environment Variables

```bash
POSTGRES_PASSWORD=<secure>        # mandatory
API_KEY=<api-key>                 # mandatory (FastAPI auth)
EXCHANGE_API_KEY=<key>            # for live/testnet
EXCHANGE_SECRET_KEY=<secret>
APP_MODE=paper|live|replay        # default: paper
VAULT_MASTER_KEY=<32-byte-base64>
ALERT_WEBHOOK_URL=<discord/slack>
GEMINI_API_KEY=<for-ai-features>
CORS_ORIGINS=http://localhost:3000,http://localhost:8080
```

## Conventions

- **Config**: All values in `config/strategy.yaml`. Never hardcode. `src/config.py` loads via Pydantic.
- **Database**: PostgreSQL/TimescaleDB in production; SQLite for local/testing. Schema in `src/database.py`. Migrations in `alembic/`.
- **Messaging**: NATS pub/sub (`src/messaging.py`). Falls back to `MockMessagingClient` when NATS is unavailable.
- **Code style**: PEP 8, type hints, `ruff` + `black` + `mypy`. Line length 88 (Black default).
- **Microservices**: Single-purpose FastAPI apps, each exposes `/health`. Managed via `docker-compose.yml`.
- **Credentials**: Never in code or config files. Use the credential vault (`/api/vault/credentials`) or environment variables.
- **Frontend**: Components in `trading-bot-ai-studio/src/`. All data access via REST (`/api/*`) and WebSocket (`/ws`). No localStorage for trading state. The Express `server/` directory is **retired** — do not add features there.
- **Security**: Do not expose secrets in logs or API responses. Live-mode changes require the mode guard in `src/security/`.
