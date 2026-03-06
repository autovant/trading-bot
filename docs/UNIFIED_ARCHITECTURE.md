# Unified Trading Platform Architecture Document

**Version**: 1.0  
**Date**: 2026-03-03  
**Author**: Architecture Review  

---

## Executive Summary

This document defines the architecture for merging **App A** (trading-bot — Python microservices engine) and **App B** (trading-bot-ai-studio — TypeScript React workstation) into a single, AI-agent-driven autonomous trading platform. The unified system retains App A's battle-tested Python backend as the execution and strategy core, replaces App A's Streamlit dashboard with App B's institutional-grade React UI, and introduces an AI Agent framework that bridges the two via REST + NATS + WebSocket.

**Key architectural decisions:**
- Python backend is the single source of truth for all trading state
- TypeScript frontend is the single UI — Streamlit and incomplete Next.js/Vite attempts are retired
- AI agents run server-side in Python, using a Copilot-proxy LLM provider
- Docker Compose orchestrates everything on a single machine, with optional VPS deployment for the execution engine

---

## Section 1: Feature Merge Matrix

| Feature | App A | App B | Decision | Rationale |
|---------|-------|-------|----------|-----------|
| **Strategy Engine** | Multi-timeframe, regime detection, MACD/EMA/ADX/ATR/Bollinger, dynamic JSON/YAML config, plugin scoring | SMA/EMA/RSI only, basic rule builder | **KEEP-A** | App A's engine is far more mature with 15+ indicators, regime detection, and production-tested signal scoring |
| **Visual Strategy Builder** | None | Indicator config UI, entry/exit rule builder, inline backtesting | **KEEP-B** | No equivalent exists in App A; add as frontend for App A's DynamicStrategyEngine |
| **Exchange Connectivity** | CCXT (30+ exchanges) + native Bybit WS + Zoomex V3, replay client | Bybit V5 WS only (2-3 exchanges) | **KEEP-A** | CCXT multi-exchange support is essential; App B's Bybit WS logic is redundant |
| **Paper Broker** | High-fidelity: latency sim, slippage, partial fills, funding, queue dynamics | Basic paper simulation in ExecutionService | **KEEP-A** | App A's PaperBroker is institutional-grade with configurable parameters |
| **Order Execution Pipeline** | Ladder entries, dual stops (soft ATR + hard %), trailing, perps executor | Circuit breaker, rate limiter, idempotency, immutable journal | **MERGE** | Combine App A's sophisticated order types with App B's safety pipeline (circuit breaker, idempotency) |
| **Risk Management** | Crisis mode, drawdown thresholds, consecutive loss detection, daily limits, per-symbol exposure | Kill switch, max notional, daily loss limit, alarms (STALE_DATA, CIRCUIT_BREAKER, etc.) | **MERGE** | App A has deeper risk logic; App B has better operational alarms and kill switch UX |
| **Database** | PostgreSQL (TimescaleDB) + SQLite, async drivers (asyncpg/aiosqlite), full audit trail | better-sqlite3, 3 tables (orders, fills, pnl_events) | **KEEP-A** | App A's dual-DB with idempotent upserts and full schema is production-grade |
| **Messaging** | NATS pub/sub with memory fallback, auto-reconnect, subject routing | None (tightly coupled REST + WS) | **KEEP-A** | NATS decoupling is essential for microservices and agent coordination |
| **API Server** | FastAPI with rate limiting, error handling, partial route stubs | Express + WebSocket, credential vault endpoints, signal ingestion | **MERGE** | Keep FastAPI as primary; port App B's credential vault and signal webhook endpoints to FastAPI |
| **Dashboard/UI** | Streamlit (functional but basic) | React/Vite, Apple-inspired dark theme, animations, responsive | **KEEP-B** | App B's UI is institutional-grade; Streamlit is not suitable for a trading workstation |
| **AI Assistant** | None | Gemini 2.5-Flash + OpenAI-compatible, market analysis, trade suggestions, chat | **KEEP-B** | Foundational AI integration — extend with autonomous agent capabilities |
| **Backtesting** | CLI tool, Parquet replay, equity curve, realistic fills via PaperBroker | UI dashboard with playback controls, equity animation, strategy comparison, Sharpe/Sortino/MaxDD | **MERGE** | App A provides the engine (real data + realistic sim); App B provides the visualization |
| **Credential Storage** | Plain config/env vars | RSA-OAEP browser-side → AES-256-GCM server-side vault | **KEEP-B** | App B's encryption pipeline is the only secure solution; port vault to Python backend |
| **Signal Processing** | Signal engine with scoring, alert routing | TradingView webhook, auto-execution toggle, signal history | **MERGE** | Combine App A's scoring with App B's webhook ingestion and auto-execution |
| **Monitoring** | Prometheus + Grafana, Telegram notifications, CLI monitor | WebSocket-based alarms (5 types), severity levels | **MERGE** | Keep Prometheus/Grafana stack; add App B's alarm types to the notification pipeline |
| **Docker Orchestration** | Full docker-compose (7+ services), multi-stage Dockerfile, security hardening | None | **KEEP-A** | Add App B's frontend as an additional container (nginx static serve) |
| **Order Book Visualization** | Feed service publishes orderbook via NATS | Depth bars, bid/ask pressure, OBI indicator | **KEEP-B** | App B's orderbook UI consumes App A's feed service data |
| **Position Accounting** | DatabaseManager tracks positions with mark-to-market | Liquidation price calc, margin tracking, ROE display, leverage math | **MERGE** | App A stores the data; App B's calculations move to Python; UI rendering stays in React |
| **E2E Tests** | pytest for unit/integration | Playwright for UI | **KEEP-BOTH** | Different test layers — both are needed |
| **Streamlit Dashboard** | Complete real-time monitoring | N/A | **DROP** | Replaced entirely by App B's React UI |
| **Next.js Frontend** | Partial/incomplete | N/A | **DROP** | Superseded by App B's Vite React app |
| **frontend_v2** | Partial/incomplete | N/A | **DROP** | Superseded by App B's Vite React app |
| **Express Backend** | N/A | Complete (exchange adapters, risk, signals, vault, DB) | **DROP** | Replaced by App A's FastAPI; critical features (vault, signals) ported to Python |
| **localStorage Persistence** | N/A | Used for strategies, fills, orders, idempotency | **DROP** | All persistence moves to server-side databases |
| **Mock Data Generator** | N/A | Seeded random walk candles | **DROP** | Backtests must use real exchange data via App A's replay system |
| **AI Agent Framework** | None | None | **NEW** | Autonomous agent lifecycle, multi-agent coordination (see Section 3) |
| **Copilot LLM Proxy** | None | None | **NEW** | Custom proxy to route AI requests through GitHub Copilot subscription |
| **Portfolio Risk Manager** | None | None | **NEW** | Cross-agent correlation, concentration risk, portfolio-level drawdown |
| **Walk-Forward Optimizer** | None | None | **NEW** | Out-of-sample testing, Monte Carlo validation |
| **Market Regime Detector** | Basic in signal_generator | None | **NEW** | Standalone service with ML-based regime classification |
| **Performance Attribution** | None | None | **NEW** | Alpha decomposition, factor analysis |

---

## Section 2: Architecture Blueprint

### 2.1 System Component Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         UNIFIED TRADING PLATFORM                        │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                    REACT FRONTEND (App B UI)                     │    │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐           │    │
│  │  │Dashboard  │ │Strategy  │ │Backtest  │ │ AI Chat  │           │    │
│  │  │Positions  │ │Builder   │ │Playback  │ │Assistant │           │    │
│  │  │OrderBook  │ │Indicators│ │Equity    │ │Analysis  │           │    │
│  │  │Risk Panel │ │Rules     │ │Stats     │ │Suggest   │           │    │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘           │    │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐           │    │
│  │  │Signals   │ │Settings  │ │Agent     │ │Remote    │           │    │
│  │  │Webhook   │ │Vault     │ │Monitor   │ │Controls  │           │    │
│  │  │History   │ │Exchange  │ │Lifecycle │ │Kill Switch│          │    │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘           │    │
│  └──────────────────────────┬──────────────────────────────────────┘    │
│                              │ REST + WebSocket                         │
│  ┌───────────────────────────▼──────────────────────────────────────┐   │
│  │                  FASTAPI GATEWAY (Unified API)                    │   │
│  │  /api/agents/* /api/backtest/* /api/market/* /api/strategy/*      │   │
│  │  /api/risk/*   /api/signals/*  /api/vault/*  /api/system/*       │   │
│  │  /ws (real-time updates)       /api/webhook/tradingview          │   │
│  │  Rate Limiting │ Auth │ Error Handling │ Prometheus /metrics      │   │
│  └───────────┬────────────────────────────┬─────────────────────────┘   │
│              │ NATS pub/sub               │ Direct calls                │
│  ┌───────────▼────────────────────────────▼─────────────────────────┐   │
│  │                         NATS MESSAGE BUS                          │   │
│  │  trading.orders │ trading.executions │ market.data                │   │
│  │  agent.commands │ agent.status │ risk.management                  │   │
│  │  backtest.jobs  │ backtest.results │ config.reload                │   │
│  └──┬──────────┬──────────┬──────────┬──────────┬──────────┬────────┘   │
│     │          │          │          │          │          │             │
│  ┌──▼───┐  ┌──▼───┐  ┌──▼───┐  ┌──▼───┐  ┌──▼───┐  ┌──▼──────────┐  │
│  │Exec  │  │Feed  │  │Risk  │  │Report│  │Replay│  │Signal       │  │
│  │Svc   │  │Svc   │  │Svc   │  │Svc   │  │Svc   │  │Engine       │  │
│  │:8080 │  │:8081 │  │:8084 │  │:8083 │  │:8085 │  │:8086        │  │
│  │      │  │      │  │      │  │      │  │      │  │             │  │
│  │Paper │  │CCXT  │  │Crisis│  │PnL   │  │Parq  │  │TradingView  │  │
│  │Broker│  │Bybit │  │Mode  │  │Aggr  │  │OHLCV │  │Webhook      │  │
│  │Live  │  │WS    │  │Alarm │  │Stats │  │Replay│  │Scoring      │  │
│  │Exec  │  │OBook │  │Kill  │  │Report│  │VClk  │  │Auto-Exec    │  │
│  └──────┘  └──────┘  └──────┘  └──────┘  └──────┘  └──────────────┘  │
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │  AI LAYER                                                         │   │
│  │  ┌──────────────────┐  ┌──────────────────┐                       │   │
│  │  │  Copilot LLM     │  │  Agent            │                      │   │
│  │  │  Proxy  :8087    │  │  Orchestrator     │                      │   │
│  │  │                  │  │  :8088            │                      │   │
│  │  │  Rate Limiting   │  │                   │                      │   │
│  │  │  Caching         │  │  Agent Pool       │                      │   │
│  │  │  Gemini Fallback │  │  OODA Loop        │                      │   │
│  │  └──────────────────┘  │  Regime Det.      │                      │   │
│  │                        │  Backt. Sched     │                      │   │
│  │                        └──────────────────┘                       │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                      DATA LAYER                                   │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐    │   │
│  │  │ PostgreSQL   │  │ SQLite       │  │ Credential Vault     │    │   │
│  │  │ (TimescaleDB)│  │ (Fallback)   │  │ AES-256-GCM at rest  │    │   │
│  │  │ Trades,Orders│  │ Local dev    │  │ RSA-OAEP transport   │    │   │
│  │  │ Positions    │  │ Testing      │  │ Env-based master key │    │   │
│  │  │ Agent State  │  │              │  │                      │    │   │
│  │  │ Backtest Res │  │              │  │                      │    │   │
│  │  └──────────────┘  └──────────────┘  └──────────────────────┘    │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                      MONITORING                                   │   │
│  │  Prometheus :9090 → Grafana :3000 → Telegram/Discord Alerts      │   │
│  └──────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Deployment Topology

| Component | Location | Justification |
|-----------|----------|---------------|
| **Execution Service** | Local Docker (initially) → VPS (phase 2) | Latency to exchange is critical for fills; VPS co-located with Bybit/Zoomex servers (AWS ap-northeast-1 for Bybit) reduces round-trip by 50-200ms |
| **Feed Service** | Same host as Execution | WebSocket connections to exchanges need low-latency, co-locate with execution |
| **Strategy Engine** | Same host as Execution | Signal → order path must be <100ms; network hop would add unacceptable latency |
| **AI Agent Orchestrator** | Local Docker | Runs alongside strategy engine; LLM calls are async and latency-tolerant |
| **LLM Inference** | Copilot Proxy (local) → Cloud API fallback | Primary: custom proxy intercepting GitHub Copilot API (free with subscription). Fallback: Gemini API for structured outputs. No local GPU needed. |
| **React Frontend** | Local Docker (nginx) | Static assets served locally; accessible via browser on any device on local network. For remote access: Cloudflare Tunnel or Tailscale. |
| **PostgreSQL** | Local Docker | Keep data local for sovereignty, privacy, and latency. TimescaleDB for time-series queries. Daily encrypted backups to cloud storage (optional). |
| **NATS** | Local Docker | Message bus must be co-located with producers/consumers |
| **Prometheus + Grafana** | Local Docker | Monitoring stack runs alongside the services it monitors |
| **Credential Vault** | Local Docker (encrypted volume) | Never send credentials off-machine; AES-256-GCM encryption at rest |

**VPS Migration Path (Phase 2):**
When ready to reduce exchange latency:
1. Deploy execution + feed + strategy on VPS (e.g., Vultr Tokyo or AWS ap-northeast-1)
2. Keep frontend + monitoring + AI orchestrator local
3. Connect via WireGuard VPN tunnel between local ↔ VPS
4. NATS leaf node on VPS connects to local NATS cluster

### 2.3 Data Flow

```
EXCHANGE APIs (Bybit/Zoomex/CCXT)
        │
        ▼
┌──────────────┐     NATS: market.data      ┌──────────────┐
│  Feed Service │ ──────────────────────────▶ │  Strategy    │
│  (WebSocket   │                             │  Engine      │
│   + REST)     │     NATS: market.orderbook  │              │
│               │ ──────────────────────────▶ │  Indicators  │
└──────────────┘                             │  Regime Det. │
                                              │  Signal Gen  │
                                              │  Score/Rank  │
                                              └──────┬───────┘
                                                     │
                                         NATS: trading.orders
                                                     │
                                                     ▼
                                              ┌──────────────┐
                                              │  Execution   │
                                              │  Service     │
                                              │              │
                                              │  Circuit Brk │
                                              │  Idempotency │
                                              │  Rate Limit  │
                                              │  Paper/Live  │
                                              └──────┬───────┘
                                                     │
                                         NATS: trading.executions
                                                     │
                                              ┌──────▼───────┐
                                              │  Database    │
                                              │  (Persist)   │
                                              │              │
                                              │  Risk Svc    │
                                              │  Reporter    │
                                              │  API (WS)    │
                                              │  ──▶ UI      │
                                              └──────────────┘
```

### 2.4 Communication Patterns

| Pattern | Use Case | Technology |
|---------|----------|------------|
| **Async pub/sub** | Market data distribution, execution reports, risk alerts, agent status | NATS |
| **Request/reply** | Agent → Backtest job submission, strategy config queries | NATS request/reply |
| **REST** | Frontend ↔ API (CRUD operations, config, vault, agent management) | FastAPI |
| **WebSocket** | Real-time UI updates (prices, positions, alarms, agent status) | FastAPI WebSocket |
| **Direct function call** | Intra-service (strategy → indicators, execution → paper broker) | Python imports |

---

## Section 3: AI Agent Framework

### 3.1 Agent Lifecycle

```
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│  CREATE  │───▶│ BACKTEST │───▶│  PAPER   │───▶│   LIVE   │───▶│  RETIRE  │
│          │    │          │    │          │    │          │    │          │
│ Config   │    │ Walk-fwd │    │ Shadow   │    │ Active   │    │ Archive  │
│ Target   │    │ Monte C. │    │ 7-day    │    │ Monitor  │    │ Revenue  │
│ Guardrail│    │ Min perf │    │ min test │    │ Adapt    │    │ Analysis │
│ Symbol   │    │ gate     │    │          │    │          │    │          │
└──────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘
      │               │               │               │               │
      │          FAIL: retry          │          FAIL: pause          │
      │          with new             │          + notify             │
      │          parameters           │          + review             │
      │                               │                               │
      └───────────────────────────────┘                               │
              FAIL: back to backtest                                   │
                                                                       │
                                                         Triggered by:
                                                         - Max age reached
                                                         - Sustained underperformance
                                                         - Strategy regime mismatch
                                                         - Manual retirement
```

**Stage Gates:**

| Gate | Criteria to Pass |
|------|-----------------|
| CREATE → BACKTEST | Valid config, symbol exists, capital allocated |
| BACKTEST → PAPER | Sharpe > 1.0, MaxDD < 15%, Win rate > 40%, Profit factor > 1.3, passes walk-forward on ≥3 out-of-sample windows |
| PAPER → LIVE | 7+ days paper trading, paper results within 20% of backtest expectations, no risk limit breaches |
| LIVE → RETIRE | 30+ consecutive days below target, MaxDD > guardrail, or strategy regime shifts permanently |

### 3.2 Agent Configuration Schema

```yaml
agent:
  id: "agent-btc-momentum-001"
  name: "BTC Momentum Alpha"
  status: "live"  # created | backtesting | paper | live | paused | retired
  
  target:
    monthly_return_pct: 15.0
    max_drawdown_pct: 10.0
    allocation_usd: 10000.0
  
  strategy:
    type: "dynamic"  # references DynamicStrategyEngine config
    config_id: "momentum-v3"
    symbols: ["BTCUSDT"]
    timeframes: ["5m", "1h", "4h"]
    regime_adaptive: true
  
  risk_guardrails:
    max_position_size_pct: 25.0    # % of allocation per position
    max_leverage: 5
    max_daily_loss_pct: 3.0
    max_consecutive_losses: 5
    crisis_mode_reduction: 0.5
    correlation_limit: 0.7         # vs other agents
  
  backtest_requirements:
    min_sharpe: 1.0
    min_profit_factor: 1.3
    max_drawdown_pct: 15.0
    min_trades: 50
    walk_forward_windows: 3
    monte_carlo_runs: 1000
    monte_carlo_confidence: 0.95
  
  paper_requirements:
    min_days: 7
    performance_tolerance_pct: 20.0  # vs backtest

  schedule:
    active_hours: "00:00-23:59"  # UTC, or specific windows
    rebalance_interval: "4h"
    regime_check_interval: "1h"
```

### 3.3 Decision-Making Pipeline

```
Every rebalance_interval:
  1. OBSERVE
     ├─ Fetch current market data (price, volume, orderbook)
     ├─ Compute indicators across all configured timeframes
     ├─ Run regime detection (trending/ranging/volatile/crisis)
     └─ Check portfolio state (positions, exposure, P&L)

  2. ORIENT (AI-assisted)
     ├─ LLM analyzes regime + indicators → market thesis
     ├─ Compare current regime vs strategy's optimal regime
     ├─ Score signal confidence (0-100)
     └─ If regime mismatch detected:
          ├─ Query backtest API for alternative strategies
          ├─ If better strategy found & backtested → switch
          └─ If no better strategy → reduce exposure, wait

  3. DECIDE
     ├─ Apply risk guardrails (position size, leverage, exposure)
     ├─ Check portfolio-level constraints (correlation, concentration)
     ├─ Generate order intents (entry, exit, adjust stops)
     └─ Priority: risk limits > target return > signal strength

  4. ACT
     ├─ Submit order intents via NATS → Execution Service
     ├─ Execution Service validates (circuit breaker, idempotency)
     ├─ Order routes to Paper Broker or Live Exchange
     └─ Fill reports flow back via NATS → Agent state update

  5. LEARN
     ├─ Record decision + outcome in agent journal
     ├─ Update rolling performance metrics
     ├─ If performance degrading → increase regime check frequency
     └─ If stage gate violated → pause agent, notify user
```

### 3.4 LLM Provider: Copilot Proxy Architecture

```
┌──────────────┐     HTTP POST     ┌──────────────────┐     HTTPS    ┌─────────┐
│  AI Agent    │ ───────────────▶  │  Copilot Proxy   │ ──────────▶ │ GitHub  │
│  Orchestrator│                   │  (localhost:8087) │             │ Copilot │
│              │ ◀─────────────── │                   │ ◀────────── │ API     │
│              │   JSON response   │  - Auth injection │             │         │
└──────────────┘                   │  - Request format │             └─────────┘
                                   │  - Response parse │
                                   │  - Rate limiting  │
                                   │  - Caching        │
                                   │  - Fallback route │
                                   └────────┬─────────┘
                                            │ Fallback
                                            ▼
                                   ┌──────────────────┐
                                   │  Gemini API      │
                                   │  (structured out) │
                                   └──────────────────┘
```

**Proxy Implementation Notes:**
- Lightweight Python FastAPI service (single file, ~200 lines)
- Intercepts requests, formats for Copilot's chat completions API
- Handles auth token refresh from VS Code's stored credentials
- Response caching for identical market analysis queries (TTL: 5 min)
- Automatic fallback to Gemini if Copilot is unavailable
- Rate limit: max 30 requests/minute to avoid abuse detection
- This is a development convenience — for production, a dedicated API key (Gemini, OpenAI, or local model) is recommended

### 3.5 Inter-Agent Coordination

```yaml
# Portfolio-level constraints enforced by the Agent Orchestrator
portfolio:
  max_total_exposure_usd: 50000
  max_agents: 5
  max_correlation_between_agents: 0.7
  max_sector_concentration: 0.4  # no more than 40% in correlated assets
  
  # API rate limit sharing
  rate_limits:
    bybit:
      orders_per_second: 10      # exchange limit
      per_agent_share: 2         # each agent gets 2/s
    zoomex:
      orders_per_second: 5
      per_agent_share: 1
```

The Agent Orchestrator:
1. Maintains a central view of all agent positions and exposure
2. Before any agent places an order, checks portfolio constraints
3. If two agents want conflicting positions on the same symbol, the agent with higher confidence wins
4. Shared API rate limit pool prevents any single agent from starving others
5. Correlation matrix is recalculated hourly using rolling 30-day returns

---

## Section 4: Technology Stack Decisions

### 4.1 Final Stack

| Layer | Technology | Source | Justification |
|-------|-----------|--------|---------------|
| **Frontend** | React 19 + Vite 6 + Tailwind v4 | App B | Mature, responsive, dark theme, animations; only rewrite needed is replacing localStorage with API calls |
| **API Gateway** | FastAPI (Python) | App A | Async, auto-docs (OpenAPI), Pydantic validation, native NATS integration |
| **Strategy Engine** | Python (custom) | App A | 15+ indicators, regime detection, dynamic config, proven in testing |
| **Execution** | Python FastAPI microservice | App A + App B patterns | App A's ladder/stops + App B's circuit breaker/idempotency merged |
| **Exchange Adapters** | CCXT + native Bybit WS + Zoomex V3 | App A | 30+ exchange support; App B's Bybit WS is a subset |
| **Paper Broker** | Python (PaperBroker) | App A | High-fidelity simulation with configurable latency/slippage/partial fills |
| **Messaging** | NATS | App A | Decoupled pub/sub; essential for agent coordination |
| **Database** | PostgreSQL (TimescaleDB) + SQLite fallback | App A | Time-series optimized; idempotent upserts; full audit trail |
| **Credential Vault** | AES-256-GCM at rest, RSA-OAEP transport | App B (ported to Python) | Port `credentialVault.ts` to Python; use `cryptography` library |
| **AI/LLM** | Copilot Proxy (primary), Gemini (fallback) | New + App B | Cost-effective via existing subscription; structured outputs for decisions |
| **Monitoring** | Prometheus + Grafana | App A | Industry standard; already configured with scrape targets |
| **Notifications** | Telegram + Discord (new) | App A + new | Telegram exists; add Discord webhook for richer formatting |
| **Containerization** | Docker Compose | App A | Simple, proven; no Kubernetes overhead for single-trader scale |
| **Testing** | pytest (backend) + Playwright (frontend) | Both | Coverage across both layers |
| **Language** | Python 3.11+ (backend) + TypeScript 5.x (frontend) | Both | Two-language constraint met; clear separation of concerns |

### 4.2 What to Keep vs. Rewrite

**Keep As-Is (from App A):**
- `src/strategy.py`, `src/signal_generator.py`, `src/indicators.py` — core strategy logic
- `src/exchanges/*` — all exchange adapters
- `src/paper_trader.py` — PaperBroker
- `src/database.py` — database layer
- `src/messaging.py` — NATS client
- `src/services/execution.py`, `feed.py`, `risk.py`, `reporter.py`, `replay.py` — microservices
- `src/config.py` + `config/strategy.yaml` — configuration
- `docker-compose.yml` + `Dockerfile` — orchestration
- `prometheus.yml` — monitoring config
- `tools/backtest.py` — CLI backtesting

**Keep As-Is (from App B):**
- All React components (`components/*`) — UI layer
- `services/marketStream.ts` — rewire to consume from App A's feed service
- `services/strategyEngine.ts` — keep for client-side backtest preview (lightweight)
- `services/ai/*` — AI provider abstraction
- `tests/e2e.spec.ts` — Playwright tests

**Port to Python (from App B):**
- `server/src/security/credentialVault.ts` → `src/security/credential_vault.py`
- `server/src/signals/signalService.ts` → `src/services/signal_service.py`
- `server/src/risk/alarms.ts` → merge into `src/services/risk.py`
- Circuit breaker + idempotency patterns → merge into `src/services/execution.py`

**Rewrite/New:**
- `src/services/agent_orchestrator.py` — new AI agent service
- `src/api/routes/agents.py` — agent management REST endpoints
- `src/api/routes/vault.py` — credential vault REST endpoints
- `src/api/routes/signals.py` — TradingView webhook endpoint
- `src/copilot_proxy.py` — Copilot LLM proxy service
- Frontend: replace all `localStorage` calls with REST API calls to Python backend

### 4.3 Migration Path (Phased)

**Phase 1: Foundation Merge (2-3 weeks)**
1. Port credential vault to Python (`src/security/credential_vault.py`)
2. Complete App A's API stubs (backtest, market, strategy routes)
3. Add WebSocket endpoint to FastAPI for real-time UI updates
4. Add App B's frontend as a Docker container (nginx + Vite build)
5. Rewire React frontend to call App A's FastAPI instead of Express backend
6. Replace all `localStorage` persistence with API calls
7. Add CORS and auth middleware to FastAPI

**Phase 2: AI Agent Core (2-3 weeks)**
1. Build Agent Orchestrator service
2. Implement Copilot Proxy (or Gemini fallback)
3. Create agent CRUD API endpoints
4. Wire agent decision pipeline (observe → orient → decide → act → learn)
5. Implement agent backtest scheduling (NATS request/reply to replay service)
6. Add portfolio-level risk constraints

**Phase 3: Enhanced Backtesting (1-2 weeks)**
1. Implement walk-forward optimization in `tools/backtest.py`
2. Add Monte Carlo simulation module
3. Wire backtest API so agents can programmatically submit and consume results
4. Connect React BacktestDashboard to App A's backtest API
5. Strategy comparison with statistical significance testing

**Phase 4: Production Hardening (1-2 weeks)**
1. Merge alarm systems (App B's alarm types into Prometheus alerting)
2. Add Discord notification channel
3. Remote control endpoints (pause/resume agents, force-close, kill switch)
4. Audit trail for all agent decisions and human interventions
5. Encrypted database backups
6. Health check auto-recovery (watchdog service)

**Phase 5: Optional VPS Deployment (1 week)**
1. Extract execution + feed + strategy into VPS-deployable config
2. WireGuard tunnel setup
3. NATS leaf node configuration
4. Cold-start pre-warming (load recent state from DB on boot)

---

## Section 5: Features to Drop

| Feature | Source | Reason |
|---------|--------|--------|
| **Streamlit Dashboard** | App A (`dashboard/app.py`) | Replaced by App B's React UI. Streamlit is not suitable for a real-time trading workstation — poor WebSocket handling, limited interactivity, single-threaded. |
| **Next.js Frontend** | App A (`frontend/`) | Incomplete; superseded by App B's production-ready Vite React app. Two incomplete frontends are worse than one complete one. |
| **frontend_v2** | App A (`frontend_v2/`) | Same as above — incomplete Vite React attempt. App B is the canonical frontend. |
| **Express Backend** | App B (`server/src/`) | Replaced by App A's FastAPI. Running two backend frameworks doubles maintenance. Critical features (vault, signals, risk alarms) are ported to Python. |
| **better-sqlite3 Server DB** | App B | Replaced by App A's PostgreSQL/aiosqlite with full schema and async drivers. |
| **localStorage Persistence** | App B (strategies, fills, orders, idempotency) | Not production-grade. All state moves to server-side database with proper ACID guarantees. |
| **Mock Data Generator** | App B (`services/mockData.ts`) | Backtests must use real historical data. Seeded random walks give false confidence. Keep only for UI component testing. |
| **App B Exchange Adapters** | App B (`server/src/adapters/`) | Redundant with App A's CCXT + native adapters which support 30+ exchanges vs. 2-3. |
| **App B Paper Simulation** | App B (`services/execution.ts` paper mode) | App A's PaperBroker is far more realistic (latency sim, partial fills, funding). |
| **Presentation Layer** | App A (`src/presentation/`) | Empty/unused stub directory. |
| **Alternative Domain Layers** | App A (`src/domain/`, `src/application/`, `src/infrastructure/`) | Partially implemented DDD layers that add complexity without value. The current flat structure in `src/` works fine. |
| **CLI Monitor** | App A (`tools/monitor.py`) | Replaced by React dashboard + Grafana. CLI TUI is redundant when a web dashboard exists. |

---

## Section 6: Missing Features Roadmap

### Priority 1 — Critical for AI Agent Trading

| # | Feature | Effort | Dependencies | Description |
|---|---------|--------|-------------|-------------|
| 1 | **Copilot LLM Proxy** | S | None | FastAPI service that proxies LLM requests through GitHub Copilot subscription. Single file, ~200 lines. Auth token extraction from VS Code credentials. |
| 2 | **Agent Orchestrator Service** | L | #1 | Core agent lifecycle manager. Agent CRUD, stage gates, decision pipeline, portfolio constraints. New FastAPI microservice on port 8086. |
| 3 | **Credential Vault (Python)** | M | None | Port App B's AES-256-GCM vault to Python using `cryptography` library. REST endpoints for store/retrieve/delete/test credentials. |
| 4 | **FastAPI WebSocket Endpoint** | S | None | Add `/ws` to API server for real-time frontend updates (positions, fills, alarms, agent status). Replace Express WebSocket. |
| 5 | **Frontend API Rewiring** | M | #3, #4 | Replace all `localStorage` and Express calls in React frontend with FastAPI REST + WebSocket calls. |
| 6 | **Backtest API (Complete)** | M | None | Finish stub endpoints: POST job, GET status, GET results. Wire to `tools/backtest.py` engine via async task queue. |

### Priority 2 — Enhanced Strategy & Risk

| # | Feature | Effort | Dependencies | Description |
|---|---------|--------|-------------|-------------|
| 7 | **Walk-Forward Optimizer** | L | #6 | Split historical data into train/test windows. Run strategy on train, validate on test. Iterate across multiple windows. Reject strategies that fail out-of-sample. |
| 8 | **Monte Carlo Simulation** | M | #6 | Randomize trade order/returns 1000x. Report confidence intervals for Sharpe, MaxDD, final equity. Reject strategies below 95th percentile threshold. |
| 9 | **Portfolio Risk Manager** | M | #2 | Cross-agent correlation matrix (rolling 30-day). Concentration limits. Portfolio-level VaR. Aggregate drawdown tracking. |
| 10 | **Market Regime Detector (ML)** | L | #1 | Classify market into trending/ranging/volatile/crisis using HMM or clustering on volatility + trend strength + volume. Publish regime via NATS. |
| 11 | **TradingView Webhook Ingestion** | S | #3 | Port App B's webhook handler to FastAPI route. Parse TradingView alert JSON → order intent → execution service. |

### Priority 3 — Operational Excellence

| # | Feature | Effort | Dependencies | Description |
|---|---------|--------|-------------|-------------|
| 12 | **Discord Notifications** | S | None | Add Discord webhook channel alongside Telegram. Richer embeds for trade reports, daily summaries, alarm escalation. |
| 13 | **Alert Escalation Pipeline** | M | #12 | INFO → WARNING → CRITICAL → AUTO-SHUTDOWN with configurable thresholds. Escalation timer: if WARNING not acknowledged in 15 min → CRITICAL. |
| 14 | **Remote Kill Switch** | S | #4 | WebSocket + REST endpoint to instantly halt all agents, cancel open orders, flatten positions. Accessible from mobile. |
| 15 | **Agent Decision Audit Trail** | M | #2 | Every agent decision (observe/orient/decide/act) logged to database with reasoning, market state snapshot, and outcome. Queryable via API. |
| 16 | **Encrypted DB Backups** | S | None | Daily PostgreSQL `pg_dump` encrypted with GPG, stored to configurable location (local or cloud). Restore tested monthly. |

### Priority 4 — Advanced Features

| # | Feature | Effort | Dependencies | Description |
|---|---------|--------|-------------|-------------|
| 17 | **Performance Attribution** | L | #2, #9 | Decompose returns into alpha (strategy skill), beta (market exposure), gamma (timing). Per-agent and portfolio-level. |
| 18 | **Funding Rate Arbitrage** | M | #2 | Monitor funding rates across exchanges. Alert or auto-execute when spread exceeds threshold. Requires multi-exchange positions. |
| 19 | **News/Sentiment Ingestion** | L | #1 | Ingest crypto news feeds (CryptoPanic API, Twitter/X sentiment). Feed to AI agent for decision augmentation. Not a primary signal — supplementary only. |
| 20 | **Tax Reporting / Trade Export** | M | #15 | Export trade history in CSV/JSON. Calculate realized P&L by tax year. Support FIFO/LIFO cost basis methods. |
| 21 | **Multi-Exchange Arbitrage** | XL | #18 | Detect price discrepancies across exchanges. Execute simultaneous buy/sell. Requires sub-second execution and multi-exchange balances. High complexity, low priority for retail scale. |
| 22 | **Drawdown-Based Dynamic Sizing** | S | #9 | Reduce position sizes proportionally as drawdown increases. Inversely scale with drawdown depth: 5% DD → 90% size, 10% DD → 70% size, 15% DD → 50% size. |
| 23 | **API Rate Limit Manager** | M | #2 | Central rate limit pool shared across agents. Per-exchange limits enforced. Token bucket algorithm. Prevents 429 errors when multiple agents trade simultaneously. |
| 24 | **Graceful Degradation** | M | All | Service health monitoring with automatic fallback: if NATS dies → memory bus, if DB dies → local SQLite, if feed dies → stale data alarm → pause agents. |

---

## Section 7: Risk & Trade-offs

### 7.1 Technical Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| **Copilot Proxy breaks with API changes** | Medium | High (no AI agent decisions) | Gemini fallback provider is always available. Proxy has version detection and graceful degradation. Monitor GitHub API changelog. |
| **NATS single point of failure** | Low | Critical (all inter-service communication stops) | NATS is extremely stable. Memory bus fallback exists for monolith mode. Docker restart policy: `always`. Add health check with auto-restart. |
| **Database corruption/loss** | Low | Critical | Daily encrypted backups. WAL mode for SQLite. PostgreSQL streaming replication (optional). Idempotent upserts allow re-processing. |
| **Exchange API rate limiting** | Medium | Medium (missed trades) | Central rate limit manager (#23). Exponential backoff in CCXT client. Per-agent rate quotas. |
| **Strategy overfitting in backtests** | High | High (losses in live) | Walk-forward validation (#7) is mandatory gate. Monte Carlo (#8) filters fragile strategies. Paper trading gate requires 7+ days of live-market validation. |
| **LLM hallucination in trading decisions** | Medium | High | AI agents suggest but don't bypass risk limits. All decisions constrained by guardrails. LLM output is one input to a scoring pipeline, not the sole decision maker. |
| **Frontend/backend API contract drift** | Medium | Low | OpenAPI spec auto-generated by FastAPI. TypeScript client generated from spec. CI validates contract. |
| **Docker resource exhaustion on single machine** | Medium | Medium | Resource limits in docker-compose (memory, CPU). Monitoring via Prometheus. TimescaleDB compression for old data. |

### 7.2 Operational Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| **Unattended agent runs away** | Low | Critical (capital loss) | Multi-layer guardrails: per-agent limits → portfolio limits → kill switch. Max drawdown auto-pause. Daily loss limit triggers shutdown. Telegram/Discord alerts on every trade. |
| **Exchange downtime during open positions** | Medium | High | Stops stored on exchange (not just locally). Health monitoring detects connection loss → alarm → pause new entries. Existing positions have exchange-side stop-loss. |
| **Network partition (VPS ↔ local)** | Medium (if VPS used) | High | WireGuard with keepalive. Execution engine operates independently with local risk limits. Reconnection auto-syncs state. |
| **Credential leak** | Low | Critical | AES-256-GCM encrypted vault. No plaintext credentials in config/env after Phase 1. API keys scoped to minimum permissions (trade only, no withdraw). IP whitelist on exchange. |
| **Single trader operational burden** | High | Medium | AI agents handle routine decisions. Alert escalation minimizes false alarms. Weekly summary reports auto-generated. Mobile-accessible dashboard for quick checks. |

### 7.3 Architecture Trade-offs

| Decision | Trade-off | Accepted Because |
|----------|-----------|-----------------|
| **Python + TypeScript (2 languages)** | Cognitive overhead of two ecosystems; separate build pipelines | Python is unmatched for data/ML/trading libraries; TypeScript is unmatched for modern web UIs. The boundary is clean (API contract). |
| **Docker Compose (not K8s)** | No auto-scaling, no rolling deploys, manual failover | Single trader with $5k-$100k doesn't need horizontal scaling. Compose is simpler to operate, debug, and understand. K8s adds weeks of complexity for zero benefit at this scale. |
| **Copilot Proxy (not dedicated LLM API)** | Fragile dependency on undocumented API; potential ToS concerns | Cost: $0/month vs. $20-100/month for API keys. Gemini fallback exists. User explicitly prefers this approach. Proxy is <200 lines and easily replaced. |
| **Local deployment (not cloud-native)** | Higher latency to exchanges; depends on local uptime | Data sovereignty, zero cloud costs, simpler security model. VPS migration path exists for Phase 5 when latency matters. |
| **Single PostgreSQL instance (not distributed)** | No HA, backup window creates brief vulnerability | At this scale, a single TimescaleDB handles millions of rows. Daily backups + WAL provide sufficient durability. Managed cloud DB is an easy upgrade if needed. |
| **Flat Python module structure (not DDD)** | Less "clean architecture"; harder to enforce boundaries | The existing flat structure works, is well-tested, and is easy to navigate. DDD adds layers without adding value for a <50-service system operated by one person. |
| **NATS (not Kafka/RabbitMQ)** | Less ecosystem tooling than Kafka; no message persistence by default | NATS is lightweight (~10MB), fast, and perfect for ephemeral trading events. JetStream adds persistence if needed. Kafka is massive overkill for single-trader scale. |

---

## Appendix A: Updated Docker Compose Services

```yaml
services:
  # --- Data Layer ---
  postgres:
    image: timescale/timescaledb-ha:pg16
    ports: ["5432:5432"]
    volumes: ["pgdata:/home/postgres/pgdata"]
    environment:
      POSTGRES_PASSWORD_FILE: /run/secrets/db_password
    restart: always

  nats:
    image: nats:2.10-alpine
    ports: ["4222:4222", "8222:8222"]
    command: ["--jetstream", "--store_dir", "/data"]
    volumes: ["natsdata:/data"]
    restart: always

  # --- Core Trading ---
  strategy-engine:
    build: .
    command: python src/main.py
    depends_on: [postgres, nats]
    environment:
      APP_MODE: paper
      NATS_URL: nats://nats:4222
      DATABASE_URL: postgresql://...
    restart: always

  execution:
    build: .
    command: uvicorn src.services.execution:app --host 0.0.0.0 --port 8080
    ports: ["8080:8080"]
    depends_on: [nats, postgres]
    restart: always

  feed:
    build: .
    command: uvicorn src.services.feed:app --host 0.0.0.0 --port 8081
    ports: ["8081:8081"]
    depends_on: [nats]
    restart: always

  risk:
    build: .
    command: uvicorn src.services.risk:app --host 0.0.0.0 --port 8084
    ports: ["8084:8084"]
    depends_on: [nats]
    restart: always

  reporter:
    build: .
    command: uvicorn src.services.reporter:app --host 0.0.0.0 --port 8083
    ports: ["8083:8083"]
    depends_on: [nats, postgres]
    restart: always

  replay:
    build: .
    command: uvicorn src.services.replay:app --host 0.0.0.0 --port 8085
    ports: ["8085:8085"]
    depends_on: [nats]
    restart: always

  # --- NEW: AI Agent ---
  agent-orchestrator:
    build: .
    command: uvicorn src.services.agent_orchestrator:app --host 0.0.0.0 --port 8086
    ports: ["8086:8086"]
    depends_on: [nats, postgres, copilot-proxy]
    environment:
      LLM_PROVIDER: copilot-proxy
      LLM_BASE_URL: http://copilot-proxy:8087
      FALLBACK_PROVIDER: gemini
    restart: always

  copilot-proxy:
    build:
      context: .
      dockerfile: Dockerfile.proxy
    ports: ["8087:8087"]
    environment:
      COPILOT_TOKEN_PATH: /run/secrets/copilot_token
      GEMINI_API_KEY_FILE: /run/secrets/gemini_key
      RATE_LIMIT_RPM: 30
      CACHE_TTL_SECONDS: 300
    restart: always

  # --- API Gateway ---
  api-server:
    build: .
    command: uvicorn src.api.main:app --host 0.0.0.0 --port 8000
    ports: ["8000:8000"]
    depends_on: [nats, postgres]
    restart: always

  # --- Frontend ---
  frontend:
    build:
      context: ../trading-bot-ai-studio
      dockerfile: Dockerfile
    ports: ["3000:80"]
    depends_on: [api-server]
    restart: always

  # --- Monitoring ---
  prometheus:
    image: prom/prometheus:v2.51.0
    ports: ["9090:9090"]
    volumes: ["./prometheus.yml:/etc/prometheus/prometheus.yml"]
    restart: always

  grafana:
    image: grafana/grafana:10.4.0
    ports: ["3001:3000"]
    volumes: ["grafana_data:/var/lib/grafana"]
    restart: always

volumes:
  pgdata:
  natsdata:
  grafana_data:
```

## Appendix B: API Endpoint Inventory (Unified)

```
# System
GET    /health
GET    /api/system/mode
GET    /api/system/config
PUT    /api/system/config/reload
GET    /metrics                          # Prometheus

# Market Data
GET    /api/market/ticker/{symbol}
GET    /api/market/orderbook/{symbol}
GET    /api/market/kline/{symbol}
GET    /api/market/account
GET    /api/market/positions
GET    /api/market/trades
WS     /ws                               # Real-time updates

# Strategy
GET    /api/strategies
POST   /api/strategies
GET    /api/strategies/{id}
PUT    /api/strategies/{id}
DELETE /api/strategies/{id}

# Backtesting
POST   /api/backtests                    # Submit backtest job
GET    /api/backtests/{job_id}           # Job status + results
GET    /api/backtests/{job_id}/results   # Detailed results
GET    /api/backtests/history            # Past backtest runs

# Agents (NEW)
GET    /api/agents                       # List all agents
POST   /api/agents                       # Create agent
GET    /api/agents/{id}                  # Agent details + state
PUT    /api/agents/{id}                  # Update config
POST   /api/agents/{id}/start           # Advance to next stage
POST   /api/agents/{id}/pause           # Pause agent
POST   /api/agents/{id}/resume          # Resume agent
POST   /api/agents/{id}/retire          # Retire agent
GET    /api/agents/{id}/journal          # Decision audit trail
GET    /api/agents/{id}/performance      # Performance metrics
DELETE /api/agents/{id}                  # Delete retired agent

# Risk
GET    /api/risk/status                  # Current risk state
PUT    /api/risk/limits                  # Update risk limits
POST   /api/risk/kill-switch            # Emergency stop all
GET    /api/risk/alarms                  # Active alarms
POST   /api/risk/alarms/{id}/ack        # Acknowledge alarm

# Credentials (NEW)
POST   /api/vault/credentials            # Store encrypted credentials
GET    /api/vault/credentials            # List stored (metadata only)
DELETE /api/vault/credentials/{id}       # Remove credentials
POST   /api/vault/credentials/{id}/test  # Test exchange connection

# Signals (NEW)
POST   /api/webhook/tradingview          # TradingView alert ingestion
GET    /api/signals/history              # Signal history
PUT    /api/signals/config               # Auto-execution settings
```

## Appendix C: Migration Checklist

### Phase 1 Checklist
- [ ] Port `credentialVault.ts` → `src/security/credential_vault.py`
- [ ] Add `/api/vault/*` routes to FastAPI
- [ ] Add WebSocket endpoint (`/ws`) to FastAPI API server
- [ ] Complete backtest API routes (remove stubs, wire to engine)
- [ ] Complete market API routes (positions, trades, account)
- [ ] Complete strategy API routes (CRUD)
- [ ] Create `Dockerfile` for frontend (multi-stage: npm build → nginx)
- [ ] Add `frontend` service to `docker-compose.yml`
- [ ] Update React frontend: replace `localhost:3001` Express calls → `localhost:8000` FastAPI
- [ ] Update React frontend: replace all `localStorage.setItem/getItem` → REST API calls
- [ ] Add CORS middleware to FastAPI (allow frontend origin)
- [ ] Add API authentication (JWT or API key for remote access)
- [ ] Verify all Playwright E2E tests pass against new backend

### Phase 2 Checklist
- [ ] Create `src/services/agent_orchestrator.py`
- [ ] Create `src/copilot_proxy.py` (or `Dockerfile.proxy`)
- [ ] Add agent Pydantic models to `src/config.py`
- [ ] Add agent tables to database schema
- [ ] Create `/api/agents/*` routes
- [ ] Implement agent decision pipeline (observe → orient → decide → act → learn)
- [ ] Implement stage gates (backtest → paper → live)
- [ ] Wire agent to backtest service via NATS request/reply
- [ ] Implement portfolio-level risk constraints
- [ ] Add agent status to WebSocket broadcast
- [ ] Add agent management UI to React frontend

### Phase 3 Checklist
- [ ] Implement walk-forward optimizer in `tools/backtest.py`
- [ ] Implement Monte Carlo simulation module
- [ ] Wire BacktestDashboard to FastAPI backtest endpoints
- [ ] Strategy comparison with statistical significance
- [ ] Agent can programmatically submit + consume backtests

### Phase 4 Checklist
- [ ] Merge alarm types into Prometheus alerting rules
- [ ] Add Discord webhook notification channel
- [ ] Implement alert escalation pipeline
- [ ] Add remote kill switch (WebSocket + REST)
- [ ] Add agent decision audit trail (DB table + API)
- [ ] Set up encrypted daily DB backups
- [ ] Health check watchdog service

### Phase 5 Checklist (Optional)
- [ ] Create VPS-specific docker-compose override
- [ ] Set up WireGuard VPN tunnel
- [ ] Configure NATS leaf node
- [ ] Implement cold-start pre-warming
- [ ] Latency benchmarking (local vs. VPS)
