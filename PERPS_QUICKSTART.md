# Perpetual Futures Strategy - Quick Start Guide

## Overview

The perpetual futures (perps) strategy has been successfully integrated into the trading bot. This guide will help you get started with testing and running the strategy.

## What Was Implemented

### Core Components

1. **Zoomex V3 REST Client** (`src/exchanges/zoomex_v3.py`)
   - Full async implementation with HMAC authentication
   - Klines fetching, order placement, position management
   - TP/SL bracket orders
   - Precision handling and error retries

2. **Technical Indicators** (`src/ta_indicators/ta_core.py`)
   - Simple Moving Average (SMA)
   - RSI with EMA smoothing
   - Volume-Weighted Average Price (VWAP)

3. **Strategy Signals** (`src/strategies/perps_trend_vwap.py`)
   - Bull crossover detection (fast MA > slow MA)
   - VWAP filter (price must be above VWAP)
   - RSI filter (30-65 range for fresh trends)

4. **Position Sizing & Execution** (`src/engine/perps_executor.py`)
   - Risk-based position sizing
   - Quantity rounding to exchange precision
   - TP/SL bracket orders
   - Early exit on trend reversal

5. **Perps Service** (`src/services/perps.py`)
   - Main orchestration logic
   - Fetches klines every cycle
   - Computes signals
   - Manages positions
   - Logs all entry/exit decisions with R:R ratios

6. **Integration** (`src/main.py`)
   - Perps service integrated into main trading engine
   - Runs on configurable cycle interval

### Test Coverage

- **16 passing tests** covering:
  - Technical indicators (SMA, RSI, VWAP)
  - Position sizing and quantity rounding
  - Zoomex client initialization and requests

## Configuration

### 1. Set Environment Variables

Create a `.env` file (or export directly):

```bash
# Zoomex Testnet Credentials
export ZOOMEX_API_KEY="your_testnet_api_key"
export ZOOMEX_API_SECRET="your_testnet_api_secret"
export ZOOMEX_BASE="https://openapi-testnet.zoomex.com"
```

### 2. Enable Perps in config/strategy.yaml

```yaml
perps:
  enabled: true              # Toggle strategy on/off
  exchange: zoomex           # Currently supports Zoomex only
  symbol: "SOLUSDT"          # Trading symbol (no slash)
  interval: "5"              # Candle interval (5 minutes)
  leverage: 1                # Leverage (1x recommended for testing)
  mode: "oneway"             # "oneway" or "hedge"
  positionIdx: 0             # 0 for oneway mode
  riskPct: 0.005             # Risk 0.5% of equity per trade
  stopLossPct: 0.01          # 1% stop-loss distance
  takeProfitPct: 0.03        # 3% take-profit (3:1 R:R)
  cashDeployCap: 0.20        # Max 20% of equity per position
  triggerBy: "LastPrice"     # "LastPrice", "MarkPrice", or "IndexPrice"
  earlyExitOnCross: false    # Exit on MA bear cross
  useTestnet: true           # Use testnet for testing
  consecutiveLossLimit: null # Circuit breaker (null = disabled)
```

## Running the Strategy

### 1. Install Dependencies

```bash
pip install aiohttp pandas numpy pyyaml pydantic pytest
```

### 2. Run Tests

```bash
# Run all perps tests
pytest tests/test_indicators.py tests/test_perps_executor.py tests/test_zoomex_client.py -v

# Run a specific test
pytest tests/test_indicators.py::test_sma -v
```

### 3. Start the Bot

```bash
python src/main.py
```

### 4. Monitor Logs

The bot will log:
- Initialization messages
- Klines fetching
- Signal computation
- Entry decisions with:
  - Entry price
  - TP price and level
  - SL price and level
  - Expected R:R ratio
  - Position size in base currency
- Exit decisions (TP hit, SL hit, or early exit)
- API errors and retries

## Strategy Logic

### Entry Conditions (LONG only)

1. **Bull Crossover**: `fast_ma(10)` crosses above `slow_ma(30)`
2. **Price Above VWAP**: Confirms bullish momentum
3. **RSI Filter**: RSI between 30 and 65 (fresh trend, not overbought)

### Exit Conditions

1. **Take-Profit**: Entry × (1 + takeProfitPct) = 3% gain
2. **Stop-Loss**: Entry × (1 - stopLossPct) = 1% loss
3. **Early Exit** (if enabled): Fast MA crosses below slow MA

### Position Sizing

```
risk_dollars = equity × riskPct
notional = risk_dollars / stopLossPct
usd_to_deploy = min(notional, equity × cashDeployCap)
qty_base = usd_to_deploy / entry_price
```

## Safety Features

1. **Candle-Close Execution**: Only trades on closed candles to avoid repainting
2. **Idempotent Orders**: Unique `orderLinkId` prevents double-fills on retries
3. **Exchange-Resident TP/SL**: Orders placed directly on exchange (survives bot restarts)
4. **Leverage Control**: Configurable leverage (1x default)
5. **Circuit Breaker**: Optional consecutive loss limit
6. **Quantity Precision**: Automatic rounding to exchange tick size
7. **Error Handling**: Retries on network errors, logs on API errors

## Testing Checklist

- [ ] Set Zoomex testnet credentials
- [ ] Enable `perps.enabled: true` in config
- [ ] Set `perps.useTestnet: true`
- [ ] Run unit tests (all passing)
- [ ] Start bot and verify initialization
- [ ] Wait for entry signal
- [ ] Check Zoomex UI for open position with TP/SL
- [ ] Monitor logs for entry/exit decisions
- [ ] Verify TP/SL hit correctly
- [ ] Test circuit breaker (if enabled)

## Troubleshooting

### Import Errors

If you see import errors, ensure all `__init__.py` files exist:
- `src/ta_indicators/__init__.py`
- `src/engine/__init__.py`
- `src/strategies/__init__.py`
- `src/exchanges/__init__.py`

### API Authentication Errors

- Verify API key/secret are correct
- Ensure testnet keys for testnet base URL
- Check if IP is whitelisted (if required)

### Position Not Opening

- Check logs for signal computation
- Verify sufficient equity in testnet account
- Ensure symbol is tradeable and not suspended
- Check leverage is set correctly

### Orders Rejected

- Verify quantity meets minimum order size
- Check if enough margin available
- Ensure price and quantity have correct precision

## Next Steps

1. **Paper Trade on Testnet**: Run for 1-2 weeks to validate strategy
2. **Optimize Parameters**: Adjust MA periods, RSI thresholds, R:R ratio
3. **Add Shorts**: Extend strategy to support short positions
4. **Backtesting**: Create historical backtest for parameter optimization
5. **Multi-Symbol**: Support multiple symbols in parallel
6. **Advanced Filters**: Add volume, volatility, or time filters

## File Structure

```
src/
├── exchanges/
│   ├── __init__.py
│   └── zoomex_v3.py           # Zoomex REST client
├── ta_indicators/
│   ├── __init__.py
│   └── ta_core.py             # SMA, RSI, VWAP
├── strategies/
│   ├── __init__.py
│   └── perps_trend_vwap.py    # Signal computation
├── engine/
│   ├── __init__.py
│   └── perps_executor.py      # Position sizing & execution
├── services/
│   └── perps.py               # Main perps service
├── main.py                    # Trading engine entry point
└── config.py                  # Configuration classes

tests/
├── test_indicators.py         # Indicator tests
├── test_perps_executor.py     # Executor tests
└── test_zoomex_client.py      # Client tests

config/
└── strategy.yaml              # Main configuration file
```

## Support

For issues or questions:
1. Check logs for error messages
2. Verify configuration settings
3. Run unit tests to ensure setup is correct
4. Review README.md for detailed documentation
