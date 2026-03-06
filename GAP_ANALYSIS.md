# Inventory & Gap Analysis

## 1. Inventory

### Backend (`src/`)
- **Exchange Layer**: `ExchangeClient` (`src/exchange.py`) correctly abstracts `live` vs `paper` modes.
- **Paper Trading**: `PaperBroker` (`src/paper_trader.py`) is a robust, high-fidelity simulator (latency, slippage, partial fills). Verified with unit tests.
- **API**: ~~`src/api_server.py`~~ → `[RESOLVED]` Now `src/api/main.py` (FastAPI unified API server, port 8000) with 14 route modules: `agents`, `auth`, `backtest`, `data`, `intelligence`, `market`, `notifications`, `portfolio`, `presets`, `risk`, `signals`, `strategy`, `system`, `vault`. WebSocket at `/ws`.
- **Strategy Engine**: `DynamicStrategyEngine` (`src/dynamic_strategy.py`) allows execution of JSON-configured strategies.
- **Main Engine**: `src/main.py` orchestrates the trading loop and handles config reloading.
- **Microservices** `[NEW]`: `src/services/` — execution (8080), feed (8081), reporter (8083), risk (8084), replay (8085), signal_engine (8086), llm_proxy (8087), agent_orchestrator (8088).
- **Security** `[NEW]`: `src/security/credential_vault.py` — AES-256-GCM credential vault.
- **Risk** `[NEW]`: `src/risk/portfolio_risk.py` — portfolio-level risk with correlation and concentration limits.
- **Notifications** `[NEW]`: `src/notifications/` — Discord + Telegram webhook integration, alert escalation.

### Tools (`tools/`)
- **Backtester**: `BacktestEngine` (`tools/backtest.py`) exists but has significant issues (see Gaps).

### Frontend (`trading-bot-ai-studio/`)
- **Architecture**: `[RESOLVED]` Migrated from Next.js to React 19 + Vite 6 + Tailwind v4. State managed via `@tanstack/react-query` hooks + local React state.
- **Components**: `[RESOLVED]` Full component suite: ChartWidget, OrderBook, OrderForm, StrategyBuilder, BacktestDashboard, AgentManager, PortfolioDashboard, SignalsPanel, PresetLibrary, TradeJournal, DataManager, SettingsView, RiskSettings, AIAssistant.
- **Safety**: `[RESOLVED]` `wsClient.ts` handles WebSocket lifecycle with auto-reconnect. `MarketStream` service for direct Bybit data. `ExecutionService` for client-side execution pipeline with idempotency and fill ledger.

## 2. Gaps & Issues

### Critical
1.  **Backtester Discrepancy**:
    - `tools/backtest.py` implements its **own simplified simulation logic** (`_update_positions`, `_close_position`).
    - It **does not** use the `PaperBroker` used by the live/paper mode.
    - **Requirement Violation**: "Uses the same paper execution engine as live/paper mode".
    - **Risk**: Backtest results will not match paper/live performance.
    - **Status**: Open — `src/api/routes/backtest.py` delegates to `tools.backtest.run_backtest` which still uses its own logic.

2.  **Backtester Data Fetching**:
    - `BacktestEngine` initializes `ExchangeClient` in `live` mode to fetch data. This is risky and conceptually wrong for a pure backtest environment.
    - **Status**: Open — needs refactor to use stored Parquet data or a dedicated data-fetch path.

3.  **Strategy Builder Integration**: `[RESOLVED]`
    - End-to-end API chain now exists: Frontend `StrategyBuilder` → `backendApi.createStrategy()` → `POST /api/strategies` → `DatabaseManager`. Strategies can be created, updated, activated, deactivated, and used in backtests via `POST /api/backtests`.
    - `DynamicStrategyEngine` is integrated. 14 API route modules mounted in `src/api/main.py`.

### High Priority
4.  **Frontend Wiring**: `[RESOLVED]`
    - Old Next.js frontend (`BotControlModal`, `ManualTradePanel`) replaced entirely by `trading-bot-ai-studio/`. New `OrderForm` component calls `backendApi.placeOrder()` → `POST /api/orders`. Bot start/stop via `POST /api/bot/start` and `/api/bot/stop`. All UI components are wired to real FastAPI endpoints through `services/backend.ts`.

5.  **Configuration**: `[RESOLVED]`
    - `config/strategy.yaml` is the single source — loaded and validated by Pydantic in `src/config.py`. Hot-reloadable via `POST /api/bot/start` / `POST /api/bot/stop` which call `reload_config()`. API routes read from config (e.g., `GET /api/mode` returns `config.app_mode`).

## 3. Plan of Action (Summary)

1.  **Refactor Backtester** (Open): Rewrite `BacktestEngine` to feed historical data into `PaperBroker` instead of using internal simulation logic.
2.  **Unify Strategy Config**: `[RESOLVED]` — `config/strategy.yaml` (Pydantic-validated) is the single source. DB-stored strategies are separate user-created configs.
3.  **Wire Frontend**: `[RESOLVED]` — New React frontend fully wired to FastAPI backend via `services/backend.ts` REST + WebSocket.
4.  **Harden Safety**: `[RESOLVED]` — Kill switch implemented (`POST /api/risk/kill-switch`), mode guard in `src/security/`, API key auth middleware, credential vault.
