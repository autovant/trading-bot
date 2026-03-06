# Unified Platform Implementation Plan

**Source**: [docs/UNIFIED_ARCHITECTURE.md](../docs/UNIFIED_ARCHITECTURE.md)  
**Created**: 2026-03-03  
**Status**: Active  

---

## Workspace Structure

Both workspace folders are required during the transition. Here's how they relate:

| Folder | Role | Long-term fate |
|--------|------|----------------|
| `trading-bot/` | **Primary repo.** All backend code (FastAPI API, strategy engine, microservices), database, config, docker-compose, tests. | Stays — this is the single repo going forward. |
| `trading-bot-ai-studio/` | **Frontend source only.** React/Vite app that gets built into static files and served by nginx. | Stays as a sub-build context. Its `server/` (Express backend) is **retired** — all API calls route to `trading-bot/src/api/`. |

### What lives where

- **Backend API, WebSocket, auth, vault, strategy engine** → `trading-bot/src/`
- **React components, hooks, services** → `trading-bot-ai-studio/`
- **Docker orchestration** → `trading-bot/docker-compose.yml` (references `../trading-bot-ai-studio` as build context for the `frontend` service)
- **Tests (backend)** → `trading-bot/tests/`
- **Tests (frontend e2e)** → `trading-bot-ai-studio/tests/`

### Why not merge into one folder?

The frontend is a separate build artifact (node/npm → static HTML/JS/CSS). Keeping it in its own folder:
1. Separates the Node.js toolchain (package.json, node_modules) from the Python toolchain (requirements.txt, venv)
2. Allows independent CI/CD pipelines for frontend and backend
3. The multi-stage Docker build (`trading-bot-ai-studio/Dockerfile`) produces a pure nginx image — no Node.js runtime in production

### What to ignore in `trading-bot-ai-studio/`

During the transition, these paths in the frontend repo are **dead code** being replaced by backend equivalents:

| Frontend path (retiring) | Replaced by (backend) |
|--------------------------|----------------------|
| `server/` (Express API) | `trading-bot/src/api/` |
| `services/secureStorage.ts` (browser RSA) | `trading-bot/src/security/credential_vault.py` |
| `services/strategyStorage.ts` (localStorage) | `trading-bot/src/api/routes/strategy.py` |
| `services/executionJournal.ts` (localStorage) | Backend WS events via `trading-bot/src/api/ws.py` |
| `services/fillLedger.ts` (localStorage) | `trading-bot/src/api/routes/market.py` (`/api/trades`) |
| `services/orderIdempotency.ts` (localStorage) | Server-side `order_intents` table |

Do **not** delete these yet — they're still imported by components until Epic 1.6 (Frontend API Rewiring) is complete.

---

## Overview

5 phases, 24 epics, ~85 subtasks. Each subtask is scoped to a single PR-sized unit of work. Dependencies are explicit — nothing starts until its prereqs are done.

---

## Phase 1: Foundation Merge

**Goal**: App B's React frontend talks to App A's FastAPI backend. Express backend retired. All state server-side.

### Epic 1.1 — FastAPI WebSocket Endpoint
**Files**: `src/api/ws.py` (new), `src/api/main.py` (edit)  
**Agent**: @backend-engineer  

| # | Subtask | Depends | Status |
|---|---------|---------|--------|
| 1.1.1 | Create `src/api/ws.py` — FastAPI WebSocket manager with connection registry, broadcast, per-topic subscriptions (positions, fills, alarms, agents, market) | — | [x] |
| 1.1.2 | Wire WebSocket manager into `src/api/main.py` — mount `/ws` route, start NATS subscription bridge on startup (NATS events → WS broadcast) | 1.1.1 | [x] |
| 1.1.3 | Add heartbeat/ping-pong and stale connection cleanup (30s timeout) | 1.1.1 | [x] |

### Epic 1.2 — Credential Vault (Python)
**Files**: `src/security/credential_vault.py` (new), `src/api/routes/vault.py` (new), `src/database.py` (edit)  
**Agent**: @backend-engineer  
**Reference**: Port from `trading-bot-ai-studio/server/src/security/credentialVault.ts`

| # | Subtask | Depends | Status |
|---|---------|---------|--------|
| 1.2.1 | Create `src/security/credential_vault.py` — AES-256-GCM encrypt/decrypt using `cryptography` lib. Master key from env `VAULT_MASTER_KEY`. Functions: `encrypt_credential()`, `decrypt_credential()`, `generate_master_key()` | — | [x] |
| 1.2.2 | Add `credentials` table to `src/database.py` — columns: id, exchange_id, label, encrypted_api_key, encrypted_api_secret, encrypted_passphrase (nullable), is_testnet, created_at, updated_at. Add CRUD methods to DatabaseManager. | — | [x] |
| 1.2.3 | Create `src/api/routes/vault.py` — endpoints: `POST /api/vault/credentials` (store), `GET /api/vault/credentials` (list metadata only, never return decrypted keys), `DELETE /api/vault/credentials/{id}`, `POST /api/vault/credentials/{id}/test` (decrypt + test exchange conn via CCXT) | 1.2.1, 1.2.2 | [x] |
| 1.2.4 | Mount vault router in `src/api/main.py`, add to OpenAPI tags | 1.2.3 | [x] |
| 1.2.5 | Write tests: `tests/test_credential_vault.py` — encrypt/decrypt round-trip, test connection mock, invalid key rejection | 1.2.3 | [x] |

### Epic 1.3 — Complete API Stubs
**Files**: `src/api/routes/backtest.py` (edit), `src/api/routes/market.py` (edit)  
**Agent**: @backend-engineer  

| # | Subtask | Depends | Status |
|---|---------|---------|--------|
| 1.3.1 | Wire `POST /api/backtests` — replace in-memory dict with DB persistence. Launch backtest as `asyncio.create_task()` calling `tools/backtest.py` engine programmatically. Store results in new `backtest_jobs` table (id, strategy_id, symbol, start_date, end_date, status, result_json, created_at, completed_at). | — | [x] |
| 1.3.2 | Add `GET /api/backtests/{job_id}/results` — return full result JSON (equity curve, trades, stats). Add `GET /api/backtests/history` — list past runs with summary stats. | 1.3.1 | [x] |
| 1.3.3 | Fix `GET /api/klines` — format response to match App B's `Candle` interface: `{ time, open, high, low, close, volume }`. Add timeframe param (1m/5m/15m/1h/4h/1d). | — | [x] |
| 1.3.4 | Add `DELETE /api/orders/{order_id}` — cancel order via exchange adapter | — | [x] |
| 1.3.5 | Add `backtest_jobs` table to `src/database.py` | — | [x] |

### Epic 1.4 — CORS, Auth & Middleware
**Files**: `src/api/main.py` (edit), `src/api/middleware/auth.py` (new)  
**Agent**: @backend-engineer  

| # | Subtask | Depends | Status |
|---|---------|---------|--------|
| 1.4.1 | Add `CORSMiddleware` to `src/api/main.py` — allow origins `http://localhost:3000`, configurable via env `CORS_ORIGINS` | — | [x] |
| 1.4.2 | Create `src/api/middleware/auth.py` — API key auth via `X-API-Key` header for non-read endpoints. Key stored in vault or env. Exempt: `/health`, `/metrics`, `/ws` | — | [x] |
| 1.4.3 | Wire auth middleware into `src/api/main.py` | 1.4.2 | [x] |

### Epic 1.5 — Frontend Containerization
**Files**: `trading-bot-ai-studio/Dockerfile` (new), `trading-bot-ai-studio/nginx.conf` (new), `docker-compose.yml` (edit)  
**Agent**: @frontend-engineer  

| # | Subtask | Depends | Status |
|---|---------|---------|--------|
| 1.5.1 | Create `trading-bot-ai-studio/Dockerfile` — multi-stage: `node:20-alpine` build → `nginx:alpine` serve. Copy Vite build output to `/usr/share/nginx/html`. | — | [x] |
| 1.5.2 | Create `trading-bot-ai-studio/nginx.conf` — SPA fallback (`try_files $uri /index.html`), proxy `/api/*` to `http://api-server:8000`, proxy `/ws` to WebSocket upstream | — | [x] |
| 1.5.3 | Add `frontend` service to `docker-compose.yml` — build context `../trading-bot-ai-studio`, port 3000:80, depends_on api-server | 1.5.1, 1.5.2 | [x] |
| 1.5.4 | Remove `dash` (Streamlit) service from `docker-compose.yml` | — | [x] |

### Epic 1.6 — Frontend API Rewiring
**Files**: `trading-bot-ai-studio/services/backend.ts` (edit), others in `services/`  
**Agent**: @frontend-engineer  
**Constraint**: Do NOT rewrite component logic — only change data access calls.

| # | Subtask | Depends | Status |
|---|---------|---------|--------|
| 1.6.1 | Update `services/backend.ts` — change `BACKEND_URL` default from `localhost:3001` to `/api` (nginx proxied). Update all fetch URLs to match FastAPI endpoint paths. | 1.4.1, 1.5.2 | [x] |
| 1.6.2 | Create `services/wsClient.ts` (new) — WebSocket client for `/ws`. Auto-reconnect, subscribe to topics (positions, fills, prices, alarms). Replace `backendStream` usage. | 1.1.2 | [x] |
| 1.6.3 | Update `services/secureStorage.ts` — remove browser-side RSA encryption. Credentials sent over HTTPS to `/api/vault/credentials`, server does all encryption. Keep the UI flow in `SettingsView.tsx`. | 1.2.4 | [x] |
| 1.6.4 | Update `hooks/useAccountState.ts` — replace `localStorage` hydration with REST fetch from `/api/market/positions`, `/api/market/trades`, `/api/market/account`. Subscribe to WS for live updates. | 1.6.1, 1.6.2 | [x] |
| 1.6.5 | Update `services/strategyStorage.ts` — replace `localStorage` read/write with REST calls to `/api/strategies`. | 1.6.1 | [x] |
| 1.6.6 | Update `services/executionJournal.ts` and `services/fillLedger.ts` — remove localStorage persistence. Execution journal served from backend via WS events. Fill ledger from `/api/market/trades`. | 1.6.2 | [x] |
| 1.6.7 | Update `services/orderIdempotency.ts` — remove localStorage cache. Idempotency enforced server-side by `order_intents` table. Client sends idempotency key in request header. | 1.6.1 | [x] |
| 1.6.8 | Update `components/BacktestDashboard.tsx` — submit backtests to `POST /api/backtests`, poll `GET /api/backtests/{id}` for status, fetch results from `GET /api/backtests/{id}/results`. Remove mock data fallback. | 1.3.2 | [x] |
| 1.6.9 | Update `services/marketStream.ts` — keep Bybit WebSocket for direct market data OR rewire to consume from FastAPI WebSocket (market.data topic). Decision: keep direct Bybit WS for lowest latency, use FastAPI WS for positions/fills/alarms only. | 1.6.2 | [x] |

### Epic 1.7 — Integration Verification
**Agent**: @tester  

| # | Subtask | Depends | Status |
|---|---------|---------|--------|
| 1.7.1 | Update Playwright tests (`tests/e2e.spec.ts`) — retarget from Express to FastAPI backend. Verify: dashboard loads, strategy CRUD, backtest submission, settings page. | 1.6.* | [x] |
| 1.7.2 | Add API integration tests — `tests/test_api_vault.py`, `tests/test_api_backtest_e2e.py` (submit job → poll → verify results) | 1.2.5, 1.3.2 | [x] |
| 1.7.3 | Docker Compose smoke test — `docker compose up`, verify all services healthy, frontend loads, API responds | 1.5.3 | [x] |

---

## Phase 2: AI Agent Core

**Goal**: Autonomous agents can be created, backtest strategies, paper trade, and go live with guardrails.

### Epic 2.1 — Agent Data Model
**Files**: `src/config.py` (edit), `src/database.py` (edit)  
**Agent**: @backend-engineer  

| # | Subtask | Depends | Status |
|---|---------|---------|--------|
| 2.1.1 | Add agent Pydantic models to `src/config.py` — `AgentConfig`, `AgentTarget`, `AgentRiskGuardrails`, `AgentBacktestRequirements`, `AgentPaperRequirements`, `AgentSchedule`. Match schema from architecture doc Section 3.2. | — | [x] |
| 2.1.2 | Add `agents` table to `src/database.py` — columns: id, name, status (created/backtesting/paper/live/paused/retired), config_json, allocation_usd, created_at, updated_at, paused_at, retired_at. Add CRUD methods. | — | [x] |
| 2.1.3 | Add `agent_decisions` table — columns: id, agent_id, timestamp, phase (observe/orient/decide/act/learn), market_snapshot_json, decision_json, outcome_json, trade_ids[]. For audit trail. | 2.1.2 | [x] |
| 2.1.4 | Add `agent_performance` table — columns: id, agent_id, date, realized_pnl, unrealized_pnl, total_trades, win_rate, sharpe_rolling_30d, max_drawdown, equity. Daily rollup. | 2.1.2 | [x] |

### Epic 2.2 — LLM Proxy Service
**Files**: `src/services/llm_proxy.py` (new), `Dockerfile.proxy` (new)  
**Agent**: @backend-engineer  
**Constraint**: Must work without proxy (Gemini fallback). Proxy is optional enhancement.

| # | Subtask | Depends | Status |
|---|---------|---------|--------|
| 2.2.1 | Create `src/services/llm_proxy.py` — FastAPI service (port 8087). OpenAI-compatible `/v1/chat/completions` endpoint. Accepts messages[], returns structured JSON. Implements: token bucket rate limiter (30 RPM), response cache (TTL 5min, keyed on message hash), request/response logging. | — | [x] |
| 2.2.2 | Add Gemini provider in proxy — if primary provider unavailable, route to Gemini API via `google-generativeai` SDK. Env: `GEMINI_API_KEY`. Return same response format. | 2.2.1 | [x] |
| 2.2.3 | Create `Dockerfile.proxy` — lightweight Python image, only llm_proxy deps (fastapi, uvicorn, httpx, google-generativeai). ~50MB image. | 2.2.1 | [x] |
| 2.2.4 | Add `copilot-proxy` service to `docker-compose.yml` — port 8087, env vars for keys, restart always | 2.2.3 | [x] |
| 2.2.5 | Create `src/llm_client.py` — async client wrapper used by agent orchestrator. `async def chat(messages, model, temperature) -> dict`. Calls proxy's `/v1/chat/completions`. Handles timeouts, retries, fallback. | 2.2.1 | [x] |

### Epic 2.3 — Agent Orchestrator Service
**Files**: `src/services/agent_orchestrator.py` (new), `src/api/routes/agents.py` (new)  
**Agent**: @backend-engineer  
**This is the largest epic — core of the platform.**

| # | Subtask | Depends | Status |
|---|---------|---------|--------|
| 2.3.1 | Create `src/services/agent_orchestrator.py` — FastAPI app (port 8088). On startup: load all non-retired agents from DB, subscribe to NATS for market data + execution reports. Health endpoint at `/health`. | 2.1.2, 2.2.5 | [x] |
| 2.3.2 | Implement agent lifecycle state machine — `AgentStateMachine` class. States: created → backtesting → paper → live → paused → retired. Transitions validated against stage gates (Section 3.1 of architecture doc). Publish state changes to NATS `agent.status`. | 2.3.1 | [x] |
| 2.3.3 | Implement OBSERVE phase — on each `rebalance_interval` tick: fetch latest market data from NATS cache, compute indicators (call strategy engine functions), run regime detection, snapshot portfolio state. | 2.3.2 | [x] |
| 2.3.4 | Implement ORIENT phase — send market context to LLM proxy: regime + indicators + positions. Parse structured response (market thesis, confidence score 0-100, recommended action). If regime mismatch → flag for strategy switch. | 2.3.3, 2.2.5 | [x] |
| 2.3.5 | Implement DECIDE phase — apply risk guardrails (max position size, leverage, exposure). Check portfolio constraints (correlation, concentration). Generate order intents. Priority: risk > return > signal. | 2.3.4 | [x] |
| 2.3.6 | Implement ACT phase — publish order intents to NATS `trading.orders`. Subscribe to `trading.executions` for fill reports. Update agent state with fill results. | 2.3.5 | [x] |
| 2.3.7 | Implement LEARN phase — record decision + outcome in `agent_decisions` table. Update `agent_performance` daily rollup. If performance below threshold → increase regime check frequency. If stage gate breached → auto-pause + notify. | 2.3.6 | [x] |
| 2.3.8 | Implement backtest gate — when agent transitions created → backtesting: submit backtest job via NATS request/reply to replay service. Poll for completion. Validate results against `backtest_requirements` (min Sharpe, profit factor, MaxDD, min trades). Pass → advance to paper. Fail → stay in backtesting, log reason. | 2.3.2, 1.3.1 | [x] |
| 2.3.9 | Implement paper gate — when agent in paper mode: run for configured `min_days`. Compare paper P&L vs backtest expectations (`performance_tolerance_pct`). Pass → advance to live. Fail → back to backtesting. | 2.3.8 | [x] |
| 2.3.10 | Create `src/api/routes/agents.py` — REST endpoints for agent CRUD. `GET /api/agents`, `POST /api/agents`, `GET /api/agents/{id}`, `PUT /api/agents/{id}`, `POST /api/agents/{id}/start`, `/pause`, `/resume`, `/retire`, `GET /api/agents/{id}/journal`, `GET /api/agents/{id}/performance`, `DELETE /api/agents/{id}`. | 2.3.1, 2.1.2 | [x] |
| 2.3.11 | Mount agents router in `src/api/main.py`, add to OpenAPI tags | 2.3.10 | [x] |
| 2.3.12 | Add `agent-orchestrator` service to `docker-compose.yml` — port 8088, depends on nats, postgres, copilot-proxy | 2.3.1, 2.2.4 | [x] |

### Epic 2.4 — Portfolio Risk Manager
**Files**: `src/risk/portfolio_risk.py` (new)  
**Agent**: @backend-engineer  

| # | Subtask | Depends | Status |
|---|---------|---------|--------|
| 2.4.1 | Create `src/risk/portfolio_risk.py` — `PortfolioRiskManager` class. Maintains aggregate view of all agent positions. Enforces: max total exposure, max correlation between agents (rolling 30-day returns), max sector concentration. Called by agent orchestrator before ACT phase. | 2.3.5 | [x] |
| 2.4.2 | Add API rate limit pool — `RateLimitPool` class in portfolio risk. Token bucket per exchange, shared across agents. Each agent gets `per_agent_share` tokens/second. Prevents 429 errors. | 2.4.1 | [x] |
| 2.4.3 | Write tests: `tests/test_portfolio_risk.py` — correlation limit enforcement, exposure cap, rate limit allocation | 2.4.1 | [x] |

### Epic 2.5 — Agent UI (Frontend)
**Files**: `trading-bot-ai-studio/components/AgentManager.tsx` (new), `components/AgentDetail.tsx` (new)  
**Agent**: @frontend-engineer  

| # | Subtask | Depends | Status |
|---|---------|---------|--------|
| 2.5.1 | Create `components/AgentManager.tsx` — list all agents with status badges (created/backtesting/paper/live/paused/retired). Create new agent form. Start/pause/resume/retire buttons. Uses `/api/agents` endpoints. | 2.3.10 | [x] |
| 2.5.2 | Create `components/AgentDetail.tsx` — agent detail view. Performance chart (equity curve), decision journal (scrollable log), current positions, risk metrics. Subscribe to WS for live updates. | 2.5.1 | [x] |
| 2.5.3 | Add "Agents" tab to `Navbar.tsx` and route in `App.tsx` | 2.5.1 | [x] |

### Epic 2.6 — Agent Tests
**Agent**: @tester  

| # | Subtask | Depends | Status |
|---|---------|---------|--------|
| 2.6.1 | `tests/test_agent_orchestrator.py` — unit tests for state machine transitions, stage gate validation, decision pipeline with mocked LLM | 2.3.7 | [x] |
| 2.6.2 | `tests/test_agent_integration.py` — integration test: create agent → auto-backtest → validate gate → advance to paper. Uses test DB + mock exchange. | 2.3.9 | [x] |

---

## Phase 3: Enhanced Backtesting

**Goal**: Walk-forward optimization, Monte Carlo simulation, programmatic backtest API for agents.

### Epic 3.1 — Walk-Forward Optimizer
**Files**: `src/backtest/walk_forward.py` (new)  
**Agent**: @Strategy Developer  

| # | Subtask | Depends | Status |
|---|---------|---------|--------|
| 3.1.1 | Create `src/backtest/walk_forward.py` — `WalkForwardOptimizer` class. Splits historical data into N in-sample/out-of-sample windows (configurable ratio, default 70/30). Runs strategy on in-sample, validates on out-of-sample. Reports per-window and aggregate metrics. | — | [x] |
| 3.1.2 | Integrate walk-forward into backtest API — optional `walk_forward_windows` param on `POST /api/backtests`. If set, run walk-forward instead of simple backtest. Results include per-window breakdown. | 3.1.1, 1.3.1 | [x] |

### Epic 3.2 — Monte Carlo Simulation
**Files**: `src/backtest/monte_carlo.py` (new)  
**Agent**: @Strategy Developer  

| # | Subtask | Depends | Status |
|---|---------|---------|--------|
| 3.2.1 | Create `src/backtest/monte_carlo.py` — `MonteCarloSimulator` class. Takes backtest trade results, randomizes order/returns N times (default 1000). Reports confidence intervals for: final equity, Sharpe, MaxDD. Returns pass/fail against configurable percentile threshold. | — | [x] |
| 3.2.2 | Integrate Monte Carlo into backtest API — optional `monte_carlo_runs` param. If set, append MC results to backtest output. | 3.2.1, 1.3.1 | [x] |

### Epic 3.3 — Strategy Comparison
**Files**: `src/api/routes/backtest.py` (edit)  
**Agent**: @backend-engineer  

| # | Subtask | Depends | Status |
|---|---------|---------|--------|
| 3.3.1 | Add `POST /api/backtests/compare` — accepts array of backtest job IDs. Returns side-by-side stats comparison + statistical significance test (paired t-test on daily returns). | 1.3.2 | [x] |

---

## Phase 4: Production Hardening

**Goal**: Robust alerting, remote control, audit trails, backups.

### Epic 4.1 — TradingView Webhook + Signal Service
**Files**: `src/api/routes/signals.py` (new), `src/services/signal_service.py` (new)  
**Agent**: @backend-engineer  
**Reference**: Port from `trading-bot-ai-studio/server/src/signals/`

| # | Subtask | Depends | Status |
|---|---------|---------|--------|
| 4.1.1 | Create `src/api/routes/signals.py` — `POST /api/webhook/tradingview` (validates webhook secret via HMAC), `GET /api/signals/history`, `PUT /api/signals/config` (auto-execution toggle). | — | [x] |
| 4.1.2 | Create `src/services/signal_service.py` — parses TradingView alert JSON, maps to order intent, publishes to NATS `trading.orders` if auto-execution enabled. Logs all signals to `signals` table. | 4.1.1 | [x] |
| 4.1.3 | Add `signals` table to `src/database.py` — id, source, symbol, side, confidence, entry_price, status, auto_executed, agent_id (nullable), created_at | — | [x] |

### Epic 4.2 — Alert Escalation + Discord
**Files**: `src/notifications/discord.py` (new), `src/notifications/escalation.py` (new)  
**Agent**: @backend-engineer  

| # | Subtask | Depends | Status |
|---|---------|---------|--------|
| 4.2.1 | Create `src/notifications/discord.py` — send Discord webhook embeds. Rich formatting for trade reports, daily summaries, alarms. Env: `DISCORD_WEBHOOK_URL`. | — | [x] |
| 4.2.2 | Create `src/notifications/escalation.py` — `AlertEscalator` class. Alarm severity levels: INFO → WARNING → CRITICAL → AUTO_SHUTDOWN. Timer-based escalation (WARNING unacknowledged for 15min → CRITICAL). CRITICAL triggers agent pause + all-channel notification. AUTO_SHUTDOWN triggers kill switch. | 4.2.1 | [x] |
| 4.2.3 | Wire escalation into risk service — risk service publishes alarms to NATS, escalator subscribes and manages severity lifecycle | 4.2.2 | [x] |

### Epic 4.3 — Remote Kill Switch
**Files**: `src/api/routes/risk.py` (new)  
**Agent**: @backend-engineer  

| # | Subtask | Depends | Status |
|---|---------|---------|--------|
| 4.3.1 | Create `src/api/routes/risk.py` — `GET /api/risk/status`, `PUT /api/risk/limits`, `POST /api/risk/kill-switch` (cancel all orders, flatten positions, pause all agents), `GET /api/risk/alarms`, `POST /api/risk/alarms/{id}/ack` | — | [x] |
| 4.3.2 | Wire kill switch — publish kill command to NATS `risk.management`. Execution service subscribes and cancels all open orders. Agent orchestrator pauses all agents. Confirmation broadcast via WS. | 4.3.1 | [x] |

### Epic 4.4 — Encrypted Backups
**Files**: `scripts/backup.sh` (new), `docker-compose.yml` (edit)  
**Agent**: @backend-engineer  

| # | Subtask | Depends | Status |
|---|---------|---------|--------|
| 4.4.1 | Create `scripts/backup.sh` — daily `pg_dump`, encrypt with GPG/age, store to configurable path. Cron schedule in Docker. Retention: 7 daily, 4 weekly. | — | [x] |
| 4.4.2 | Add backup sidecar to `docker-compose.yml` — runs backup.sh on schedule via ofelia or built-in cron | 4.4.1 | [x] |

---

## Phase 5: VPS Deployment (Optional)

**Goal**: Move latency-sensitive services to a VPS co-located with exchange servers.

### Epic 5.1 — VPS Infrastructure
**Agent**: @backend-engineer  

| # | Subtask | Depends | Status |
|---|---------|---------|--------|
| 5.1.1 | Create `docker-compose.vps.yml` — override file for VPS deployment. Only: strategy-engine, execution, feed, nats (leaf node), postgres (replica or standalone). | All of Phase 1-4 | [x] |
| 5.1.2 | WireGuard VPN setup script — `scripts/setup_wireguard.sh`. Connects VPS to local machine. NATS leaf node config for cross-site pub/sub. | 5.1.1 | [x] |
| 5.1.3 | Cold-start pre-warming — on VPS boot: load recent positions, open orders, agent state from DB. Resume strategy engine. Health check gate before accepting new signals. | 5.1.1 | [x] |
| 5.1.4 | Latency benchmarking script — `tools/latency_bench.py`. Measures round-trip to exchange API from current host. Compare local vs VPS. | — | [x] |

---

## Dependency Graph (Critical Path)

```
Phase 1 (Foundation) ─────────────────────────────────────────────────
  1.1 WebSocket ──┐
  1.2 Vault ─────┤
  1.3 API Stubs ─┼──▶ 1.6 Frontend Rewiring ──▶ 1.7 Integration Tests
  1.4 CORS/Auth ─┤
  1.5 Dockerfile ┘

Phase 2 (Agents) ─────────────────────────────────────────────────────
  2.1 Data Model ─┐
  2.2 LLM Proxy ──┼──▶ 2.3 Agent Orchestrator ──▶ 2.4 Portfolio Risk
                   │                               ──▶ 2.5 Agent UI
                   │                               ──▶ 2.6 Agent Tests
                   └──▶ (Phase 1 must be done first)

Phase 3 (Backtesting) ────────────────────────────────────────────────
  3.1 Walk-Forward ─┐
  3.2 Monte Carlo ──┼──▶ 3.3 Strategy Comparison
                     └──▶ (Needs 1.3 backtest API done)

Phase 4 (Hardening) ──────────────────────────────────────────────────
  4.1 Signals ───────┐
  4.2 Escalation ────┼──▶ (Can run in parallel with Phase 2-3)
  4.3 Kill Switch ───┤
  4.4 Backups ───────┘

Phase 5 (VPS) ────────────────────────────────────────────────────────
  5.1 VPS Infra ────▶ (After Phase 1-4 stable)
```

## Execution Order (Recommended)

**Sprint 1** (Week 1-2): Epics 1.1, 1.2, 1.3, 1.4, 1.5 in parallel  
**Sprint 2** (Week 3-4): Epic 1.6 (sequential, needs Sprint 1 outputs), Epic 1.7  
**Sprint 3** (Week 5-6): Epics 2.1, 2.2 in parallel  
**Sprint 4** (Week 7-8): Epic 2.3 (largest — may need full 2 weeks)  
**Sprint 5** (Week 9): Epics 2.4, 2.5, 2.6 in parallel  
**Sprint 6** (Week 10): Epics 3.1, 3.2, 3.3, 4.1, 4.2 in parallel  
**Sprint 7** (Week 11): Epics 4.3, 4.4, remaining Phase 3 integration  
**Sprint 8** (Week 12+): Phase 5 if latency benchmarks justify VPS  

## Files Created/Modified Summary

### New Files (21)
| File | Phase | Purpose |
|------|-------|---------|
| `src/api/ws.py` | 1 | WebSocket manager |
| `src/security/credential_vault.py` | 1 | AES-256-GCM credential encryption |
| `src/api/routes/vault.py` | 1 | Vault REST endpoints |
| `src/api/middleware/auth.py` | 1 | API key authentication |
| `trading-bot-ai-studio/Dockerfile` | 1 | Frontend container |
| `trading-bot-ai-studio/nginx.conf` | 1 | Reverse proxy config |
| `trading-bot-ai-studio/services/wsClient.ts` | 1 | WebSocket client |
| `tests/test_credential_vault.py` | 1 | Vault tests |
| `tests/test_api_vault.py` | 1 | Vault API tests |
| `tests/test_api_backtest_e2e.py` | 1 | Backtest API tests |
| `src/services/llm_proxy.py` | 2 | LLM proxy service |
| `src/llm_client.py` | 2 | Async LLM client |
| `Dockerfile.proxy` | 2 | LLM proxy container |
| `src/services/agent_orchestrator.py` | 2 | Agent lifecycle manager |
| `src/api/routes/agents.py` | 2 | Agent REST endpoints |
| `src/risk/portfolio_risk.py` | 2 | Portfolio-level risk |
| `trading-bot-ai-studio/components/AgentManager.tsx` | 2 | Agent list UI |
| `trading-bot-ai-studio/components/AgentDetail.tsx` | 2 | Agent detail UI |
| `tests/test_agent_orchestrator.py` | 2 | Agent unit tests |
| `tests/test_agent_integration.py` | 2 | Agent integration tests |
| `tests/test_portfolio_risk.py` | 2 | Portfolio risk tests |
| `src/backtest/walk_forward.py` | 3 | Walk-forward optimizer |
| `src/backtest/monte_carlo.py` | 3 | Monte Carlo simulation |
| `src/api/routes/signals.py` | 4 | Signal/webhook endpoints |
| `src/services/signal_service.py` | 4 | Signal processing |
| `src/notifications/discord.py` | 4 | Discord notifications |
| `src/notifications/escalation.py` | 4 | Alert escalation |
| `src/api/routes/risk.py` | 4 | Risk control endpoints |
| `scripts/backup.sh` | 4 | Encrypted DB backups |

### Modified Files (12)
| File | Phase | Changes |
|------|-------|---------|
| `src/api/main.py` | 1 | Mount WS, vault, CORS, auth middleware |
| `src/database.py` | 1,2,4 | Add credentials, backtest_jobs, agents, agent_decisions, agent_performance, signals tables |
| `src/api/routes/backtest.py` | 1,3 | Wire to engine, add results/history/compare endpoints |
| `src/api/routes/market.py` | 1 | Fix klines format, add order cancel |
| `docker-compose.yml` | 1,2,4 | Add frontend, remove dash, add agent-orchestrator, copilot-proxy, backup |
| `src/config.py` | 2 | Add AgentConfig models |
| `trading-bot-ai-studio/services/backend.ts` | 1 | Update base URL and endpoint paths |
| `trading-bot-ai-studio/services/secureStorage.ts` | 1 | Remove browser crypto, use server vault |
| `trading-bot-ai-studio/hooks/useAccountState.ts` | 1 | Replace localStorage with REST/WS |
| `trading-bot-ai-studio/services/strategyStorage.ts` | 1 | Replace localStorage with REST |
| `trading-bot-ai-studio/components/Navbar.tsx` | 2 | Add Agents tab |
| `trading-bot-ai-studio/App.tsx` | 2 | Add Agents route |
