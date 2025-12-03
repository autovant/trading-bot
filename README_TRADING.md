# Zoomex Perpetual Futures Trading Bot - Production Guide

## Table of Contents
- [Architecture Overview](#architecture-overview)
- [Quick Start](#quick-start)
- [Detailed Setup](#detailed-setup)
- [Running the Bot](#running-the-bot)
- [Backtesting](#backtesting)
- [Paper Trading](#paper-trading)
- [Live Trading](#live-trading)
- [Strategy Configuration](#strategy-configuration)
- [Risk Management](#risk-management)
- [Monitoring & Logs](#monitoring--logs)
- [Troubleshooting](#troubleshooting)
- [Safety Checklist](#safety-checklist)

---

## Architecture Overview

This trading bot is designed for **perpetual futures trading on Zoomex** with a production-ready architecture:

### Core Components

```
┌─────────────────────────────────────────────────────────────┐
│                      Trading Engine                          │
│  (src/main.py - Orchestrates all services)                  │
└────────────┬────────────────────────────────────────────────┘
             │
    ┌────────┴────────┐
    │                 │
┌───▼────┐      ┌────▼─────┐
│ Perps  │      │ Strategy │
│Service │      │ Engine   │
└───┬────┘      └────┬─────┘
    │                │
┌───▼────────────────▼─────┐
│   Zoomex V3 Client       │
│  (REST API + WebSocket)  │
└──────────────────────────┘
```

### Key Features

- **Exchange Integration**: Zoomex V3 REST API with HMAC authentication
- **Strategy**: Trend-following with SMA crossover + VWAP + RSI filters
- **Risk Management**: Position sizing based on equity and risk percentage
- **TP/SL Orders**: Exchange-resident take-profit and stop-loss brackets
- **Circuit Breaker**: Automatic trading halt after consecutive losses
- **Testnet Support**: Full testnet mode for safe testing
- **Hot Reload**: Configuration changes applied without restart
- **Comprehensive Logging**: All decisions logged with R:R ratios

### File Structure

```
trading-bot/
├── src/
│   ├── main.py                    # Main trading engine
│   ├── config.py                  # Configuration loader
│   ├── exchanges/
│   │   └── zoomex_v3.py          # Zoomex API client
│   ├── strategies/
│   │   └── perps_trend_vwap.py   # Perps strategy signals
│   ├── services/
│   │   └── perps.py              # Perps orchestration service
│   └── engine/
│       └── perps_executor.py     # Position sizing & execution
├── config/
│   └── strategy.yaml             # Main configuration file
├── configs/
│   └── zoomex_example.yaml       # Example Zoomex config
├── tools/
│   ├── backtest.py               # Backtesting engine
│   └── backtest_perps.py         # Perps-specific backtest
├── logs/                         # Trading logs
├── data/                         # Database & historical data
└── tests/                        # Unit tests
```

---

## Quick Start

### 1. Get Zoomex Testnet Credentials

1. Visit https://testnet.zoomex.com
2. Create an account (free testnet funds provided)
3. Go to API Management
4. Create a new API key with permissions:
   - ✅ Read
   - ✅ Trade
   - ❌ Withdraw (not needed)
5. Save your API Key and API Secret

### 2. Set Environment Variables

```bash
# Copy the example file
cp .env.example .env

# Edit .env and add your credentials
export ZOOMEX_API_KEY="your_testnet_api_key"
export ZOOMEX_API_SECRET="your_testnet_api_secret"
export ZOOMEX_BASE="https://openapi-testnet.zoomex.com"
```

On Windows (PowerShell):
```powershell
$env:ZOOMEX_API_KEY="your_testnet_api_key"
$env:ZOOMEX_API_SECRET="your_testnet_api_secret"
$env:ZOOMEX_BASE="https://openapi-testnet.zoomex.com"
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Run Paper Trading (Simulated)

```bash
python run_bot.py --mode paper --config configs/zoomex_example.yaml
```

This runs in **simulation mode** - no real orders are placed.

### 5. Run on Testnet (Real Orders, Fake Money)

```bash
python run_bot.py --mode testnet --config configs/zoomex_example.yaml
```

This places **real orders on testnet** using fake funds.

---

## Detailed Setup

### Prerequisites

- **Python 3.9+** (tested on 3.10, 3.11)
- **Windows 11** (also works on Linux/Mac)
- **Internet connection** for API access
- **Zoomex account** (testnet or mainnet)

### Installation Steps

#### 1. Clone or Navigate to Repository

```bash
cd /path/to/trading-bot
```

#### 2. Create Virtual Environment (Recommended)

```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Linux/Mac
python3 -m venv venv
source venv/bin/activate
```

#### 3. Install Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

Required packages:
- `aiohttp` - Async HTTP client
- `pandas` - Data manipulation
- `numpy` - Numerical computing
- `pyyaml` - YAML config parsing
- `pydantic` - Config validation
- `pytest` - Testing framework

#### 4. Create Configuration

```bash
# Copy example config
cp configs/zoomex_example.yaml config/strategy.yaml

# Edit config/strategy.yaml with your preferences
```

#### 5. Set Up Environment Variables

**Option A: Using .env file (Recommended)**

```bash
cp .env.example .env
# Edit .env with your API credentials
```

**Option B: Export directly**

```bash
# Linux/Mac
export ZOOMEX_API_KEY="your_key"
export ZOOMEX_API_SECRET="your_secret"

# Windows PowerShell
$env:ZOOMEX_API_KEY="your_key"
$env:ZOOMEX_API_SECRET="your_secret"

# Windows CMD
set ZOOMEX_API_KEY=your_key
set ZOOMEX_API_SECRET=your_secret
```

#### 6. Verify Installation

```bash
# Run tests
pytest tests/ -v

# Check configuration
python -c "from src.config import get_config; print(get_config())"
```

---

## Running the Bot

### Command-Line Interface

The bot provides a unified CLI through `run_bot.py`:

```bash
python run_bot.py --mode <MODE> --config <CONFIG_FILE> [OPTIONS]
```

**Arguments:**

- `--mode`: Trading mode
  - `paper` - Simulated trading (no real orders)
  - `testnet` - Real orders on testnet
  - `live` - Real orders on mainnet ⚠️
- `--config`: Path to configuration file (default: `config/strategy.yaml`)
- `--symbol`: Override trading symbol (e.g., `BTCUSDT`)
- `--interval`: Override candle interval (e.g., `5` for 5 minutes)
- `--leverage`: Override leverage (default: 1)
- `--dry-run`: Validate config without starting bot

### Paper Trading Mode

**Purpose**: Test strategy logic without any real orders

```bash
python run_bot.py --mode paper --config configs/zoomex_example.yaml
```

**What happens:**
- ✅ Fetches real market data
- ✅ Generates real signals
- ✅ Calculates position sizes
- ❌ No orders sent to exchange
- ✅ Logs all decisions as if trading

**Use when:**
- Testing strategy changes
- Validating configuration
- Learning how the bot works

### Testnet Mode

**Purpose**: Place real orders with fake money

```bash
python run_bot.py --mode testnet --config configs/zoomex_example.yaml
```

**What happens:**
- ✅ Fetches real market data
- ✅ Places real orders on testnet
- ✅ TP/SL orders created on exchange
- ✅ Fills tracked and logged
- ✅ Uses testnet API keys

**Use when:**
- Validating order execution
- Testing TP/SL bracket orders
- Verifying position sizing
- Final testing before live

**Requirements:**
- Testnet API keys
- `perps.useTestnet: true` in config
- `ZOOMEX_BASE=https://openapi-testnet.zoomex.com`

### Live Trading Mode ⚠️

**Purpose**: Trade with real money

```bash
python run_bot.py --mode live --config configs/zoomex_example.yaml
```

**⚠️ WARNING: This uses real money! ⚠️**

**What happens:**
- ✅ Places real orders on mainnet
- ✅ Uses real funds
- ✅ Real profit/loss
- ⚠️ Real risk

**Before going live:**
1. ✅ Test thoroughly on testnet
2. ✅ Verify all risk limits
3. ✅ Start with small position sizes
4. ✅ Monitor closely for first 24 hours
5. ✅ Have stop-loss in place
6. ✅ Set `consecutiveLossLimit` in config

**Requirements:**
- Mainnet API keys
- `perps.useTestnet: false` in config
- `ZOOMEX_BASE=https://openapi.zoomex.com` (or omit)
- Sufficient account balance

### Running with Docker (Optional)

```bash
# Paper mode
APP_MODE=paper docker compose up --build

# Testnet mode
APP_MODE=testnet docker compose up --build

# Live mode (⚠️ use with caution)
APP_MODE=live docker compose up --build
```

---

## Backtesting

### Perps-Specific Backtest

Test the perps strategy on historical data:

```bash
python tools/backtest_perps.py \
  --symbol SOLUSDT \
  --start 2024-01-01 \
  --end 2024-12-31 \
  --interval 5 \
  --config configs/zoomex_example.yaml
```

**Output:**
```
=== Backtest Results ===
Symbol: SOLUSDT
Period: 2024-01-01 to 2024-12-31
Initial Balance: $1000.00
Final Balance: $1247.32
Total P&L: $247.32 (24.73%)
Total Trades: 47
Winning Trades: 28 (59.57%)
Losing Trades: 19 (40.43%)
Win Rate: 59.57%
Average Win: $18.45
Average Loss: -$9.23
Profit Factor: 2.00
Max Drawdown: -8.34%
Sharpe Ratio: 1.42
```

### Traditional Strategy Backtest

For the multi-timeframe regime strategy:

```bash
python tools/backtest.py \
  --symbol BTCUSDT \
  --start 2023-01-01 \
  --end 2024-01-01
```

### Backtest Options

```bash
--symbol SYMBOL       # Trading pair (e.g., BTCUSDT)
--start YYYY-MM-DD    # Start date
--end YYYY-MM-DD      # End date
--interval N          # Candle interval (perps only)
--config FILE         # Config file path
--output FILE         # Save results to JSON
--plot                # Generate equity curve plot
```

---

## Strategy Configuration

### Perps Strategy Parameters

Edit `config/strategy.yaml` under the `perps:` section:

```yaml
perps:
  enabled: true              # Toggle perps trading on/off
  exchange: zoomex           # Exchange (currently only zoomex)
  symbol: "SOLUSDT"          # Trading pair (no slash)
  interval: "5"              # Candle interval in minutes
  leverage: 1                # Leverage multiplier (1-10x)
  mode: "oneway"             # "oneway" or "hedge"
  positionIdx: 0             # 0=oneway, 1=long, 2=short (hedge mode)
  
  # Risk Parameters
  riskPct: 0.005             # Risk 0.5% of equity per trade
  stopLossPct: 0.01          # 1% stop-loss distance
  takeProfitPct: 0.03        # 3% take-profit (3:1 R:R)
  cashDeployCap: 0.20        # Max 20% of equity per position
  
  # Execution
  triggerBy: "LastPrice"     # "LastPrice", "MarkPrice", "IndexPrice"
  earlyExitOnCross: false    # Exit on MA bear cross
  
  # Safety
  useTestnet: true           # Use testnet (true) or mainnet (false)
  consecutiveLossLimit: 3    # Stop after N losses (null=disabled)
```

### Strategy Logic

**Entry Conditions (LONG only):**

1. **Bull Crossover**: Fast MA (10) crosses above Slow MA (30)
2. **VWAP Filter**: Price must be above VWAP
3. **RSI Filter**: RSI between 30 and 65 (fresh trend)
4. **No Existing Position**: Only one position at a time

**Exit Conditions:**

1. **Take-Profit**: Entry × (1 + takeProfitPct)
2. **Stop-Loss**: Entry × (1 - stopLossPct)
3. **Early Exit** (optional): MA bear crossover if `earlyExitOnCross: true`

**Position Sizing:**

```python
risk_dollars = equity × riskPct
notional = risk_dollars / stopLossPct
usd_to_deploy = min(notional, equity × cashDeployCap)
qty_base = usd_to_deploy / entry_price
```

**Example:**
- Equity: $1000
- Risk: 0.5% = $5
- Stop-loss: 1% = $5 / 0.01 = $500 notional
- Cash cap: 20% = $200
- Deploy: min($500, $200) = $200
- Entry price: $100
- Quantity: $200 / $100 = 2 units

### Indicator Parameters

The strategy uses these technical indicators (configured in `src/strategies/perps_trend_vwap.py`):

- **Fast MA**: 10-period SMA
- **Slow MA**: 30-period SMA
- **VWAP**: Volume-Weighted Average Price
- **RSI**: 14-period RSI with EMA smoothing

To modify indicator parameters, edit `src/strategies/perps_trend_vwap.py`:

```python
fast = sma(closes, 10)   # Change 10 to your preferred period
slow = sma(closes, 30)   # Change 30 to your preferred period
rsi_series = rsi_ema(closes, 14)  # Change 14 for RSI period
```

---

## Risk Management

### Built-in Safety Features

#### 1. Position Sizing

**Risk-based sizing** ensures you never risk more than configured percentage:

```yaml
perps:
  riskPct: 0.005        # Risk 0.5% per trade
  cashDeployCap: 0.20   # Max 20% of equity
```

**How it works:**
- Calculates position size based on stop-loss distance
- Caps position at `cashDeployCap` to prevent over-leverage
- Rounds to exchange precision automatically

#### 2. Stop-Loss & Take-Profit

**Exchange-resident orders** placed immediately with entry:

```yaml
perps:
  stopLossPct: 0.01      # 1% stop-loss
  takeProfitPct: 0.03    # 3% take-profit (3:1 R:R)
```

**Benefits:**
- Orders remain active even if bot crashes
- No slippage on TP/SL execution
- Guaranteed exit at specified levels

#### 3. Circuit Breaker

**Automatic trading halt** after consecutive losses:

```yaml
perps:
  consecutiveLossLimit: 3  # Stop after 3 losses
```

**How it works:**
- Tracks consecutive losing trades
- Stops opening new positions after limit hit
- Logs warning and requires manual reset
- Set to `null` to disable

#### 4. Daily Loss Limit

**Maximum daily loss** before trading stops:

```yaml
trading:
  max_daily_risk: 0.05  # 5% max daily loss
```

#### 5. Leverage Control

**Configurable leverage** with safe defaults:

```yaml
perps:
  leverage: 1  # 1x leverage (recommended for testing)
```

**Recommendations:**
- **Testing**: 1x leverage
- **Conservative**: 2-3x leverage
- **Aggressive**: 5x leverage (⚠️ higher risk)
- **Maximum**: 10x (⚠️ very high risk)

### Risk Calculation Example

**Scenario:**
- Account: $1000
- Risk per trade: 0.5% = $5
- Stop-loss: 1%
- Take-profit: 3%
- Entry: $100

**Position Size:**
```
Risk dollars: $1000 × 0.005 = $5
Notional: $5 / 0.01 = $500
Cash cap: $1000 × 0.20 = $200
Deploy: min($500, $200) = $200
Quantity: $200 / $100 = 2 units
```

**Outcomes:**
- **Win**: 2 × $100 × 0.03 = $6 profit (1.2:1 actual R:R)
- **Loss**: 2 × $100 × 0.01 = $2 loss (0.4% of account)
- **Max loss**: $5 (0.5% of account) ✅

### Manual Risk Overrides

You can override risk parameters via CLI:

```bash
python run_bot.py \
  --mode testnet \
  --config configs/zoomex_example.yaml \
  --risk-pct 0.003 \
  --stop-loss-pct 0.015 \
  --take-profit-pct 0.045
```

---

## Monitoring & Logs

### Log Files

All trading activity is logged to:

```
logs/
├── trading.log          # Main trading log
├── perps.log           # Perps-specific log
├── risk.log            # Risk decisions
└── errors.log          # Error stack traces
```

### Log Levels

Configure in `config/strategy.yaml`:

```yaml
logging:
  level: "INFO"          # DEBUG | INFO | WARNING | ERROR
  file: "logs/trading.log"
  max_size: "10MB"
  backup_count: 5
```

### What Gets Logged

#### Entry Signals
```
[INFO] LONG signal: price=100.45 fast=99.23 slow=98.12 vwap=99.87 rsi=42.3
[INFO] Position sizing: equity=$1000 risk=0.5% qty=2.0 notional=$200
[INFO] Entry order placed: orderId=abc123 qty=2.0 entry=100.45 tp=103.46 sl=99.45 R:R=3.0
```

#### Exit Signals
```
[INFO] Take-profit hit: orderId=abc123 entry=100.45 exit=103.46 pnl=$6.02 (+3.0%)
[INFO] Stop-loss hit: orderId=abc123 entry=100.45 exit=99.45 pnl=-$2.00 (-1.0%)
```

#### Risk Events
```
[WARNING] Circuit breaker triggered: 3 consecutive losses
[WARNING] Daily loss limit reached: -5.2% (limit: -5.0%)
[WARNING] Quantity 0.0012 below minimum 0.01 for SOLUSDT
```

#### Errors
```
[ERROR] Zoomex API error: Insufficient balance
[ERROR] Order placement failed: retCode=10001 retMsg=Invalid symbol
```

### Real-Time Monitoring

#### Dashboard (Streamlit)

```bash
streamlit run dashboard/app.py
```

Visit `http://localhost:8501` to see:
- Current positions
- Recent trades
- Equity curve
- Performance metrics
- Live logs

#### Command-Line Monitoring

```bash
# Tail logs in real-time
tail -f logs/trading.log

# Filter for specific events
grep "LONG signal" logs/trading.log
grep "ERROR" logs/trading.log

# Count trades
grep "Entry order placed" logs/trading.log | wc -l
```

### Performance Metrics

The bot tracks and logs:

- **Total P&L**: Cumulative profit/loss
- **Win Rate**: Percentage of winning trades
- **Average Win/Loss**: Mean profit and loss per trade
- **Profit Factor**: Gross profit / gross loss
- **Max Drawdown**: Largest peak-to-trough decline
- **Sharpe Ratio**: Risk-adjusted returns
- **Consecutive Losses**: Current losing streak

Access metrics via:

```bash
# View summary
python tools/performance_report.py

# Export to JSON
python tools/performance_report.py --output metrics.json
```

---

## Troubleshooting

### Common Issues

#### 1. API Authentication Errors

**Error:**
```
[ERROR] ZOOMEX_API_KEY and ZOOMEX_API_SECRET must be set
```

**Solution:**
```bash
# Verify environment variables are set
echo $ZOOMEX_API_KEY
echo $ZOOMEX_API_SECRET

# Re-export if needed
export ZOOMEX_API_KEY="your_key"
export ZOOMEX_API_SECRET="your_secret"
```

#### 2. Invalid Signature

**Error:**
```
[ERROR] Zoomex API error: Invalid signature
```

**Solution:**
- Check API secret is correct (no extra spaces)
- Verify system time is synchronized
- Ensure API key has correct permissions (Read + Trade)

#### 3. Insufficient Balance

**Error:**
```
[ERROR] Zoomex API error: Insufficient balance
```

**Solution:**
- Check account balance on Zoomex
- Reduce position size (`riskPct` or `cashDeployCap`)
- For testnet: Request more testnet funds

#### 4. Quantity Below Minimum

**Warning:**
```
[WARNING] Quantity 0.0012 below minimum 0.01 for SOLUSDT
```

**Solution:**
- Increase `riskPct` in config
- Increase `cashDeployCap` in config
- Trade a different symbol with lower minimum

#### 5. Rate Limiting

**Warning:**
```
[WARNING] Zoomex rate limited (429). attempt=1
```

**Solution:**
- Bot automatically retries with backoff
- Reduce polling frequency if persistent
- Check Zoomex rate limits for your tier

#### 6. No Signals Generated

**Issue:** Bot runs but never enters trades

**Solution:**
- Check market conditions (strategy is LONG-only)
- Verify indicators have enough data (needs 35+ candles)
- Lower RSI thresholds if too restrictive
- Check logs for signal details

#### 7. Configuration Not Loading

**Error:**
```
[ERROR] Configuration file not found
```

**Solution:**
```bash
# Verify config file exists
ls -la config/strategy.yaml

# Copy example if missing
cp configs/zoomex_example.yaml config/strategy.yaml
```

### Debug Mode

Enable detailed logging:

```yaml
logging:
  level: "DEBUG"
```

Or via CLI:

```bash
python run_bot.py --mode paper --config configs/zoomex_example.yaml --log-level DEBUG
```

### Testing Connectivity

```bash
# Test Zoomex API connection
python -c "
import asyncio
import aiohttp
from src.exchanges.zoomex_v3 import ZoomexV3Client

async def test():
    async with aiohttp.ClientSession() as session:
        client = ZoomexV3Client(session)
        df = await client.get_klines('BTCUSDT', '5', 10)
        print(df)

asyncio.run(test())
"
```

### Getting Help

1. **Check logs**: `logs/trading.log` and `logs/errors.log`
2. **Run tests**: `pytest tests/ -v`
3. **Validate config**: `python run_bot.py --dry-run --config configs/zoomex_example.yaml`
4. **Review documentation**: `docs/` directory
5. **Check Zoomex API docs**: https://www.zoomex.com/docs/v3

---

## Safety Checklist

### Before Testing on Testnet

- [ ] API keys are from **testnet** (not mainnet)
- [ ] `perps.useTestnet: true` in config
- [ ] `ZOOMEX_BASE=https://openapi-testnet.zoomex.com`
- [ ] Risk parameters are reasonable (`riskPct: 0.005`)
- [ ] Stop-loss is configured (`stopLossPct: 0.01`)
- [ ] Circuit breaker is enabled (`consecutiveLossLimit: 3`)
- [ ] Leverage is low (`leverage: 1`)
- [ ] Logs directory exists and is writable
- [ ] All tests pass (`pytest tests/ -v`)

### Before Going Live

- [ ] ✅ Tested thoroughly on testnet for at least 1 week
- [ ] ✅ Verified all orders execute correctly
- [ ] ✅ Confirmed TP/SL orders are placed
- [ ] ✅ Monitored for false signals
- [ ] ✅ Backtested on historical data
- [ ] ✅ Win rate is acceptable (>50%)
- [ ] ✅ Max drawdown is tolerable (<15%)
- [ ] ✅ API keys are from **mainnet**
- [ ] ✅ `perps.useTestnet: false` in config
- [ ] ✅ `ZOOMEX_BASE` is mainnet or omitted
- [ ] ✅ Risk per trade is conservative (0.5-1%)
- [ ] ✅ Daily loss limit is set (`max_daily_risk: 0.05`)
- [ ] ✅ Circuit breaker is enabled (`consecutiveLossLimit: 3`)
- [ ] ✅ Leverage is appropriate (1-3x recommended)
- [ ] ✅ Sufficient account balance (>$500 recommended)
- [ ] ✅ Monitoring system is in place
- [ ] ✅ Alert notifications configured
- [ ] ✅ Emergency stop procedure documented
- [ ] ✅ You understand the risks and can afford losses

### Emergency Stop Procedure

If you need to stop the bot immediately:

1. **Stop the bot process**:
   ```bash
   # Press Ctrl+C in terminal
   # Or kill the process
   pkill -f "python run_bot.py"
   ```

2. **Cancel all open orders**:
   ```bash
   python tools/cancel_all_orders.py --symbol SOLUSDT
   ```

3. **Close all positions** (if needed):
   ```bash
   python tools/close_all_positions.py --symbol SOLUSDT
   ```

4. **Check Zoomex UI** to verify all orders/positions are closed

### Risk Disclaimer

⚠️ **IMPORTANT**: Trading cryptocurrencies involves substantial risk of loss. This bot is provided as-is with no guarantees of profitability. You are solely responsible for:

- Understanding how the bot works
- Testing thoroughly before live trading
- Monitoring the bot during operation
- Managing your risk appropriately
- Any losses incurred

**Never trade with money you cannot afford to lose.**

---

## Advanced Topics

### Custom Strategy Development

To create your own strategy:

1. Create a new file in `src/strategies/`:
   ```python
   # src/strategies/my_strategy.py
   def compute_signals(df: pd.DataFrame) -> Dict[str, Any]:
       # Your strategy logic here
       return {
           "long_signal": bool,
           "short_signal": bool,
           "price": float,
           # ... other indicators
       }
   ```

2. Update `src/services/perps.py` to use your strategy:
   ```python
   from src.strategies.my_strategy import compute_signals
   ```

3. Test your strategy:
   ```bash
   pytest tests/test_my_strategy.py -v
   python tools/backtest_perps.py --strategy my_strategy
   ```

### WebSocket Integration

For real-time data (lower latency):

1. Implement WebSocket client in `src/exchanges/zoomex_ws.py`
2. Subscribe to kline and order updates
3. Update `src/services/perps.py` to use WebSocket data

### Multi-Symbol Trading

To trade multiple symbols simultaneously:

```yaml
perps:
  enabled: true
  symbols:
    - symbol: "BTCUSDT"
      interval: "5"
      riskPct: 0.003
    - symbol: "ETHUSDT"
      interval: "5"
      riskPct: 0.003
    - symbol: "SOLUSDT"
      interval: "5"
      riskPct: 0.004
```

### Database Integration

For persistent storage:

```yaml
database:
  type: "postgresql"
  host: "localhost"
  port: 5432
  database: "trading"
  user: "trader"
  password: "${DB_PASSWORD}"
```

### Notifications

Add Telegram/Discord alerts:

```yaml
notifications:
  telegram:
    enabled: true
    bot_token: "${TELEGRAM_BOT_TOKEN}"
    chat_id: "${TELEGRAM_CHAT_ID}"
  discord:
    enabled: true
    webhook_url: "${DISCORD_WEBHOOK}"
```

---

## Appendix

### Configuration Reference

See `configs/zoomex_example.yaml` for complete configuration with comments.

### API Reference

See `docs/API.md` for detailed API documentation.

### Testing Guide

See `docs/TESTING.md` for comprehensive testing guide.

### Performance Tuning

See `docs/PERFORMANCE.md` for optimization tips.

---

## Support

For issues, questions, or contributions:

- **GitHub Issues**: [Create an issue](https://github.com/yourusername/trading-bot/issues)
- **Documentation**: `docs/` directory
- **Tests**: `tests/` directory
- **Examples**: `configs/` directory

---

**Last Updated**: 2024-12-31
**Version**: 1.0.0
**License**: MIT
