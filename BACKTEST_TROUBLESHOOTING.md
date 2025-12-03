# Backtest Troubleshooting Guide

This guide helps you diagnose and fix common backtest issues.

## Quick Diagnosis

Run the diagnostic tool first:

```bash
python tools/diagnose_backtest.py --symbol BTCUSDT --days 30
```

This will test:
- ✅ Configuration loading
- ✅ Data fetching from API
- ✅ Indicator calculations
- ✅ Signal generation
- ✅ Market conditions analysis

## Common Issues and Solutions

### Issue 1: "Backtest returned an empty result"

**Symptoms:**
- Backtest completes but shows 0 trades
- No error messages
- Job status shows "FAILED"

**Causes:**
1. **No signals generated** - Strategy conditions too strict
2. **Data fetching failed** - API issues or invalid date range
3. **Configuration errors** - Missing or invalid parameters

**Solutions:**

#### A. Check if signals are being generated

```bash
# Run diagnostic to see signal count
python tools/diagnose_backtest.py --symbol BTCUSDT --days 30

# Look for this line:
# "Total signals in dataset: X"
```

If signals = 0, the strategy is too strict for the market conditions.

**Fix:** Adjust strategy parameters in `src/strategies/perps_trend_vwap.py`:

```python
# Current (strict):
long_signal = (
    fast.iloc[-2] < slow.iloc[-2]
    and fast.iloc[-1] > slow.iloc[-1]
    and current["close"] > vwap_series.iloc[-1]
    and 30 < rsi_series.iloc[-1] < 65  # Very narrow range
)

# Relaxed (more signals):
long_signal = (
    fast.iloc[-1] > slow.iloc[-1]  # Just check current state
    and current["close"] > vwap_series.iloc[-1]
    and 25 < rsi_series.iloc[-1] < 70  # Wider range
)
```

#### B. Verify data is being fetched

```bash
# Test data fetch
python tools/diagnose_backtest.py --symbol BTCUSDT --days 7

# Should see:
# "✅ Fetched X candles"
# "Date range: YYYY-MM-DD to YYYY-MM-DD"
```

If data fetch fails:
- Check internet connection
- Verify symbol is correct (BTCUSDT, ETHUSDT, etc.)
- Try testnet: `--testnet` flag
- Check API status: https://www.zoomex.com/api-status

#### C. Check configuration

```bash
# Verify config loads correctly
python -c "
import os
os.environ['CONFIG_PATH'] = 'configs/zoomex_example.yaml'
from src.config import get_config
config = get_config()
print(f'Symbol: {config.perps.symbol}')
print(f'Interval: {config.perps.interval}')
print(f'Risk: {config.perps.riskPct}')
"
```

### Issue 2: "No data available for timeframe"

**Symptoms:**
- Error: "Missing historical data for timeframes"
- Backtest fails immediately

**Cause:**
Using the old multi-timeframe backtest script instead of the perps-specific one.

**Solution:**
Use the correct backtest script:

```bash
# ❌ Wrong (old multi-timeframe backtest)
python tools/backtest.py --symbol BTCUSDT --start 2024-01-01 --end 2024-12-31

# ✅ Correct (perps backtest)
python tools/backtest_perps.py --symbol BTCUSDT --start 2024-01-01 --end 2024-12-31
```

### Issue 3: "Insufficient data: X candles (need 35+)"

**Symptoms:**
- Error message about insufficient candles
- Backtest exits immediately

**Cause:**
Date range too short or data fetch returned limited results.

**Solution:**

```bash
# Increase date range
python tools/backtest_perps.py \
  --symbol BTCUSDT \
  --start 2024-01-01 \
  --end 2024-12-31 \
  --interval 5

# Or use more recent dates
python tools/backtest_perps.py \
  --symbol BTCUSDT \
  --start 2024-11-01 \
  --end 2024-12-14 \
  --interval 5
```

### Issue 4: API Rate Limiting

**Symptoms:**
- Backtest hangs or times out
- Error: "Too many requests"

**Solution:**

The backtest script includes rate limiting (0.5s delay between requests), but if you still hit limits:

```bash
# Use smaller date ranges
python tools/backtest_perps.py \
  --symbol BTCUSDT \
  --start 2024-12-01 \
  --end 2024-12-14 \
  --interval 5

# Or use testnet (less traffic)
python tools/backtest_perps.py \
  --symbol BTCUSDT \
  --start 2024-12-01 \
  --end 2024-12-14 \
  --testnet
```

### Issue 5: "Error computing signals"

**Symptoms:**
- Backtest runs but shows errors during execution
- Some candles are skipped

**Cause:**
Missing or invalid data in some candles (NaN values).

**Solution:**

The backtest script now handles this gracefully by skipping problematic candles. If you see many errors:

```bash
# Run with debug logging
python tools/backtest_perps.py \
  --symbol BTCUSDT \
  --start 2024-12-01 \
  --end 2024-12-14 \
  --log-level DEBUG
```

Check for:
- Missing OHLCV data
- Zero volume candles
- Timestamp gaps

## Understanding Strategy Conditions

The perps strategy requires ALL of these conditions to trigger a long signal:

1. **MA Crossover**: Fast MA (10) crosses above Slow MA (30)
2. **Price above VWAP**: Current close > VWAP
3. **RSI in range**: 30 < RSI < 65

This is intentionally strict to reduce false signals. If you want more signals:

### Option A: Relax RSI range

```python
# In src/strategies/perps_trend_vwap.py
and 25 < rsi_series.iloc[-1] < 70  # Wider range
```

### Option B: Remove crossover requirement

```python
# Just check if fast > slow (not requiring a cross)
and fast.iloc[-1] > slow.iloc[-1]
```

### Option C: Remove VWAP filter

```python
# Comment out VWAP condition
# and current["close"] > vwap_series.iloc[-1]
```

## Testing Your Changes

After modifying the strategy:

```bash
# 1. Run diagnostic to see signal count
python tools/diagnose_backtest.py --symbol BTCUSDT --days 30

# 2. Run backtest on short period
python tools/backtest_perps.py \
  --symbol BTCUSDT \
  --start 2024-12-01 \
  --end 2024-12-14 \
  --initial-balance 1000

# 3. If successful, test longer period
python tools/backtest_perps.py \
  --symbol BTCUSDT \
  --start 2024-01-01 \
  --end 2024-12-14 \
  --initial-balance 1000 \
  --output results/backtest_btc_2024.json
```

## Interpreting Results

### Good Backtest Results

```
Total Trades: 15-50 (not too few, not too many)
Win Rate: 40-60% (realistic for trend following)
Profit Factor: > 1.5 (wins bigger than losses)
Max Drawdown: < 30% (manageable risk)
Sharpe Ratio: > 1.0 (good risk-adjusted returns)
```

### Warning Signs

```
Total Trades: < 5 (strategy too strict)
Total Trades: > 200 (strategy too loose, overtrading)
Win Rate: > 80% (likely overfitting)
Win Rate: < 30% (strategy not working)
Profit Factor: < 1.0 (losing money)
Max Drawdown: > 50% (too risky)
```

## Advanced Debugging

### Enable detailed logging

```bash
python tools/backtest_perps.py \
  --symbol BTCUSDT \
  --start 2024-12-01 \
  --end 2024-12-14 \
  --log-level DEBUG
```

### Check indicator values

```python
# Add to src/strategies/perps_trend_vwap.py
def compute_signals(df: pd.DataFrame) -> Dict[str, float | bool]:
    # ... existing code ...
    
    # Debug output
    print(f"Fast MA: {fast.iloc[-1]:.2f}")
    print(f"Slow MA: {slow.iloc[-1]:.2f}")
    print(f"VWAP: {vwap_series.iloc[-1]:.2f}")
    print(f"RSI: {rsi_series.iloc[-1]:.2f}")
    print(f"Signal: {long_signal}")
    
    return { ... }
```

### Analyze market conditions

```bash
# See why signals aren't triggering
python tools/diagnose_backtest.py --symbol BTCUSDT --days 30

# Look at "Market Conditions Analysis" section
# Shows:
# - MA crossover count
# - % of time above VWAP
# - % of time RSI in range
```

## Getting Help

If you're still having issues:

1. **Run full diagnostic:**
   ```bash
   python tools/diagnose_backtest.py --symbol BTCUSDT --days 30 > diagnostic.log 2>&1
   ```

2. **Check the logs:**
   - Look for ERROR or WARNING messages
   - Note which step fails

3. **Verify environment:**
   ```bash
   python --version  # Should be 3.10+
   pip list | grep pandas  # Check dependencies
   ```

4. **Test with known-good data:**
   ```bash
   # BTCUSDT is most liquid, should always work
   python tools/backtest_perps.py \
     --symbol BTCUSDT \
     --start 2024-11-01 \
     --end 2024-11-30 \
     --interval 5
   ```

## Quick Reference

### Diagnostic Commands

```bash
# Full diagnostic
python tools/diagnose_backtest.py --symbol BTCUSDT --days 30

# Test specific symbol
python tools/diagnose_backtest.py --symbol ETHUSDT --days 7

# Use testnet
python tools/diagnose_backtest.py --symbol BTCUSDT --testnet
```

### Backtest Commands

```bash
# Basic backtest
python tools/backtest_perps.py --symbol BTCUSDT --start 2024-11-01 --end 2024-11-30

# With custom balance
python tools/backtest_perps.py --symbol BTCUSDT --start 2024-11-01 --end 2024-11-30 --initial-balance 5000

# Save results
python tools/backtest_perps.py --symbol BTCUSDT --start 2024-11-01 --end 2024-11-30 --output results.json

# Debug mode
python tools/backtest_perps.py --symbol BTCUSDT --start 2024-11-01 --end 2024-11-30 --log-level DEBUG
```

## Common Fixes Summary

| Issue | Quick Fix |
|-------|-----------|
| No signals | Relax RSI range: `25 < rsi < 70` |
| No data | Check symbol name, use recent dates |
| Too slow | Use smaller date range |
| Rate limited | Add `--testnet` flag |
| Wrong script | Use `backtest_perps.py` not `backtest.py` |
| Config error | Check `CONFIG_PATH` environment variable |

## Next Steps

Once your backtest is working:

1. **Optimize parameters** - Test different MA periods, RSI ranges
2. **Test multiple symbols** - ETHUSDT, SOLUSDT, etc.
3. **Walk-forward testing** - Test on different time periods
4. **Paper trading** - Validate with live data before real money

Remember: A good backtest doesn't guarantee future profits. Always start with paper trading!
