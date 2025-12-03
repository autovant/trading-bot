# Backtest Fixes - Summary

## Issues Identified

Your backtests were failing with "Backtest returned an empty result" because:

1. **Wrong backtest script** - The old `tools/backtest.py` expects multi-timeframe data (1h, 4h, 1d) but the perps strategy uses a single timeframe
2. **Data fetching issues** - The backtest wasn't properly handling API responses and date ranges
3. **No diagnostic tools** - Hard to debug why signals weren't being generated
4. **Strategy too strict** - The perps strategy conditions are very specific and may not trigger often

## Fixes Implemented

### 1. Rewrote `tools/backtest_perps.py` (539 lines)

**Key improvements:**
- ✅ Proper single-timeframe data fetching for perps
- ✅ Realistic execution simulation (slippage + fees)
- ✅ Better error handling and logging
- ✅ Incremental data fetching with rate limiting
- ✅ Proper signal generation using `compute_signals()`
- ✅ Comprehensive metrics calculation
- ✅ JSON export for results

**Usage:**
```bash
python tools/backtest_perps.py --symbol BTCUSDT --start 2024-11-01 --end 2024-11-30
```

### 2. Created `tools/diagnose_backtest.py` (329 lines)

**Diagnostic tool that tests:**
- ✅ Configuration loading
- ✅ Data fetching from API
- ✅ Indicator calculations (SMA, RSI, VWAP)
- ✅ Signal generation
- ✅ Market conditions analysis

**Usage:**
```bash
python tools/diagnose_backtest.py --symbol BTCUSDT --days 30
```

**Output shows:**
- How many signals are generated
- Why signals might not trigger
- Current indicator values
- Market condition statistics

### 3. Created `BACKTEST_TROUBLESHOOTING.md` (400 lines)

**Comprehensive guide covering:**
- ✅ Common issues and solutions
- ✅ Step-by-step debugging
- ✅ Strategy parameter tuning
- ✅ API troubleshooting
- ✅ Quick reference commands

### 4. Updated `README.md`

Added backtesting section with:
- ✅ Example commands
- ✅ Link to troubleshooting guide
- ✅ Diagnostic tool reference

## How to Use

### Step 1: Diagnose the Issue

```bash
python tools/diagnose_backtest.py --symbol BTCUSDT --days 30
```

This will show you:
- ✅ If data is being fetched correctly
- ✅ If indicators are calculating properly
- ✅ How many signals are generated
- ✅ Why signals might not trigger

### Step 2: Run the Backtest

```bash
python tools/backtest_perps.py \
  --symbol BTCUSDT \
  --start 2024-11-01 \
  --end 2024-11-30 \
  --initial-balance 1000
```

### Step 3: Interpret Results

**Good results:**
```
Total Trades: 15-50
Win Rate: 40-60%
Profit Factor: > 1.5
Max Drawdown: < 30%
```

**If no trades:**
- Strategy is too strict for the market conditions
- See troubleshooting guide for parameter adjustments

## Common Issues & Quick Fixes

### Issue: "No signals generated"

**Cause:** Strategy conditions too strict

**Fix:** Relax RSI range in `src/strategies/perps_trend_vwap.py`:

```python
# Current (strict):
and 30 < rsi_series.iloc[-1] < 65

# Relaxed (more signals):
and 25 < rsi_series.iloc[-1] < 70
```

### Issue: "No data available"

**Cause:** Invalid symbol or date range

**Fix:**
```bash
# Use recent dates
python tools/backtest_perps.py \
  --symbol BTCUSDT \
  --start 2024-12-01 \
  --end 2024-12-14

# Or try testnet
python tools/backtest_perps.py \
  --symbol BTCUSDT \
  --start 2024-12-01 \
  --end 2024-12-14 \
  --testnet
```

### Issue: "Insufficient data: X candles"

**Cause:** Date range too short

**Fix:** Use at least 7-14 days of data:
```bash
python tools/backtest_perps.py \
  --symbol BTCUSDT \
  --start 2024-11-01 \
  --end 2024-11-30
```

## Understanding the Strategy

The perps strategy requires **ALL** of these conditions:

1. **MA Crossover**: Fast MA(10) crosses above Slow MA(30)
2. **Price > VWAP**: Current close above VWAP
3. **RSI Range**: 30 < RSI < 65

This is intentionally strict to reduce false signals. The diagnostic tool will show you:
- How often each condition is met
- How many crossovers occur
- Current indicator values

## Files Changed/Created

### New Files
1. `tools/backtest_perps.py` - Fixed backtest engine (539 lines)
2. `tools/diagnose_backtest.py` - Diagnostic tool (329 lines)
3. `BACKTEST_TROUBLESHOOTING.md` - Troubleshooting guide (400 lines)
4. `BACKTEST_FIXES.md` - This summary (you're reading it!)

### Modified Files
1. `README.md` - Added backtesting section with links
2. `QUICK_REFERENCE.md` - Updated by user

## Next Steps

1. **Run diagnostic** to understand your data:
   ```bash
   python tools/diagnose_backtest.py --symbol BTCUSDT --days 30
   ```

2. **Run backtest** on a short period first:
   ```bash
   python tools/backtest_perps.py --symbol BTCUSDT --start 2024-12-01 --end 2024-12-14
   ```

3. **If no signals**, adjust strategy parameters (see troubleshooting guide)

4. **If successful**, test longer periods and multiple symbols

5. **Validate with paper trading** before going live

## Key Improvements

| Before | After |
|--------|-------|
| ❌ Wrong backtest script | ✅ Perps-specific backtest |
| ❌ No error messages | ✅ Detailed logging |
| ❌ No diagnostics | ✅ Diagnostic tool |
| ❌ Hard to debug | ✅ Troubleshooting guide |
| ❌ Multi-timeframe confusion | ✅ Single timeframe clarity |
| ❌ Poor error handling | ✅ Graceful error handling |

## Testing the Fixes

To verify everything works:

```bash
# 1. Test diagnostic tool
python tools/diagnose_backtest.py --symbol BTCUSDT --days 7

# 2. Test backtest on short period
python tools/backtest_perps.py --symbol BTCUSDT --start 2024-12-01 --end 2024-12-07

# 3. Test with different symbols
python tools/backtest_perps.py --symbol ETHUSDT --start 2024-12-01 --end 2024-12-07
python tools/backtest_perps.py --symbol SOLUSDT --start 2024-12-01 --end 2024-12-07

# 4. Test longer period if short period works
python tools/backtest_perps.py --symbol BTCUSDT --start 2024-11-01 --end 2024-12-14
```

## Support

If you still encounter issues:

1. Check `BACKTEST_TROUBLESHOOTING.md` for detailed solutions
2. Run diagnostic tool with debug logging:
   ```bash
   python tools/diagnose_backtest.py --symbol BTCUSDT --days 30 --log-level DEBUG
   ```
3. Verify your environment:
   ```bash
   python --version  # Should be 3.10+
   pip list | grep pandas
   ```

## Summary

The backtest failures were due to using the wrong backtest script and lack of diagnostic tools. The new `backtest_perps.py` is specifically designed for the perps strategy and includes proper error handling. The diagnostic tool helps identify issues quickly, and the troubleshooting guide provides solutions for common problems.

**You should now be able to run successful backtests!** 🎉
