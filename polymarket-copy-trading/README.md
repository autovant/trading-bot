# Polymarket Copy Trading Bot

Automatically mirror trades from top Polymarket prediction-market wallets. Monitor source wallets, size positions intelligently, enforce risk limits, and execute orders through Polymarket's CLOB API — all in real time.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Copy Trading Bot                         │
│                                                             │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌─────────┐ │
│  │  Trade    │──▶│   Copy   │──▶│   Risk   │──▶│ Order   │ │
│  │  Monitor  │   │  Engine  │   │  Manager │   │ Executor│ │
│  └──────────┘   └──────────┘   └──────────┘   └─────────┘ │
│       │                                             │       │
│       ▼                                             ▼       │
│  ┌──────────┐                                ┌──────────┐  │
│  │Polymarket│                                │  Trade   │  │
│  │  Client  │                                │  Store   │  │
│  └──────────┘                                └──────────┘  │
└─────────────────────────────────────────────────────────────┘
```

**Pipeline:**

1. **Trade Monitor** — Polls source wallets via the Polymarket CLOB API for new trades
2. **Copy Engine** — Converts detected trades into sized copy signals (proportional or fixed)
3. **Risk Manager** — Enforces per-position limits, portfolio exposure caps, price bounds, daily loss limits, and a consecutive-loss circuit breaker
4. **Order Executor** — Places limit orders on Polymarket's CLOB (or logs them in dry-run mode)
5. **Trade Store** — Persists all trade history and statistics in SQLite

## Quick Start

### 1. Install Dependencies

```bash
cd polymarket-copy-trading
pip install -r requirements.txt
```

### 2. Configure

```bash
# Copy and edit the example environment file
cp .env.example .env

# Required: add your wallet private key and source wallets
# POLYMARKET_PRIVATE_KEY=0x...
# SOURCE_WALLETS=0xwallet1,0xwallet2
```

Edit `config/default.yaml` for detailed settings (sizing mode, risk limits, polling interval, etc.).

### 3. Validate Configuration

```bash
python -m src validate
```

### 4. Run (Dry Run)

```bash
# Dry run — logs trades without placing real orders
python -m src start --dry-run
```

### 5. Run (Live)

```bash
# ⚠️  Live mode — places real orders with real funds
python -m src start --live
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `python -m src start --dry-run` | Start bot in dry-run mode |
| `python -m src start --live` | Start bot in live mode |
| `python -m src start -w 0xWALLET` | Monitor specific wallet(s) |
| `python -m src history` | Show recent trade history |
| `python -m src stats` | Show aggregate statistics |
| `python -m src validate` | Validate config and connectivity |

## Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `POLYMARKET_PRIVATE_KEY` | Yes (for live) | Wallet private key for signing orders |
| `POLYMARKET_CHAIN_ID` | No | Polygon chain ID (default: 137) |
| `SOURCE_WALLETS` | Yes | Comma-separated wallet addresses to copy |
| `DATABASE_URL` | No | SQLite database path |
| `LOG_LEVEL` | No | Logging level (DEBUG, INFO, WARNING) |

### YAML Config (`config/default.yaml`)

```yaml
# Sizing: "proportional" (mirror size × multiplier) or "fixed" (flat USDC amount)
copy:
  sizing_mode: proportional
  size_multiplier: 1.0
  fixed_size_usdc: 10.0
  copy_sells: true

# Risk limits
risk:
  max_position_size_usdc: 100.0
  max_portfolio_exposure_usdc: 500.0
  max_open_positions: 20
  slippage_tolerance_pct: 2.0
  daily_loss_limit_usdc: 50.0
  max_consecutive_losses: 5
```

## Docker

```bash
# Build and run in dry-run mode
docker compose up --build

# Run in live mode
docker compose run copy-trader start --live
```

## Development

### Run Tests

```bash
pip install -r requirements.txt
cd polymarket-copy-trading
pytest tests/ -v
```

### Project Structure

```
polymarket-copy-trading/
├── config/default.yaml       # Default configuration
├── src/
│   ├── __init__.py
│   ├── __main__.py           # python -m src entry point
│   ├── app.py                # Main application orchestrator
│   ├── cli.py                # Click CLI (start, history, stats, validate)
│   ├── client.py             # Polymarket API client wrapper
│   ├── config.py             # Pydantic config with YAML + env loading
│   ├── copy_engine.py        # Trade signal processing and sizing
│   ├── executor.py           # Order placement (dry-run + live)
│   ├── models.py             # Data models (SourceTrade, CopiedTrade, etc.)
│   ├── monitor.py            # Wallet polling and trade detection
│   ├── persistence.py        # SQLite trade history storage
│   └── risk_manager.py       # Risk checks, limits, circuit breaker
├── tests/                    # Comprehensive test suite
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── requirements.txt
└── .env.example
```

## Safety

- **Always start with `--dry-run`** to verify behaviour before using real funds
- **Use a dedicated hot wallet** — never use your main wallet for automation
- **Private keys** are loaded from `.env` only — never committed to source control
- **Circuit breaker** automatically pauses trading after consecutive losses
- **Daily loss limit** halts trading if the configured threshold is exceeded
- **Position and exposure caps** prevent over-concentration

## License

MIT
