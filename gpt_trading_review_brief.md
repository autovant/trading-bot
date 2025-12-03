# Trading Bot Technical Review Brief

**Prepared for:** External AI Review (ChatGPT)  
**Purpose:** Pre-live trading safety assessment  
**Date:** 2025  
**Bot Version:** Zoomex Perpetual Futures Trading Bot

---

## A. Repo & Architecture Summary

### Main Entry Points

- **`run_bot.py`**: Primary CLI entry point for running the bot in paper/testnet/live modes
  - Supports three modes: `paper` (simulated), `testnet` (real orders, fake money), `live` (real money)
  - Handles mode validation, API key checks, and user confirmation for live trading
  - Runs 60-second trading cycles in an async event loop

- **`src/main.py`**: Alternative trading engine (appears to be legacy/unused in current perps workflow)
  - Contains `TradingEngine` class with config hot-reloading
  - Not actively used by `run_bot.py` for perps trading

- **`tools/backtest_perps.py`**: Backtesting engine for perpetual futures strategy
  - Simulates historical trading with slippage and fees
  - Generates performance metrics (win rate, Sharpe, drawdown)

### Core Modules & Responsibilities

**Exchange Integration:**
- `src/exchanges/zoomex_v3.py`: Zoomex V3 API client
  - Handles authentication (HMAC-SHA256 signing)
  - Implements exponential backoff retry logic (max 3 attempts)
  - Provides methods: `get_klines()`, `set_leverage()`, `create_market_with_brackets()`, `get_wallet_equity()`, `get_position_qty()`
  - Raises `ZoomexError` on API failures

**Strategy & Signals:**
- `src/strategies/perps_trend_vwap.py`: Signal generation logic
  - Function: `compute_signals(df)` returns long/short signals
  - Uses SMA(10), SMA(30), VWAP, RSI(14)
  - Requires minimum 35 candles for indicator warmup

**Risk & Execution:**
- `src/engine/perps_executor.py`: Position sizing and order execution
  - `risk_position_size()`: Calculates position size based on equity, risk %, stop-loss %, and cash cap
  - `round_quantity()`: Rounds to exchange precision
  - `enter_long_with_brackets()`: Places market order with TP/SL
  - `early_exit_reduce_only()`: Closes position via reduce-only order

**Trading Service:**
- `src/services/perps.py`: Main trading orchestration (`PerpsService` class)
  - Manages trading cycle: fetch candles → compute signals → execute orders
  - Tracks equity, position quantity, consecutive losses
  - Implements circuit breaker logic
  - Refreshes account state before each cycle

**Configuration:**
- `src/config.py`: Pydantic-based config validation
  - `PerpsConfig` class with strict validation (extra fields forbidden)
  - Validates leverage, risk percentages, position mode
  - Substitutes environment variables (e.g., `${ZOOMEX_API_KEY}`)

**Paper Trading:**
- `src/paper_trader.py`: High-fidelity paper broker (NOT used by current perps implementation)
  - Simulates slippage, fees, partial fills, funding
  - Current perps paper mode in `run_bot.py` only logs signals without order simulation

### Data Flow

```
Market Data (Zoomex API)
    ↓
get_klines() → DataFrame (OHLCV)
    ↓
_closed_candle_view() → Filter incomplete candles
    ↓
compute_signals() → {long_signal, price, fast, slow, vwap, rsi}
    ↓
PerpsService.run_cycle() → Check circuit breaker, position state
    ↓
risk_position_size() → Calculate qty based on equity & risk
    ↓
enter_long_with_brackets() → Place market order + TP/SL on exchange
    ↓
_refresh_account_state() → Update equity & position qty
```

### Architectural Patterns

- **Async/await**: All I/O operations are asynchronous (aiohttp, asyncio)
- **Service-oriented**: `PerpsService` encapsulates trading logic
- **Functional risk engine**: Pure functions for position sizing
- **Config-driven**: All parameters loaded from YAML with Pydantic validation
- **Retry with backoff**: API requests retry up to 3 times with exponential backoff

---

## B. Config & Modes (Paper / Testnet / Live)

### Configuration Files

**Primary Config:** `configs/zoomex_example.yaml`

User must copy this to their own config file and customize. The file contains:

**Top-Level Sections:**

1. **`app_mode`**: `"paper"` (not actively used by `run_bot.py`; mode is CLI-driven)

2. **`exchange`**:
   - `name`: `"zoomex"`
   - `api_key`: `"${ZOOMEX_API_KEY}"` (env var substitution)
   - `secret_key`: `"${ZOOMEX_API_SECRET}"`
   - `testnet`: `true`
   - `base_url`: `"https://openapi-testnet.zoomex.com"`

3. **`trading`**:
   - `initial_capital`: `1000.0`
   - `risk_per_trade`: `0.006` (0.6%)
   - `max_positions`: `3`
   - `max_daily_risk`: `0.05` (5%)
   - `max_sector_exposure`: `0.20` (20%)
   - `symbols`: `["BTCUSDT", "ETHUSDT", "SOLUSDT"]`

4. **`strategy`**: Multi-timeframe strategy config (regime, setup, signals)
   - **NOT used by perps strategy** (perps uses simpler SMA/VWAP logic)

5. **`risk_management`**:
   - `ladder_entries`: `[0.25, 0.35, 0.40]` (NOT implemented in perps)
   - `stops`: ATR-based and hard risk % (NOT used in perps; perps uses fixed %)
   - `crisis_mode`: `drawdown_threshold: 0.10`, `consecutive_losses: 3`

6. **`perps`** (ACTIVE CONFIG FOR PERPS TRADING):
   - `enabled`: `true`
   - `exchange`: `"zoomex"`
   - `symbol`: `"SOLUSDT"`
   - `interval`: `"5"` (5-minute candles)
   - `leverage`: `1` (1x leverage)
   - `mode`: `"oneway"` (or `"hedge"`)
   - `positionIdx`: `0` (0 for oneway, 1/2 for hedge)
   - `riskPct`: `0.005` (0.5% of equity per trade)
   - `stopLossPct`: `0.01` (1% stop-loss)
   - `takeProfitPct`: `0.03` (3% take-profit)
   - `cashDeployCap`: `0.20` (max 20% of equity per position)
   - `triggerBy`: `"LastPrice"` (or `"MarkPrice"`, `"IndexPrice"`)
   - `earlyExitOnCross`: `false` (exit on MA bear cross)
   - `useTestnet`: `true`
   - `consecutiveLossLimit`: `3` (circuit breaker)

7. **`backtesting`**:
   - `slippage`: `0.0005` (0.05%)
   - `commission`: `0.001` (0.1%)
   - `initial_balance`: `1000.0`

8. **`paper`**: Paper trading simulation params (NOT used by perps paper mode)

9. **`logging`**:
   - `level`: `"INFO"`
   - `file`: `"logs/trading.log"`

### Mode Selection

**CLI Argument:** `--mode {paper|testnet|live}`

**Mode Behavior:**

- **`paper`**:
  - Fetches live market data from Zoomex
  - Computes signals and logs them
  - **Does NOT place orders** (just logs "No order placed (paper mode)")
  - Does NOT use `PaperBroker` class (that's for the legacy strategy)

- **`testnet`**:
  - Forces `config.perps.useTestnet = True` (safety override)
  - Places real orders on Zoomex testnet (`https://openapi-testnet.zoomex.com`)
  - Uses testnet API keys
  - Real order execution, fake money

- **`live`**:
  - Validates `config.perps.useTestnet = False` (raises error if misconfigured)
  - Displays warning banner: "⚠️ RUNNING IN LIVE MODE - REAL MONEY AT RISK ⚠️"
  - Requires user to type `"I UNDERSTAND THE RISKS"` to proceed
  - Places real orders on mainnet (`https://openapi.zoomex.com` or `ZOOMEX_BASE` env var)
  - Uses live API keys

### Environment Variables (REQUIRED)

- **`ZOOMEX_API_KEY`**: Zoomex API key (testnet or mainnet)
- **`ZOOMEX_API_SECRET`**: Zoomex API secret
- **`CONFIG_PATH`** (optional): Path to config file (set by `run_bot.py` via `os.environ`)

### Creating Your Own Config

1. Copy `configs/zoomex_example.yaml` to `configs/my_config.yaml`
2. Edit `perps` section:
   - Set `symbol`, `interval`, `leverage`, `riskPct`, `stopLossPct`, `takeProfitPct`
   - Set `useTestnet: true` for testing, `false` for live
   - Set `consecutiveLossLimit` (e.g., `3`) or `null` to disable
3. Set environment variables:
   ```bash
   export ZOOMEX_API_KEY="your_key"
   export ZOOMEX_API_SECRET="your_secret"
   ```
4. Run:
   ```bash
   python run_bot.py --mode testnet --config configs/my_config.yaml
   ```

---

## C. Strategy & Signal Logic

### Location

**File:** `src/strategies/perps_trend_vwap.py`  
**Function:** `compute_signals(df: pd.DataFrame) -> Dict[str, float | bool]`

### Inputs

- **DataFrame `df`**: OHLCV candles (columns: `open`, `high`, `low`, `close`, `volume`)
- **Minimum candles required:** 35 (for indicator warmup)

### Indicators Used

All indicators are **hardcoded** (not configurable via YAML):

1. **SMA(10)** - Fast moving average
   - Period: 10 candles
   - Source: `close` prices
   - Function: `sma(closes, 10)` from `src.ta_indicators.ta_core`

2. **SMA(30)** - Slow moving average
   - Period: 30 candles
   - Source: `close` prices
   - Function: `sma(closes, 30)`

3. **VWAP** - Volume-Weighted Average Price
   - Calculated from OHLCV data
   - Function: `vwap(df)` from `src.ta_indicators.ta_core`

4. **RSI(14)** - Relative Strength Index (EMA-based)
   - Period: 14 candles
   - Source: `close` prices
   - Function: `rsi_ema(closes, 14)`

### Signal Generation Logic

**LONG Signal Conditions (ALL must be true):**

1. **Golden Cross:** `fast[-2] < slow[-2]` AND `fast[-1] > slow[-1]`
   - Fast MA crosses above slow MA on the last closed candle
   - Uses previous candle (`[-2]`) to detect the cross

2. **Price Above VWAP:** `close[-1] > vwap[-1]`
   - Current close is above VWAP (bullish momentum)

3. **RSI Filter:** `30 < rsi[-1] < 65`
   - RSI is not oversold (< 30) or overbought (> 65)
   - Avoids buying into exhaustion

**SHORT Signal:** NOT IMPLEMENTED (strategy is long-only)

**Exit Conditions:**

- **Take-Profit:** Price reaches `entry * (1 + takeProfitPct)` (e.g., +3%)
- **Stop-Loss:** Price reaches `entry * (1 - stopLossPct)` (e.g., -1%)
- **Early Exit (optional):** If `earlyExitOnCross = true`, closes position when fast MA crosses below slow MA (bear cross)

### Signal Output

Returns a dictionary:
```python
{
    "long_signal": bool,      # True if all conditions met
    "price": float,           # Current close price
    "fast": float,            # Fast MA value
    "slow": float,            # Slow MA value
    "vwap": float,            # VWAP value
    "rsi": float,             # RSI value
    "prev_fast": float,       # Previous fast MA (for early exit)
    "prev_slow": float        # Previous slow MA (for early exit)
}
```

### Filters & Safety Checks

**Pre-Signal Checks (in `PerpsService.run_cycle()`):**

1. **Circuit Breaker:** If `consecutive_losses >= consecutiveLossLimit`, skip signal evaluation
2. **Insufficient Data:** If `len(df) < 35`, skip (not enough candles for indicators)
3. **Incomplete Candle:** Uses `_closed_candle_view()` to exclude the current (incomplete) candle
4. **Duplicate Candle:** If `last_candle_time == last_closed_time`, skip (already processed this candle)
5. **Already in Position:** If `current_position_qty > 0`, skip entry (no pyramiding)

**No Trend Filter:** Strategy does NOT check higher timeframe trend (e.g., daily EMA200)

**No Volatility Filter:** Strategy does NOT adjust for high/low volatility (ATR-based filters are in config but not used)

---

## D. Risk Management & Position Sizing

### Location

**File:** `src/engine/perps_executor.py`  
**Function:** `risk_position_size()`

### Position Sizing Formula

**Exact Implementation (line 13-26):**

```python
def risk_position_size(
    *,
    equity_usdt: float,
    risk_pct: float,
    stop_loss_pct: float,
    price: float,
    cash_cap: float = 0.20,
) -> float:
    if stop_loss_pct <= 0 or price <= 0 or equity_usdt <= 0:
        return 0.0
    risk_dollars = equity_usdt * risk_pct
    notional = risk_dollars / stop_loss_pct
    usd_to_deploy = min(notional, equity_usdt * cash_cap)
    return usd_to_deploy / price
```

**Step-by-Step:**

1. **Risk Dollars:** `equity * riskPct` (e.g., $1000 * 0.005 = $5)
2. **Notional from Risk:** `risk_dollars / stopLossPct` (e.g., $5 / 0.01 = $500)
3. **Apply Cash Cap:** `min(notional, equity * cashDeployCap)` (e.g., min($500, $1000 * 0.20) = $200)
4. **Quantity:** `usd_to_deploy / price` (e.g., $200 / $150 = 1.333 SOL)

**Example (default config):**
- Equity: $1000
- Risk per trade: 0.5% ($5)
- Stop-loss: 1%
- Cash cap: 20% ($200)
- Price: $150
- **Result:** 1.333 units (capped by cash cap, not risk)

### Max % of Equity Per Trade

**Implemented:** `cashDeployCap` (default: 0.20 = 20%)

This is a **hard cap** on notional exposure per position, regardless of risk calculation.

### Max Daily Loss Logic

**NOT IMPLEMENTED** in perps strategy.

The config has `trading.max_daily_risk: 0.05` (5%), but this is **not enforced** in `PerpsService`.

### Max Position Size / Leverage Constraints

**Leverage:**
- Set via `config.perps.leverage` (default: 1x)
- Applied once per session via `client.set_leverage(symbol, buy, sell)`
- **No dynamic adjustment** based on volatility or drawdown

**Max Position Size:**
- Controlled by `cashDeployCap` (20% of equity)
- **No absolute max position size** (e.g., max $10,000 notional)

**Max Positions:**
- `config.trading.max_positions: 3` exists but is **NOT enforced** in perps (perps only trades one symbol at a time)

### Stop-Loss & Take-Profit

**Calculation (line 248-249 in `perps.py`):**

```python
tp_price = price * (1 + self.config.takeProfitPct)  # e.g., $150 * 1.03 = $154.50
sl_price = price * (1 - self.config.stopLossPct)    # e.g., $150 * 0.99 = $148.50
```

**Order Type:**
- **Exchange-resident orders** (not "mental" stops)
- Placed via `create_market_with_brackets()` in a single API call
- TP/SL are conditional orders on Zoomex (triggered by `triggerBy` price: LastPrice, MarkPrice, or IndexPrice)

**Risk-Reward Ratio:**
- Default: 3% TP / 1% SL = 3:1 R:R
- Logged but **not validated** (no minimum R:R requirement)

### Safety Checks Before Placing Order

**Pre-Order Checks (in `PerpsService._enter_long()`):**

1. **Equity Check:** If `equity_usdt <= 0`, skip order (line 206-208)
2. **Leverage Set:** Ensures leverage is set before first order (line 210-217)
3. **Quantity Rounding:** Rounds to exchange precision via `round_quantity()` (line 238)
4. **Minimum Quantity:** If `rounded_qty < precision.min_qty`, skip order (line 239-246)
5. **Position Check:** If `current_position_qty > 0`, skip entry (line 102-104)

**NOT Checked:**
- Available margin (assumes equity is sufficient)
- Open orders (no check for pending orders)
- Daily loss limit
- Max drawdown
- Correlation with other positions (single-symbol strategy)

### Circuit Breaker

**Implementation (line 69-73 in `perps.py`):**

```python
if self.config.consecutiveLossLimit and self.consecutive_losses >= self.config.consecutiveLossLimit:
    logger.warning("Circuit breaker triggered: %d consecutive losses", self.consecutive_losses)
    return
```

**Behavior:**
- Tracks `consecutive_losses` (incremented on losing trades, reset on wins)
- If limit reached (e.g., 3), **skips all trading cycles** until bot restart
- **No automatic reset** (requires manual intervention or bot restart)
- **No time-based cooldown** (e.g., "pause for 1 hour")

**Consecutive Loss Tracking:**
- **NOT IMPLEMENTED** in live/testnet mode (no PnL tracking in `PerpsService`)
- Only tracked in backtesting (`tools/backtest_perps.py`)
- **CRITICAL GAP:** Live bot does not update `consecutive_losses` after trades close

---

## E. Backtesting Implementation

### Location

**File:** `tools/backtest_perps.py`  
**Class:** `PerpsBacktest`

### Historical Data Loading

**Source:** Zoomex API (live data fetch)

**Method:** `ZoomexV3Client.get_klines()`

**Process:**
1. Fetches candles in chunks (limit: 1000 per request)
2. Iterates through date range (`--start` to `--end`)
3. Converts to pandas DataFrame with columns: `start`, `open`, `high`, `low`, `close`, `volume`
4. Index: `start` (datetime, UTC)

**Data Format:**
- **Timeframe:** Configurable via `--interval` (default: 5 minutes)
- **Columns:** OHLCV (no bid/ask spread data)
- **No CSV support:** Data is fetched live from API (not from local files)

### Order Execution Simulation

**Entry Simulation (line 103-112):**

```python
entry_price = self.simulate_fill(price, is_entry=True)
notional = qty * entry_price
fees = self.calculate_fees(notional)
self.balance -= fees
```

**Exit Simulation (line 129-140):**

```python
exit_price = self.simulate_fill(price, is_entry=False)
notional = self.position_qty * exit_price
fees = self.calculate_fees(notional)
pnl = (exit_price - self.position_entry) * self.position_qty - fees
self.balance += notional - fees
```

**Slippage Model (line 67-73):**

```python
def simulate_fill(self, price: float, is_entry: bool = True) -> float:
    slippage = price * self.slippage_rate  # 0.03%
    if is_entry:
        return price + slippage  # Pay more when entering
    else:
        return price - slippage  # Get less when exiting
```

**Fees (line 75-77):**

```python
def calculate_fees(self, notional: float) -> float:
    return notional * self.fee_rate  # 0.06% taker fee
```

**Hardcoded Values:**
- `fee_rate = 0.0006` (0.06% taker fee)
- `slippage_rate = 0.0003` (0.03% slippage)

**No Maker/Taker Distinction:** All orders assumed to be taker

### Leverage Simulation

**NOT IMPLEMENTED** in backtest.

Position sizing uses `cashDeployCap` but does not simulate:
- Margin requirements
- Liquidation price
- Funding rate payments
- Margin calls

### Metrics Calculated

**Performance Metrics (line 270-310):**

1. **Total Return:** `(final_equity - initial_balance) / initial_balance * 100`
2. **Total Trades:** Count of closed positions
3. **Win Rate:** `winning_trades / total_trades * 100`
4. **Profit Factor:** `gross_profit / gross_loss` (if gross_loss > 0)
5. **Average Win:** `total_win_pnl / winning_trades`
6. **Average Loss:** `total_loss_pnl / losing_trades`
7. **Max Consecutive Losses:** Tracked during backtest
8. **Max Drawdown:** `(equity_series - peak) / peak` (peak-to-trough)
9. **Sharpe Ratio:** `(mean_return - 0) / std_return * sqrt(252)` (annualized, assuming daily returns)

**Equity Curve:**
- Recorded after each trade close
- Stored in `self.equity_curve` (list of dicts with timestamp and equity)

### Limitations

**Identified Limitations:**

1. **No Realistic Slippage Model:**
   - Fixed 0.03% slippage (does not vary with volatility or order size)
   - No market impact modeling

2. **No Fee Modeling Variations:**
   - Assumes 0.06% taker fee (Zoomex may have different fees)
   - No maker rebates
   - No VIP tier discounts

3. **Ignores Funding:**
   - Perpetual futures have 8-hour funding payments
   - Backtest does not simulate funding rate impact on PnL

4. **No Partial Fills:**
   - Assumes 100% fill at signal price + slippage
   - Real orders may fill partially or not at all

5. **No Order Book Depth:**
   - Does not check if order size exceeds available liquidity

6. **No Latency Simulation:**
   - Assumes instant order placement and fill
   - Real trading has 100-300ms latency

7. **No Rejected Orders:**
   - Assumes all orders are accepted by exchange
   - Real orders can be rejected (insufficient margin, invalid params, etc.)

8. **Lookahead Bias Risk:**
   - Uses `_closed_candle_view()` to avoid incomplete candles
   - BUT: TP/SL checks use intra-candle high/low (line 200-210), which may introduce lookahead bias

---

## F. Paper Trading Behavior

### How to Enable

**CLI Command:**

```bash
python run_bot.py --mode paper --config configs/zoomex_example.yaml
```

### Implementation

**Location:** `run_bot.py`, method `_run_paper_cycle()` (line 167-216)

**Behavior:**

1. **Fetches Live Market Data:**
   - Calls `client.get_klines()` from Zoomex API (testnet or mainnet, depending on config)
   - Uses real-time candle data

2. **Computes Signals:**
   - Calls `compute_signals(closed_df)` (same as live mode)
   - Logs signal values (price, fast MA, slow MA, VWAP, RSI)

3. **Logs Signal (No Orders):**
   - If `long_signal == True`, logs:
     ```
     📈 LONG SIGNAL DETECTED (PAPER MODE)
     Price: 150.1234
     Fast MA: 151.5678
     Slow MA: 149.9012
     VWAP: 150.3456
     RSI: 45.67
     ⚠️ No order placed (paper mode)
     ```
   - If `long_signal == False`, logs debug message with signal values

4. **No Order Execution:**
   - Does NOT call `enter_long_with_brackets()`
   - Does NOT track positions or PnL
   - Does NOT simulate fills, fees, or slippage

### Testnet vs. Paper

**Testnet Mode:**
- Uses `https://openapi-testnet.zoomex.com`
- Places **real orders** on testnet
- Tracks **real positions** via API
- Uses **testnet API keys**

**Paper Mode:**
- Uses testnet OR mainnet API for market data (depending on `config.perps.useTestnet`)
- **Does NOT place orders**
- **Does NOT track positions** (no state management)
- Only logs signals

### Differences Between Paper and Live Paths

**Code Divergence (line 153-156 in `run_bot.py`):**

```python
if self.mode == "paper":
    await self._run_paper_cycle()
else:
    await self.perps_service.run_cycle()
```

**Potential "Works in Paper, Breaks in Live" Issues:**

1. **No Position Tracking in Paper:**
   - Paper mode does not call `_refresh_account_state()`
   - Live mode relies on `current_position_qty` to prevent duplicate entries
   - **Risk:** Paper may generate more signals than live (no position check)

2. **No API Error Handling in Paper:**
   - Paper mode only fetches candles (no order placement)
   - Live mode may encounter order rejection errors (insufficient margin, invalid params)
   - **Risk:** Paper does not test error recovery logic

3. **No Leverage Setting in Paper:**
   - Paper mode does not call `set_leverage()`
   - Live mode sets leverage on first order
   - **Risk:** Paper does not test leverage API call

4. **No Quantity Rounding in Paper:**
   - Paper mode does not call `round_quantity()`
   - Live mode may reject orders if quantity is below `min_qty`
   - **Risk:** Paper may show signals that cannot be executed live

5. **No Circuit Breaker State in Paper:**
   - Paper mode does not track `consecutive_losses`
   - Live mode circuit breaker will never trigger (PnL tracking not implemented)
   - **Risk:** Paper does not test circuit breaker behavior

**Recommendation:** Use **testnet mode** for realistic testing, not paper mode.

---

## G. Logging, Error Handling & Crash Behavior

### Logging Library

**Library:** Python `logging` module (stdlib)

**Configuration (line 32-39 in `run_bot.py`):**

```python
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/trading.log", mode="a"),
    ],
)
```

**Log Levels:**
- `INFO`: Default level (strategy decisions, orders, account state)
- `DEBUG`: Verbose (candle data, signal values)
- `WARNING`: Non-critical issues (circuit breaker, insufficient data)
- `ERROR`: Critical failures (API errors, exceptions)

### Log Destinations

**Console:** `sys.stdout` (real-time output)

**File:** `logs/trading.log` (append mode)

**File Path:** Relative to working directory (must create `logs/` directory manually)

**No Log Rotation:** File grows indefinitely (no max size or backup count)

### Key Log Events

**Strategy Decisions:**

```python
logger.info("📈 LONG SIGNAL DETECTED (PAPER MODE)")
logger.info("Already in position, skipping entry")
logger.info("No signal: price=150.12 fast=151.56 slow=149.90 rsi=45.67")
```

**Orders Placed:**

```python
logger.info("Leverage set to 1x")
logger.info("Position sizing: equity=$1000.00 risk=0.50% stop_loss=1.00% price=150.1234 => qty=1.333000")
logger.info("Entry plan: qty=1.333000 entry=150.1234 tp=154.6271 sl=148.6222 R:R=3.00")
logger.info("Entering long SOLUSDT qty=1.333000 tp=154.6271 sl=148.6222 R:R=3.00")
logger.info("Order placed: 1234567890abcdef")
```

**Risk Limit Hits:**

```python
logger.warning("Circuit breaker triggered: 3 consecutive losses")
logger.warning("Wallet equity unavailable; skipping entry")
logger.warning("Quantity 0.000100 below minimum 0.001000 for SOLUSDT")
```

**Errors / Exceptions:**

```python
logger.error("Zoomex API error: Insufficient margin")
logger.error("Perps cycle error: ...", exc_info=True)
logger.error("HTTP 429: Rate limit exceeded")
```

### Error Handling

**Zoomex API Errors:**

**Retry Logic (line 92-122 in `zoomex_v3.py`):**

```python
backoff = 1
for attempt in range(1, self.max_retries + 1):
    try:
        # ... make request ...
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        logger.warning(f"Request failed (attempt {attempt}): {e}")
        if attempt >= self.max_retries:
            raise
        await asyncio.sleep(backoff)
        backoff *= 2  # Exponential backoff: 1s, 2s, 4s
```

**Max Retries:** 3 attempts

**Backoff:** Exponential (1s, 2s, 4s)

**Timeout:** 15 seconds per request

**Raised Exception:** `ZoomexError` (subclass of `RuntimeError`)

**Caught in `PerpsService.run_cycle()` (line 108-111):**

```python
except ZoomexError as e:
    logger.error("Zoomex API error: %s", e)
except Exception as e:
    logger.error("Perps cycle error: %s", e, exc_info=True)
```

**Behavior:** Logs error and continues to next cycle (does NOT crash bot)

**Unhandled Exception in Main Loop:**

**Caught in `run_bot.py` (line 160-165):**

```python
except KeyboardInterrupt:
    logger.info("Received shutdown signal")
except Exception as e:
    logger.error(f"Trading loop error: {e}", exc_info=True)
finally:
    await self.shutdown()
```

**Behavior:**
- Logs exception with full traceback
- Calls `shutdown()` to close HTTP session
- **Does NOT attempt to cancel open orders**
- **Does NOT close open positions**

### Graceful Shutdown

**Shutdown Method (line 218-226 in `run_bot.py`):**

```python
async def shutdown(self):
    logger.info("Shutting down bot...")
    self.running = False
    if self.session:
        await self.session.close()
        logger.info("HTTP session closed")
    logger.info("Shutdown complete")
```

**What It Does:**
- Closes aiohttp session
- Logs shutdown message

**What It Does NOT Do:**
- Cancel open orders
- Close open positions
- Save state to disk
- Send alerts/notifications

**Risk:** If bot crashes with open position, TP/SL orders remain on exchange (good), but no manual intervention is triggered.

---

## H. Known Limitations, TODOs & Technical Debt

### TODOs from Code

**Found via `grep TODO`:**

1. **`src/strategy.py:824`**: `# TODO: Implement additional ladder logic for entries 2/3`
   - Ladder entries (25%, 35%, 40%) are configured but NOT implemented in perps strategy

2. **`src/strategy.py:878`**: `# TODO: Add volatility spike check`
   - No volatility filter in perps strategy (ATR-based filters exist in config but unused)

### Technical Debt

**Hardcoded Values:**

1. **Indicator Periods (perps_trend_vwap.py):**
   - SMA(10), SMA(30), RSI(14) are hardcoded
   - Should be configurable via `config.perps.indicators`

2. **Backtest Fees/Slippage (backtest_perps.py):**
   - `fee_rate = 0.0006`, `slippage_rate = 0.0003` are hardcoded
   - Should use `config.backtesting.commission` and `config.backtesting.slippage`

3. **Retry Limits (zoomex_v3.py):**
   - `max_retries = 3` is hardcoded in client init
   - Should be configurable

**Duplicate Logic:**

1. **Position Sizing:**
   - `risk_position_size()` in `perps_executor.py`
   - Similar logic in `backtest_perps.py` (line 91-97)
   - Should be unified

2. **Signal Computation:**
   - `compute_signals()` called in both `run_bot.py` (paper mode) and `perps.py` (live mode)
   - Duplicate candle filtering logic (`_closed_candle_view()`)

**Unused Modules:**

1. **`src/main.py`:**
   - `TradingEngine` class is not used by `run_bot.py`
   - Appears to be legacy code for multi-timeframe strategy

2. **`src/paper_trader.py`:**
   - `PaperBroker` class is not used by perps paper mode
   - High-fidelity simulation (slippage, fees, partial fills) is wasted

3. **`src/strategy.py`:**
   - Multi-timeframe strategy (regime, setup, signals) is not used by perps
   - Config sections `strategy`, `risk_management.ladder_entries`, `risk_management.stops` are ignored

**Unused Config Sections:**

- `trading.max_positions` (perps only trades one symbol)
- `trading.max_daily_risk` (not enforced)
- `trading.max_sector_exposure` (not enforced)
- `strategy.*` (entire section unused by perps)
- `risk_management.ladder_entries` (not implemented)
- `risk_management.stops.soft_atr_multiplier` (not used; perps uses fixed %)
- `paper.*` (not used by perps paper mode)

### Missing Tests

**No Unit Tests Found for:**

- `src/services/perps.py` (core trading logic)
- `src/strategies/perps_trend_vwap.py` (signal generation)
- `src/engine/perps_executor.py` (position sizing)
- `src/exchanges/zoomex_v3.py` (API client)

**Existing Tests (not reviewed):**

- `tests/test_strategy.py` (for legacy multi-timeframe strategy)
- `test_integration.py` (integration test, unclear if it covers perps)

### Risky for Live Trading

**Critical Gaps:**

1. **No Consecutive Loss Tracking in Live Mode:**
   - Circuit breaker relies on `consecutive_losses` counter
   - Counter is NEVER updated in `PerpsService` (no PnL tracking)
   - **Risk:** Circuit breaker will never trigger in live trading

2. **No Daily Loss Limit:**
   - Config has `max_daily_risk: 0.05` (5%)
   - NOT enforced in perps strategy
   - **Risk:** Bot can lose more than 5% in a single day

3. **No Max Drawdown Check:**
   - Config has `crisis_mode.drawdown_threshold: 0.10` (10%)
   - NOT enforced in perps strategy
   - **Risk:** Bot can continue trading after 10% drawdown

4. **No Position Reconciliation:**
   - Bot tracks `current_position_qty` in memory
   - If bot crashes and restarts, position state is lost
   - **Risk:** Bot may open duplicate positions after restart

5. **No Order Cancellation on Shutdown:**
   - Graceful shutdown does NOT cancel open orders
   - TP/SL orders remain on exchange (good)
   - But no alert is sent to user
   - **Risk:** User may not know bot has stopped

6. **No Funding Rate Tracking:**
   - Perpetual futures have 8-hour funding payments
   - Bot does not track funding PnL
   - **Risk:** Actual PnL may differ from expected (especially for long-held positions)

7. **No Liquidation Price Check:**
   - Bot does not calculate or monitor liquidation price
   - **Risk:** Position may be liquidated if price moves against it (especially with leverage > 1x)

8. **No API Rate Limit Handling:**
   - Zoomex has rate limits (e.g., 50 requests/second)
   - Bot retries on HTTP 429 but does not implement rate limiting
   - **Risk:** Bot may be temporarily banned for excessive requests

9. **No Duplicate Order Prevention:**
   - Bot uses `uuid.uuid4().hex` for `order_link_id`
   - If retry logic re-sends same order, new UUID is generated
   - **Risk:** Duplicate orders may be placed on retries

10. **No Margin Check Before Order:**
    - Bot assumes equity is sufficient for order
    - Does not check available margin or margin ratio
    - **Risk:** Order may be rejected for insufficient margin

---

## I. Concrete Commands to Run

### Prerequisites

1. **Install Python 3.10+**
2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
3. **Create logs directory:**
   ```bash
   mkdir logs
   ```
4. **Set environment variables:**
   ```bash
   export ZOOMEX_API_KEY="your_testnet_key"
   export ZOOMEX_API_SECRET="your_testnet_secret"
   ```

### Run Backtest

**Command:**

```bash
python tools/backtest_perps.py --symbol SOLUSDT --start 2024-01-01 --end 2024-12-31 --interval 5
```

**Options:**
- `--symbol`: Trading symbol (e.g., `BTCUSDT`, `ETHUSDT`, `SOLUSDT`)
- `--start`: Start date (YYYY-MM-DD)
- `--end`: End date (YYYY-MM-DD)
- `--interval`: Candle interval in minutes (default: 5)
- `--initial-balance`: Starting capital (default: 1000.0)

**Output:**
- Logs to console
- Saves results to `backtest_results_SOLUSDT_20240101_20241231.json`

### Run Paper Mode

**Command:**

```bash
python run_bot.py --mode paper --config configs/zoomex_example.yaml
```

**Behavior:**
- Fetches live market data
- Logs signals (no orders placed)
- Runs indefinitely (Ctrl+C to stop)

**Note:** Paper mode does NOT simulate positions or PnL. Use testnet for realistic testing.

### Run Testnet Mode

**Command:**

```bash
python run_bot.py --mode testnet --config configs/zoomex_example.yaml
```

**Behavior:**
- Places real orders on Zoomex testnet
- Uses testnet API keys
- Tracks real positions via API
- Runs indefinitely (Ctrl+C to stop)

**Safety:**
- Bot forces `useTestnet=true` even if config says `false`
- No real money at risk

### Enable Live Mode (DO NOT RUN YET)

**Step 1: Update Config**

Edit `configs/my_config.yaml`:

```yaml
perps:
  useTestnet: false  # CRITICAL: Set to false for live trading
  # ... other settings ...
```

**Step 2: Set Live API Keys**

```bash
export ZOOMEX_API_KEY="your_live_api_key"
export ZOOMEX_API_SECRET="your_live_api_secret"
```

**Step 3: Run Bot**

```bash
python run_bot.py --mode live --config configs/my_config.yaml
```

**Safety Prompt:**

Bot will display:

```
⚠️  RUNNING IN LIVE MODE - REAL MONEY AT RISK  ⚠️
  - Real orders will be placed on mainnet
  - Real funds will be used
  - Real profit/loss will occur
Type 'I UNDERSTAND THE RISKS' to continue:
```

You must type **exactly** `I UNDERSTAND THE RISKS` (case-sensitive) to proceed.

**DO NOT RUN THIS COMMAND** until all questions in Section J are answered and reviewed by ChatGPT.

---

## J. Questions for Human + ChatGPT Before Live Trading

### 1. Capital & Risk Preferences

**Questions for Human:**

- **Q1.1:** What is your starting capital for live trading? (e.g., $1000, $5000, $10000)
- **Q1.2:** What is the maximum acceptable daily loss in % of starting capital? (e.g., 5%, 10%)
- **Q1.3:** What is the maximum acceptable daily loss in absolute dollars? (e.g., $50, $100, $500)
- **Q1.4:** What is the maximum acceptable drawdown (peak-to-trough) before you want the bot to stop? (e.g., 10%, 15%, 20%)
- **Q1.5:** What is your target risk per trade as a % of equity? (Current default: 0.5%)
- **Q1.6:** Are you comfortable with the current position sizing formula (risk-based with 20% cash cap)? Or do you want a fixed dollar amount per trade?

**Questions for ChatGPT:**

- **Q1.7:** Given the current position sizing logic (`cashDeployCap = 20%`), is the risk per trade (0.5%) effectively capped by the cash cap? Should the cash cap be increased or decreased?
- **Q1.8:** The bot does NOT enforce `max_daily_risk` (5% in config). Should this be implemented before live trading?
- **Q1.9:** The bot does NOT track drawdown in real-time. Should this be implemented before live trading?

### 2. Trading Preferences

**Questions for Human:**

- **Q2.1:** Which symbol(s) do you want to trade initially? (Current default: SOLUSDT)
- **Q2.2:** Which timeframe (candle interval) do you want to use? (Current default: 5 minutes)
- **Q2.3:** Do you want to trade 24/7, or only during specific hours? (e.g., 9am-5pm UTC)
- **Q2.4:** Do you want to avoid trading on weekends? (Crypto markets are open 24/7, but liquidity may be lower)
- **Q2.5:** Do you want to enable `earlyExitOnCross` (exit on MA bear cross)? (Current default: false)
- **Q2.6:** What leverage do you want to use? (Current default: 1x)
- **Q2.7:** Are you comfortable with the current stop-loss (1%) and take-profit (3%) percentages? (R:R = 3:1)

**Questions for ChatGPT:**

- **Q2.8:** The strategy is long-only (no short signals). Is this appropriate for the current market regime?
- **Q2.9:** The strategy uses a simple SMA crossover (10/30) with VWAP and RSI filters. Is this robust enough for live trading, or should additional filters be added (e.g., trend filter, volatility filter)?
- **Q2.10:** The strategy does NOT check higher timeframe trend (e.g., daily EMA200). Should this be added?

### 3. Operational Constraints

**Questions for Human:**

- **Q3.1:** Will the bot run 24/7 on a dedicated server, or on your local machine?
- **Q3.2:** Do you have a plan for monitoring the bot? (e.g., check logs daily, set up alerts)
- **Q3.3:** Will you be available to manually intervene if the bot encounters issues? (e.g., API errors, unexpected losses)
- **Q3.4:** Do you want to receive alerts/notifications? (e.g., Telegram, email, SMS)
  - If yes, for which events? (e.g., order placed, position closed, circuit breaker triggered, error occurred)
- **Q3.5:** How often do you plan to review the bot's performance? (e.g., daily, weekly)
- **Q3.6:** Do you have a plan for restarting the bot if it crashes? (e.g., systemd service, Docker restart policy)

**Questions for ChatGPT:**

- **Q3.7:** The bot does NOT send alerts/notifications. Should this be implemented before live trading?
- **Q3.8:** The bot does NOT save state to disk. If it crashes with an open position, it will not remember the position on restart. Should state persistence be implemented?
- **Q3.9:** The bot does NOT cancel open orders on shutdown. Is this acceptable, or should graceful shutdown cancel all orders?

### 4. Technical Gaps Identified by Deep Agent

**Questions for ChatGPT:**

- **Q4.1:** **CRITICAL:** The circuit breaker (`consecutiveLossLimit`) is configured but NEVER triggers in live mode because `consecutive_losses` is not updated after trades close. Should this be fixed before live trading?
  - If yes, how should consecutive losses be tracked? (e.g., query exchange API for closed positions, track TP/SL fills via websocket)

- **Q4.2:** **CRITICAL:** The bot does NOT track daily loss or enforce `max_daily_risk` (5% in config). Should this be implemented before live trading?
  - If yes, how should daily loss be calculated? (e.g., sum of realized PnL since midnight UTC, or rolling 24-hour window)

- **Q4.3:** **CRITICAL:** The bot does NOT track drawdown or enforce `crisis_mode.drawdown_threshold` (10% in config). Should this be implemented before live trading?
  - If yes, how should drawdown be calculated? (e.g., peak equity since bot start, or peak equity in last 30 days)

- **Q4.4:** The bot does NOT reconcile position state on startup. If it crashes with an open position and restarts, it will not know about the existing position. Should position reconciliation be implemented?
  - If yes, should the bot query the exchange API for open positions on startup?

- **Q4.5:** The bot does NOT track funding rate payments (8-hour funding for perpetual futures). Should funding PnL be tracked?
  - If yes, should the bot query the exchange API for funding history, or estimate funding based on position size and funding rate?

- **Q4.6:** The bot does NOT calculate or monitor liquidation price. Should this be implemented?
  - If yes, should the bot log a warning if liquidation price is within X% of current price?

- **Q4.7:** The bot does NOT implement rate limiting for API requests. Should this be added to avoid hitting Zoomex rate limits?
  - If yes, what rate limit should be used? (e.g., 10 requests/second)

- **Q4.8:** The bot uses `uuid.uuid4().hex` for `order_link_id`, which generates a new ID on each retry. Should idempotent order IDs be implemented to prevent duplicate orders on retries?
  - If yes, should the bot use a deterministic ID based on timestamp + symbol + side?

- **Q4.9:** The bot does NOT check available margin before placing orders. Should this be implemented?
  - If yes, should the bot query the exchange API for margin balance and calculate margin ratio before each order?

- **Q4.10:** The bot's paper mode does NOT simulate positions or PnL (only logs signals). Should the human use testnet mode instead of paper mode for realistic testing?

- **Q4.11:** The backtest does NOT simulate funding rate payments, partial fills, or realistic slippage. Should the human run a longer testnet trial (e.g., 1 week) before going live?

- **Q4.12:** The bot does NOT have unit tests for core trading logic (`PerpsService`, `compute_signals`, `risk_position_size`). Should tests be written before live trading?

- **Q4.13:** The bot's error handling logs exceptions but does NOT send alerts. If the bot encounters a critical error (e.g., API key invalid, insufficient margin), how will the human be notified?

- **Q4.14:** The bot's graceful shutdown does NOT close open positions. If the human stops the bot with Ctrl+C, open positions will remain on the exchange with TP/SL orders. Is this acceptable?

- **Q4.15:** The strategy uses hardcoded indicator periods (SMA 10/30, RSI 14). Should these be made configurable before live trading?

- **Q4.16:** The strategy does NOT have a trend filter (e.g., only trade longs when price > daily EMA200). Should this be added?

- **Q4.17:** The strategy does NOT have a volatility filter (e.g., skip trades when ATR is > 2x average). Should this be added?

- **Q4.18:** The strategy does NOT have a volume filter (e.g., skip trades when volume is < 0.8x average). Should this be added?

- **Q4.19:** The strategy does NOT have a time-of-day filter (e.g., avoid trading during low-liquidity hours). Should this be added?

- **Q4.20:** The strategy does NOT have a correlation filter (e.g., avoid trading when BTC is in a strong downtrend). Should this be added?

### 5. Edge Cases & Failure Scenarios

**Questions for ChatGPT:**

- **Q5.1:** What should the bot do if the Zoomex API is down for > 5 minutes?
  - Options: (a) Keep retrying indefinitely, (b) Stop trading and send alert, (c) Close all positions and stop

- **Q5.2:** What should the bot do if it receives an "Insufficient margin" error when placing an order?
  - Options: (a) Skip the trade and log warning, (b) Reduce position size and retry, (c) Stop trading and send alert

- **Q5.3:** What should the bot do if it detects a position on the exchange that it did not open (e.g., manual trade by user)?
  - Options: (a) Ignore it, (b) Close it immediately, (c) Stop trading and send alert

- **Q5.4:** What should the bot do if the exchange rejects an order due to "Invalid quantity" (e.g., below minimum)?
  - Options: (a) Skip the trade and log warning, (b) Round up to minimum and retry, (c) Stop trading and send alert

- **Q5.5:** What should the bot do if it detects extreme volatility (e.g., price moves > 10% in 1 minute)?
  - Options: (a) Continue trading normally, (b) Skip trades until volatility normalizes, (c) Close all positions and stop

- **Q5.6:** What should the bot do if it detects a "flash crash" (e.g., price drops 20% then recovers in 1 minute)?
  - Options: (a) Continue trading normally, (b) Pause trading for X minutes, (c) Close all positions and stop

- **Q5.7:** What should the bot do if the circuit breaker triggers (e.g., 3 consecutive losses)?
  - Options: (a) Stop trading until manual restart, (b) Pause for X hours then resume, (c) Reduce position size by 50% and resume

- **Q5.8:** What should the bot do if it detects a "stuck" position (e.g., position open for > 24 hours without TP/SL hit)?
  - Options: (a) Continue waiting for TP/SL, (b) Close position manually, (c) Adjust TP/SL to current market conditions

---

**END OF BRIEF**

---

## Next Steps

1. **Human:** Answer all questions in Section J (Capital, Trading, Operational)
2. **Human:** Share this brief + answers with ChatGPT for review
3. **ChatGPT:** Review technical gaps (Section J.4) and provide recommendations
4. **Human + ChatGPT:** Decide which gaps must be fixed before live trading
5. **Deep Agent (if needed):** Implement required fixes based on ChatGPT's recommendations
6. **Human:** Run extended testnet trial (e.g., 1 week) to validate fixes
7. **Human + ChatGPT:** Final review of testnet results before enabling live mode

**DO NOT enable live trading until all critical gaps are addressed and testnet results are satisfactory.**
