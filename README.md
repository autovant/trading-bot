# Crypto Trading Bot

A production-ready cryptocurrency trading platform with an advanced strategy engine, AI agent orchestration, real-time React UI, and comprehensive backtesting.

## Features

- **Advanced Trading Strategy**: Multi-timeframe regime detection, confidence scoring, ladder entries, dual stops
- **AI Agent Framework**: Autonomous agents with OODA decision loop, lifecycle management (CREATE → BACKTEST → PAPER → LIVE → RETIRE)
- **Risk Management**: Portfolio-level risk, per-agent controls, crisis mode, kill switch, correlation limits
- **React Trading Workstation**: Institutional-grade UI with market view, strategy builder, backtest playback, agent management, order book, signals panel, trade journal
- **Credential Vault**: AES-256-GCM encrypted at rest, secure API key management
- **FastAPI Microservices**: Execution, feed, risk, reporter, replay, signal engine, LLM proxy, agent orchestrator — all connected via NATS
- **Backtesting Engine**: Walk-forward optimization, Monte Carlo simulation, strategy comparison
- **Signal Processing**: TradingView webhook ingestion, signal scoring, auto-execution
- **Real-time Communication**: NATS pub/sub + WebSocket bridge for live UI updates
- **Docker Orchestration**: 13+ services via docker-compose, with VPS deployment option
- **Monitoring**: Prometheus + Grafana dashboards, Discord alert escalation
- **Database**: PostgreSQL (TimescaleDB) with SQLite fallback for dev/testing

## Quickstart

1. **Boot the full stack in paper mode**

   ```bash
   APP_MODE=paper docker compose up --build
   ```

   This assembles Postgres, NATS, strategy-engine, execution (`uvicorn src.services.execution:app`), feature-engine (mock feed), ops-api, dash, reporter, risk-state, replay, Prometheus, and Grafana with the paper broker active (no exchange keys required).
   Core FastAPI health endpoints:
   - Execution: `http://localhost:8080/health`
   - Feed: `http://localhost:8081/health`
   - Ops API: `http://localhost:8082/health`
   - Reporter: `http://localhost:8083/health`
   - Risk: `http://localhost:8084/health`
   - Replay: `http://localhost:8085/health`

2. **Open the Dashboard**

   **React Trading Workstation (Recommended)**:
   Navigate to the `trading-bot-ai-studio/` directory (sibling folder), run `npm install` and `npm run dev`. Visit `http://localhost:5173`.
   
   Or use Docker Compose which serves the frontend via nginx at `http://localhost:8080`.

3. **Backtest and replay the strategy**

   ```bash
   python tools/backtest.py --symbol BTCUSDT --start 2023-01-01 --end 2024-01-01
   ```

   For deterministic market replay at 10× speed on BTC/ETH, set `paper.price_source: "replay"` and `replay.source: "parquet://sample_data/btc_eth_4h.parquet"` in `config/strategy.yaml`, then:

   ```bash
   APP_MODE=replay docker compose up --build
   ```

   The replay service will stream the bundled Parquet data over NATS while the paper broker records fills, funding, and PnL.


## Configuration

Edit `config/strategy.yaml` to customize (or use the **Strategy Control → Advanced** editor in the Streamlit dashboard—changes are written back to disk automatically):
- Exchange provider + API credentials (set `exchange.provider` to `bybit` or `zoomex`; override `exchange.base_url` for custom endpoints). The **Dashboard → Strategy Control** tab lets you flip between paper/live modes, toggle shadow trading, and update API keys/testnet flags directly—changes are written back to `config/strategy.yaml`.
- Trading parameters
- Risk management settings
- Strategy weights and thresholds
- Paper trading and replay settings (fees, slippage, latency, partial fills, margin guardrails)

## Perpetual Futures Strategy

The bot now includes a **perpetual futures (perps) strategy** module for USDT-margined contracts with:

### Features

- **Exchange-resident TP/SL**: Take-profit and stop-loss orders placed directly on the exchange
- **Risk-based position sizing**: Automatic position sizing based on equity and risk percentage
- **Candle-close execution**: Only trades on closed candles to avoid repainting
- **Trend-following signals**: SMA crossover + VWAP + RSI filters
- **Idempotent orders**: Unique order IDs to prevent double-fills on retries
- **Leverage control**: Configurable leverage (1x by default)
- **Early exit**: Optional reduce-only exit on trend reversal
- **Circuit breaker**: Optional consecutive loss limit

### Configuration

Enable and configure perps trading in `config/strategy.yaml`:

```yaml
perps:
  enabled: true              # Toggle perps strategy on/off
  exchange: zoomex           # Currently supports Zoomex
  symbol: "SOLUSDT"          # Trading symbol (no slash)
  interval: "5"              # Candle interval (5 minutes)
  leverage: 1                # Leverage multiplier
  mode: "oneway"             # "oneway" or "hedge"
  positionIdx: 0             # 0 for oneway, 1 for long/2 for short in hedge
  riskPct: 0.005             # Risk 0.5% of equity per trade
  stopLossPct: 0.01          # 1% stop-loss distance
  takeProfitPct: 0.03        # 3% take-profit distance
  cashDeployCap: 0.20        # Max 20% of equity per position
  triggerBy: "LastPrice"     # "LastPrice", "MarkPrice", or "IndexPrice"
  earlyExitOnCross: false    # Exit on MA bear cross
  useTestnet: true           # Use testnet for testing
  consecutiveLossLimit: null # Circuit breaker (null = disabled)
```

### Alert Configuration

The bot supports sending alerts via webhooks (e.g., to Slack, Discord, or generic HTTP endpoints).

Set the `ALERT_WEBHOOK_URL` environment variable:

```bash
export ALERT_WEBHOOK_URL="https://discord.com/api/webhooks/..."
```

### Websocket Integration (Limited Live Ready)

For lower latency order updates in `live` or `testnet` modes, the bot uses a direct websocket connection to the exchange (currently supports Bybit/Zoomex).

- **Enabled automatically** when `APP_MODE` is `live` or `testnet` and the exchange is `bybit` (or compatible).
- **Requires**: Standard API credentials (`EXCHANGE_API_KEY`, `EXCHANGE_SECRET_KEY`) set in environment.

### Environment Variables

Set the following environment variables for API access:

```bash
export EXCHANGE_API_KEY="your_api_key"
export EXCHANGE_SECRET_KEY="your_api_secret"
export ZOOMEX_BASE="https://openapi-testnet.zoomex.com"  # Optional
export ALERT_WEBHOOK_URL="https://your-webhook-url"      # Optional, for alerts
```

### Strategy Rules

**Entry (LONG only)**:
- Bull crossover: `fast_ma(10)` crosses above `slow_ma(30)`
- Price above VWAP
- RSI between 30 and 65 (fresh trend filter)

**Exit**:
- Take-profit at entry × (1 + takeProfitPct)
- Stop-loss at entry × (1 - stopLossPct)
- Optional early exit on bear crossover if `earlyExitOnCross: true`

**Position Sizing**:
```
risk_dollars = equity × riskPct
notional = risk_dollars / stopLossPct
usd_to_deploy = min(notional, equity × cashDeployCap)
qty_base = usd_to_deploy / entry_price
```

### Running on Testnet

1. **Get Zoomex testnet credentials** from https://testnet.zoomex.com
2. **Set environment variables**:
   ```bash
   export ZOOMEX_API_KEY="test_key"
   export ZOOMEX_API_SECRET="test_secret"
   ```
3. **Enable in config**: Set `perps.enabled: true` and `perps.useTestnet: true`
4. **Run the bot**:
   ```bash
   python src/main.py
   ```
5. **Monitor** logs for entry signals, TP/SL placement, and fills
6. **Verify** on Zoomex UI that orders appear with TP/SL attached

### Testing

Run unit tests:
```bash
pytest tests/test_indicators.py
pytest tests/test_perps_executor.py
pytest tests/test_zoomex_client.py
```

### Safety Notes

- **Start with testnet** to validate behavior before going live
- **Use low leverage** (1x recommended for testing)
- **Monitor circuit breaker**: Set `consecutiveLossLimit` to prevent runaway losses
- **Verify precision**: The bot automatically rounds quantities to market precision
- **Check logs**: All entry/exit decisions are logged with R:R ratios


## Architecture

The system is a **unified trading platform** combining a Python microservices backend with a React/Vite institutional-grade frontend.

- `src/main.py` — Main trading engine with hot-reload
- `src/strategy.py` — Complete trading strategy implementation
- `src/exchange.py` — Exchange API integration (Bybit/Zoomex via CCXT)
- `src/database.py` — PostgreSQL (TimescaleDB) + SQLite persistence
- `src/indicators.py` — Technical analysis indicators
- `src/messaging.py` — NATS messaging system
- `src/api/` — FastAPI unified API server (port 8000) with REST + WebSocket
- `src/api/routes/` — REST endpoints: agents, backtest, market, risk, signals, strategy, vault, system, data, presets
- `src/api/ws.py` — WebSocket manager with NATS bridge for real-time UI updates
- `src/services/` — FastAPI microservices (execution, feed, risk, reporter, replay, signal engine, LLM proxy, agent orchestrator)
- `src/security/` — AES-256-GCM credential vault, mode guard
- `src/risk/` — Portfolio-level risk manager, per-agent controls
- `src/backtest/` — Walk-forward optimizer, Monte Carlo simulation
- `src/notifications/` — Discord webhooks, alert escalation
- `trading-bot-ai-studio/` — React 19 + Vite 6 + Tailwind v4 frontend (served via nginx)
- `tools/backtest.py` — Historical backtesting engine

See [SERVICES.md](SERVICES.md) for the full service registry and ports.

## Production Readiness

- Quick check: `python tools/production_readiness_check.py --mode paper --strict`
- Test suite: `python -m pytest tests/test_production_readiness.py -q`
- Service status: [STATUS.md](STATUS.md)
- Service registry: [SERVICES.md](SERVICES.md)
- Architecture: [docs/UNIFIED_ARCHITECTURE.md](docs/UNIFIED_ARCHITECTURE.md)
- Implementation plan: [plans/unified-platform-plan.md](plans/unified-platform-plan.md)
- Deployment guide: [DEPLOYMENT.md](DEPLOYMENT.md)

## License

MIT License - see LICENSE file for details.
