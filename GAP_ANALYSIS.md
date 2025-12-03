# Inventory & Gap Analysis

## 1. Inventory

### Backend (`src/`)
- **Exchange Layer**: `ExchangeClient` (`src/exchange.py`) correctly abstracts `live` vs `paper` modes.
- **Paper Trading**: `PaperBroker` (`src/paper_trader.py`) is a robust, high-fidelity simulator (latency, slippage, partial fills). Verified with unit tests.
- **API**: `src/api_server.py` provides endpoints for:
    - Backtesting (`/api/backtest`)
    - Strategy Management (`/api/strategies`)
    - Mode Switching (`/api/mode`)
    - Market Data & Account Info (via WS and REST)
- **Strategy Engine**: `DynamicStrategyEngine` (`src/dynamic_strategy.py`) allows execution of JSON-configured strategies.
- **Main Engine**: `src/main.py` orchestrates the trading loop and handles config reloading.

### Tools (`tools/`)
- **Backtester**: `BacktestEngine` (`tools/backtest.py`) exists but has significant issues (see Gaps).

### Frontend (`frontend/`)
- **Architecture**: Modern Next.js app with solid Context-based state management (`AccountContext`, `MarketDataContext`).
- **Components**:
    - `StrategyControlPanel` and `StrategyBuilder` exist.
    - `BotControlModal` and `ManualTradePanel` are implemented but need wiring verification.
- **Safety**: `useWebSocket` hook handles connection lifecycle.

## 2. Gaps & Issues

### Critical
1.  **Backtester Discrepancy**:
    - `tools/backtest.py` implements its **own simplified simulation logic** (`_update_positions`, `_close_position`).
    - It **does not** use the `PaperBroker` used by the live/paper mode.
    - **Requirement Violation**: "Uses the same paper execution engine as live/paper mode".
    - **Risk**: Backtest results will not match paper/live performance.

2.  **Backtester Data Fetching**:
    - `BacktestEngine` initializes `ExchangeClient` in `live` mode to fetch data. This is risky and conceptually wrong for a pure backtest environment.

3.  **Strategy Builder Integration**:
    - `DynamicStrategyEngine` is implemented, but end-to-end integration from Frontend -> API -> Database -> Execution Engine needs verification.
    - "Divergence" indicator logic in `dynamic_strategy.py` is complex and potentially incomplete/slow for Python iteration.

### High Priority
4.  **Frontend Wiring**:
    - `BotControlModal` and `ManualTradePanel` likely use stubs or `console.log`. Need to ensure they call real endpoints (`/api/orders`, `/api/bot/start`).

5.  **Configuration**:
    - Need to ensure `config/strategy.yaml` and database-stored strategies are synchronized or clearly distinguished.

## 3. Plan of Action (Summary)

1.  **Refactor Backtester** (In Progress): Rewrite `BacktestEngine` to feed historical data into `PaperBroker` instead of using internal simulation logic.
2.  **Unify Strategy Config**: Ensure `DynamicStrategyEngine` is the single source of truth for strategy logic in all modes.
3.  **Wire Frontend**: Connect UI components to backend endpoints and verify end-to-end flow.
4.  **Harden Safety**: Implement "Kill Switch" and strict mode enforcement.
