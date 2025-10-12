# Gemini Project: Trading-bot

This document provides instructions and context for the Trading-bot project.

## Project Overview

This is a production-ready cryptocurrency trading bot with advanced strategy implementation, real-time monitoring, and backtesting capabilities.

### Core Features:
- **Advanced Trading Strategy**: Regime detection, confidence scoring, ladder entries, dual stops.
- **Risk Management**: Position sizing based on $1000 initial capital with 0.6% risk per trade.
- **Real-time Dashboard**: Streamlit-based monitoring interface.
- **Backtesting Engine**: Historical performance analysis with realistic execution.
- **Database Persistence**: SQLite storage for trades, positions, and PnL tracking.
- **Docker Support**: Containerized deployment with docker-compose.
- **Microservices Architecture**: NATS messaging with feed handler, execution, risk state, reporter, and ops API services.
- **Real-time Communication**: Publish-subscribe messaging for market data and trading signals.

### Core Technologies:
- **Backend**: Python 3.11+, Go
- **Dashboard**: Streamlit
- **Database**: SQLite
- **Messaging**: NATS
- **Deployment**: Docker

## Project Structure

- `src/main.py`: Main trading engine with hot-reload.
- `src/strategy.py`: Complete trading strategy implementation.
- `src/exchange.py`: Exchange API integration (Bybit/Binance fallback).
- `src/database.py`: SQLite persistence layer.
- `src/indicators.py`: Technical analysis indicators.
- `src/messaging.py`: NATS messaging system.
- `dashboard/app.py`: Streamlit monitoring interface.
- `tools/backtest.py`: Historical backtesting engine.
- `*.go`: Go microservices (feed handler, execution, risk state, reporter, ops API).
- `config/strategy.yaml`: Configuration file for the trading strategy.
- `docker-compose.yml`: Docker compose file for deployment.
- `requirements.txt`: Python dependencies.
- `go.mod`: Go dependencies.

## How to Run

### Local Development

1.  **Setup Environment**:
    ```bash
    python -m venv venv
    # On Windows: venv\Scripts\activate
    # On Unix/MacOS: source venv/bin/activate
    pip install -r requirements.txt
    ```

2.  **Configure**:
    - Edit `config/strategy.yaml` with your exchange API credentials.

3.  **Run Trading Bot**:
    ```bash
    python src/main.py
    ```

4.  **Run Dashboard**:
    ```bash
    streamlit run dashboard/app.py
    ```

### Docker Deployment

```bash
docker-compose up -d
```

## How to Test

### Backtesting

```bash
python tools/backtest.py --symbol BTCUSDT --start 2023-01-01 --end 2024-01-01
```

### Integration Tests

The project contains `test_integration.py` and `test_messaging.py`. You can run them using `pytest`.

```bash
pytest
```
## Strategy

The trading strategy is based on:
1. **Regime Detection** (Daily): Volatility and trend filters.
2. **Setup Detection** (4H): Moving average stack and ADX strength.
3. **Signal Generation** (1H): Pullback and breakout patterns.
4. **Confidence Scoring**: 0-100 scale with weighted factors.
5. **Position Sizing**: Risk-based allocation with ladder entries.
6. **Risk Management**: Dual stop system (soft + hard stops).

See `STRATEGY.md` for detailed strategy documentation.
