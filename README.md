# Crypto Trading Bot

A production-ready cryptocurrency trading bot with advanced strategy implementation, real-time monitoring, and backtesting capabilities.

## Features

- **Advanced Trading Strategy**: Regime detection, confidence scoring, ladder entries, dual stops
- **Risk Management**: Position sizing based on $1000 initial capital with 0.6% risk per trade
- **Real-time Dashboard**: Streamlit-based monitoring interface
- **Backtesting Engine**: Historical performance analysis with realistic execution
- **Database Persistence**: SQLite storage for trades, positions, and PnL tracking
- **Docker Support**: Containerized deployment with docker-compose
- **Microservices Architecture**: NATS messaging with feed handler, execution, risk state, reporter, and ops API services
- **Real-time Communication**: Publish-subscribe messaging for market data and trading signals

## Quickstart

1. **Boot the full stack in paper mode**

   ```bash
   APP_MODE=paper docker compose up --build
   ```

   This assembles Postgres, NATS, strategy-engine, execution, feature-engine, ops-api, dash, reporter, replay, Prometheus, and Grafana with the paper broker active (no exchange keys required).

2. **Open the dashboard**

   Visit `http://localhost:8501` — the header badge should display `MODE: PAPER`. Use the Paper Config panel to tune latency, slippage, fees, and partial-fill behaviour; changes are applied via the ops-api.

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

Edit `config/strategy.yaml` to customize:
- Exchange API credentials (for live mode)
- Trading parameters
- Risk management settings
- Strategy weights and thresholds
- Paper trading and replay settings

## Architecture

- `src/main.py` - Main trading engine with hot-reload
- `src/strategy.py` - Complete trading strategy implementation
- `src/exchange.py` - Exchange API integration (Bybit/Binance fallback)
- `src/database.py` - SQLite persistence layer
- `src/indicators.py` - Technical analysis indicators
- `src/messaging.py` - NATS messaging system
- `dashboard/app.py` - Streamlit monitoring interface
- `tools/backtest.py` - Historical backtesting engine
- `*.go` - Go microservices (feed handler, execution, risk state, reporter, ops API, replay)

## License

MIT License - see LICENSE file for details.
