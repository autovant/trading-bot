# Trading Bot AI Coding Conventions

This document provides essential guidance for AI agents working on this trading bot codebase.

## Architecture Overview

The system is a hybrid architecture combining a monolithic Python application for the core trading logic with a set of Go-based microservices for peripheral tasks.

- **Python Core (`src/`)**: The main application (`src/main.py`) orchestrates the trading strategy. It's responsible for:

  - Loading configuration (`src/config.py`)
  - Connecting to the exchange (`src/exchange.py`)
  - Executing the trading strategy (`src/strategy.py`)
  - Storing data in a SQLite database (`src/database.py`)
  - Communicating with Go services via NATS messaging (`src/messaging.py`).

- **Go Microservices (`*.go`)**: These services handle specific, decoupled tasks like handling the data feed (`feed_handler.go`), executing trades (`execution_service.go`), managing risk (`risk_state.go`), reporting (`reporter.go`), and providing an operational API (`ops_api.go`). They communicate with each other and the Python core via NATS.

- **Dashboard (`dashboard/app.py`)**: A Streamlit application for real-time monitoring of the bot's performance.

- **Data (`data/`)**: Contains the SQLite database files. `test.db` is for general testing, and `integration_test.db` is for integration tests.

## Key Files

- `src/main.py`: The entry point of the Python application.
- `src/strategy.py`: Contains the core trading logic. This is where you'll spend most of your time when modifying the strategy.
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

## Conventions

- **Configuration**: All configuration is managed through `config/strategy.yaml`. Do not hardcode values. The `src/config.py` module loads this configuration.
- **Database**: The application uses SQLite for data storage. The schema is defined and managed in `src/database.py`.
- **Messaging**: NATS is used for communication between the Python core and the Go microservices. The messaging logic is in `src/messaging.py`.
- **Code Style**: The Python code follows the PEP 8 style guide. Use a linter to ensure compliance.
- **Go Services**: The Go services are designed to be small and single-purpose. They are managed via the `docker-compose.yml` file.
