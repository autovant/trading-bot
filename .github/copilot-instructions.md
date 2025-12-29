# Trading Bot AI Coding Conventions

This document provides essential guidance for AI agents working on this trading bot codebase.

## Architecture Overview

The system is a microservices architecture combining a Python strategy engine with a set of Python FastAPI microservices for peripheral tasks.

- **Python Core (`src/`)**: The main application (`src/main.py`) orchestrates the trading strategy. It's responsible for:

  - Loading configuration (`src/config.py`)
  - Connecting to the exchange (`src/exchange.py`)
  - Executing the trading strategy (`src/strategy.py`)
  - Storing data in a SQLite database (`src/database.py`)
  - Communicating with microservices via NATS messaging (`src/messaging.py`).

- **Python FastAPI Microservices (`src/services/`)**: These services handle specific, decoupled tasks:
  - `execution.py` - Processes order intents, forwards to PaperBroker for simulation, publishes execution reports (port 8080)
  - `feed.py` - Fetches live ticker and order book data from exchanges, publishes to NATS (port 8081)
  - `risk.py` - Emits risk metrics and circuit breaker status (port 8084)
  - `reporter.py` - Aggregates performance metrics and publishes summary reports (port 8083)
  - `replay.py` - Streams historical market data from Parquet files for backtesting (port 8085)
  
  All services communicate with each other and the Python core via NATS messaging.

- **API Server (`src/api/`)**: A FastAPI application providing REST endpoints for strategy control, market data, backtesting, and system management (port 8000).

- **Dashboard (`dashboard/app.py`)**: A Streamlit application for real-time monitoring of the bot's performance (port 8501).

- **Data (`data/`)**: Contains the SQLite database files. `test.db` is for general testing, and `integration_test.db` is for integration tests.

## Key Files

- `src/main.py`: The entry point of the Python strategy engine.
- `src/strategy.py`: Contains the core trading logic. This is where you'll spend most of your time when modifying the strategy.
- `src/services/`: Python FastAPI microservices for execution, feed, risk, reporting, and replay.
- `src/api/`: REST API server for external control and monitoring.
- `config/strategy.yaml`: The main configuration file. All strategy parameters, API keys, and other settings are defined here.
- `docker-compose.yml`: Defines the services for containerized deployment.
- `tools/backtest.py`: The backtesting engine. Use this to test strategy changes on historical data.

## Developer Workflow

### Running the Bot

1.  **Activate the virtual environment**:
    ```bash
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    ```
2.  **Run the main application**:
    ```bash
    python src/main.py
    ```
3.  **Run the dashboard**:
    ```bash
    streamlit run dashboard/app.py
    ```

### Testing

- **Unit Tests**: The main unit tests for the strategy are in `tests/test_strategy.py`. Run them with `pytest`.
- **Integration Tests**: `test_integration.py` runs integration tests.
- **Backtesting**: To test strategy changes, use the backtesting tool:
  ```bash
  python tools/backtest.py --symbol BTCUSDT --start 2023-01-01 --end 2024-01-01
  ```

### Docker

The application is fully containerized. To run all services:

```bash
docker-compose up -d
```

This starts:
- PostgreSQL database (TimescaleDB)
- NATS messaging server
- Strategy engine (main trading logic)
- FastAPI microservices (execution, feed, risk, reporter, replay)
- API server (REST endpoints)
- Streamlit dashboard
- Prometheus and Grafana (monitoring)

## Conventions

- **Configuration**: All configuration is managed through `config/strategy.yaml`. Do not hardcode values. The `src/config.py` module loads this configuration.
- **Database**: The application uses SQLite for data storage. The schema is defined and managed in `src/database.py`.
- **Messaging**: NATS is used for communication between the Python core and the FastAPI microservices. The messaging logic is in `src/messaging.py`.
- **Code Style**: The Python code follows the PEP 8 style guide. Use a linter to ensure compliance.
- **Microservices**: The Python FastAPI microservices are designed to be small and single-purpose. They are managed via the `docker-compose.yml` file and expose health check endpoints at `/health`.
