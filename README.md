# Crypto Trading Bot

A production-ready cryptocurrency trading bot with advanced strategy implementation, real-time monitoring, and backtesting capabilities.

## Features

- **Advanced Trading Strategy**: Regime detection, confidence scoring, ladder entries, dual stops
- **Risk Management**: Position sizing based on $1000 initial capital with 0.6% risk per trade
- **Real-time Dashboard**: Streamlit-based monitoring interface
- **Backtesting Engine**: Historical performance analysis with realistic execution
- **Database Persistence**: SQLite storage for trades, positions, and PnL tracking
- **Docker Support**: Containerized deployment with docker-compose
- **FastAPI Microservices**: Python-based execution, feed, risk, replay, reporter, and ops API services connected via NATS
- **Real-time Communication**: Publish-subscribe messaging for market data and trading signals
- **Production Readiness**: Comprehensive validation tools and automated CI/CD checks

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

2. **Open the dashboard**

   Visit `http://localhost:8501` — the header badge should display `MODE: PAPER`. Use the Paper Config panel to tune latency, slippage, fees, partial-fill behaviour, and margin guardrails (max_leverage, initial_margin_pct, maintenance_margin_pct); changes are applied via the ops-api.

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

### Environment Variables

Set the following environment variables for Zoomex API access:

```bash
export ZOOMEX_API_KEY="your_api_key"
export ZOOMEX_API_SECRET="your_api_secret"
export ZOOMEX_BASE="https://openapi-testnet.zoomex.com"  # Optional, defaults to prod
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

- `src/main.py` - Main trading engine with hot-reload
- `src/strategy.py` - Complete trading strategy implementation
- `src/exchange.py` - Exchange API integration (Bybit/Zoomex)
- `src/database.py` - SQLite persistence layer
- `src/indicators.py` - Technical analysis indicators
- `src/messaging.py` - NATS messaging system
- `src/services/` - FastAPI microservices (execution, feed, risk, reporter, replay)
- `dashboard/app.py` - Streamlit monitoring interface
- `tools/backtest.py` - Historical backtesting engine
- `tools/production_readiness_check.py` - Production readiness validation tool

## Production Readiness

The bot includes comprehensive production readiness validation tools:

### Quick Check
```bash
# Using Make
make readiness-check

# Or directly
python tools/production_readiness_check.py --mode paper
```

### Full Validation
```bash
# Generate detailed report
make readiness-report

# Run production tests
make test-production

# Pre-deployment checks
make pre-deploy
```

### Documentation
- **Full Guide**: `tools/README_PRODUCTION_READINESS.md`
- **Quick Reference**: `PRODUCTION_READINESS_QUICK_REF.md`
- **Current Status**: `PRODUCTION_STATUS.md`

### CI/CD Integration
The `.github/workflows/production-readiness.yml` workflow automatically validates:
- Configuration files
- Security (secrets, permissions)
- Test coverage
- Documentation completeness
- Docker configuration

## License

MIT License - see LICENSE file for details.

# Crypto Trading Bot

A production-ready cryptocurrency trading bot with advanced strategy implementation, real-time monitoring, and backtesting capabilities.

## 🚀 Quick Start for Zoomex Perpetual Futures

**For production-ready Zoomex perps trading, see [README_TRADING.md](README_TRADING.md)**

The trading guide includes:
- Complete setup instructions
- Configuration examples
- Risk management guidelines
- Paper/testnet/live trading modes
- Monitoring and safety procedures

Quick commands:
```bash
# Setup
./setup.sh

# Validate configuration
python tools/validate_setup.py --config configs/zoomex_example.yaml

# Paper trading (simulated)
python run_bot.py --mode paper --config configs/zoomex_example.yaml

# Testnet trading (fake money)
python run_bot.py --mode testnet --config configs/zoomex_example.yaml

# Backtest strategy
python tools/backtest_perps.py --symbol SOLUSDT --start 2024-01-01 --end 2024-12-31

# Monitor live
python tools/monitor.py --config configs/zoomex_example.yaml --mode testnet
```

---

## Features

- **Advanced Trading Strategy**: Regime detection, confidence scoring, ladder entries, dual stops
- **Strategy Studio**: No-code interface for building, backtesting, and managing dynamic strategies
- **Risk Management**: Position sizing based on $1000 initial capital with 0.6% risk per trade
- **Real-time Dashboard**: Streamlit-based monitoring interface
- **Backtesting Engine**: Historical performance analysis with realistic execution
- **Database Persistence**: SQLite storage for trades, positions, and PnL tracking
- **Docker Support**: Containerized deployment with docker-compose
- **FastAPI Microservices**: Python-based execution, feed, risk, replay, reporter, and ops API services connected via NATS
- **Real-time Communication**: Publish-subscribe messaging for market data and trading signals

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

2. **Open the dashboard**

   Visit `http://localhost:8501` — the header badge should display `MODE: PAPER`. Use the Paper Config panel to tune latency, slippage, fees, partial-fill behaviour, and margin guardrails (max_leverage, initial_margin_pct, maintenance_margin_pct); changes are applied via the ops-api.

3. **Backtest and replay the strategy**

   ```bash
   python tools/backtest.py --symbol BTCUSDT --start 2023-01-01 --end 2024-01-01
   ```

   For deterministic market replay at 10× speed on BTC/ETH, set `paper.price_source: "replay"` and `replay.source: "parquet://sample_data/btc_eth_4h.parquet"` in `config/strategy.yaml`, then:

   ```bash
   APP_MODE=replay docker compose up --build
   ```

   The replay service will stream the bundled Parquet data over NATS while the paper broker records fills, funding, and PnL.

4. **Use the Strategy Studio**

   Build and backtest strategies without writing code:

   ```bash
   # Start the API server
   python src/server.py

   # Start the frontend (in a separate terminal)
   cd frontend
   npm run dev
   ```

   Visit `http://localhost:3000/strategy-studio` to create and test your strategies.


### Backtesting

Run backtests on historical data:

```bash
# Basic backtest
python tools/backtest_perps.py --symbol BTCUSDT --start 2024-11-01 --end 2024-11-30

# With custom initial balance
python tools/backtest_perps.py --symbol BTCUSDT --start 2024-11-01 --end 2024-11-30 --initial-balance 5000

# Save results to JSON
python tools/backtest_perps.py --symbol BTCUSDT --start 2024-11-01 --end 2024-11-30 --output results.json
```

**Troubleshooting backtests:**

If you encounter issues like "Backtest returned an empty result" or no signals:

```bash
# Run diagnostic tool
python tools/diagnose_backtest.py --symbol BTCUSDT --days 30
```

See [BACKTEST_TROUBLESHOOTING.md](BACKTEST_TROUBLESHOOTING.md) for detailed solutions to common issues.

### Testing

Run unit tests:
```bash
pytest tests/test_indicators.py
pytest tests/test_perps_executor.py
pytest tests/test_zoomex_client.py
