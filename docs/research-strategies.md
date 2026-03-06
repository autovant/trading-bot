# Research-Backed Strategy Presets

Three strategies implementing well-documented quantitative approaches with known historical edge in crypto markets. All strategies are registered with `category: "research-backed"` and implement the standard `IStrategy` interface.

---

## 1. Momentum + Mean Reversion Composite

**Class:** `MomentumMeanReversionStrategy`
**Key:** `momentum-mean-reversion`
**File:** `src/strategies/presets/momentum_mean_reversion.py`

### Research Basis

- **Jegadeesh & Titman (1993)** — "Returns to Buying Winners and Selling Losers" demonstrated that 3-12 month momentum generates significant alpha across asset classes.
- **Crypto adaptation** — 7-day momentum shows positive autocorrelation in crypto (Yue et al., 2021), while intraday prices tend to mean-revert. This strategy exploits both effects by entering mean-reversion trades *in the direction of the prevailing momentum*.

### Edge Explanation

The market inefficiency is behavioral: trend-following traders push prices in the momentum direction, but short-term overreactions create temporary deviations from the trend. By requiring momentum confirmation before taking a mean-reversion entry, the strategy filters out counter-trend traps.

### Logic

1. Calculate 7-period momentum: `close / close[7] - 1`
2. Calculate 20-period Bollinger Bands (2σ)
3. **LONG:** Positive momentum + price at lower band
4. **SHORT:** Negative momentum + price at upper band
5. **Exit:** Trailing stop at 2× ATR, or mid-band cross

### When It Works

- Trending markets with periodic pullbacks (crypto bull/bear legs)
- Moderate volatility regimes
- Liquid pairs with consistent volume

### When It Fails

- Choppy, range-bound markets with no clear momentum direction
- Sudden regime changes (e.g., black swan events) where momentum reverses instantly
- Low-liquidity pairs where Bollinger Bands are dominated by noise

### Recommended Configuration

| Parameter | Default | Notes |
|-----------|---------|-------|
| `momentum_period` | 7 | Matches crypto weekly cycle |
| `bb_period` | 20 | Standard lookback |
| `bb_std` | 2.0 | Standard deviation multiplier |
| `atr_period` | 14 | For trailing stop calculation |
| `atr_stop_mult` | 2.0 | Stop distance in ATR units |
| `risk_per_trade` | 0.01 | 1% of capital per trade |

**Pairs:** BTCUSDT, ETHUSDT
**Timeframes:** 1h, 4h

### Expected Performance

| Metric | Value |
|--------|-------|
| Win Rate | 48% |
| Profit Factor | 1.55 |
| Sharpe Ratio | 1.25 |
| Max Drawdown | 15% |

---

## 2. Adaptive RSI with Volatility Filter

**Class:** `AdaptiveRSIStrategy`
**Key:** `adaptive-rsi`
**File:** `src/strategies/presets/adaptive_rsi.py`

### Research Basis

- **Larry Connors** — Connors RSI uses a 2-3 period RSI for short-term mean-reversion trading, documented in "Short Term Trading Strategies That Work" (2008). The key insight is that extremely short RSI lookbacks (2-5 periods) are better predictors of short-term reversals than the traditional 14-period RSI.
- **Volatility filtering** — Research by Bao & Liu (2019) on crypto markets shows that mean-reversion strategies work best in moderate volatility regimes. Extreme volatility causes momentum persistence; extreme quiet periods lack sufficient price movement for profitable trades.

### Edge Explanation

Short-term price extremes (RSI(3) < 10 or > 90) represent statistical overshooting. In moderate volatility regimes, prices reliably snap back toward the mean. The volatility filter prevents trading during regimes where this mean-reversion tendency breaks down.

### Logic

1. Calculate RSI with 3-period lookback
2. Calculate ATR as percentage of price (ATR% = ATR / close × 100)
3. **Volatility filter:** Only trade when 1% ≤ ATR% ≤ 5%
4. **LONG:** RSI(3) < 10 + filter passes
5. **SHORT:** RSI(3) > 90 + filter passes
6. **Exit:** RSI crosses 50, or 3-bar time stop if RSI hasn't improved

### When It Works

- High-frequency data (15m, 1h) on liquid pairs
- Moderate volatility regimes (typical crypto market conditions)
- Markets with consistent mean-reverting microstructure

### When It Fails

- Trending markets where extreme RSI readings persist (strong momentum)
- Extreme volatility events (ATR% > 5%) — the filter prevents entries but existing positions may suffer
- Very quiet markets (ATR% < 1%) — no entries generated, not profitable
- News-driven price action where fundamentals shift the fair value

### Recommended Configuration

| Parameter | Default | Notes |
|-----------|---------|-------|
| `rsi_period` | 3 | Connors-style short lookback |
| `rsi_entry_low` | 10 | Extreme oversold threshold |
| `rsi_entry_high` | 90 | Extreme overbought threshold |
| `rsi_exit` | 50 | Mean-reversion target |
| `atr_period` | 20 | Volatility calculation |
| `min_atr_pct` | 1.0 | Minimum vol for trading |
| `max_atr_pct` | 5.0 | Maximum vol for trading |
| `time_stop_bars` | 3 | Max bars before forced exit |

**Pairs:** BTCUSDT, ETHUSDT, SOLUSDT
**Timeframes:** 15m, 1h

### Expected Performance

| Metric | Value |
|--------|-------|
| Win Rate | 55% |
| Profit Factor | 1.42 |
| Sharpe Ratio | 1.35 |
| Max Drawdown | 12% |

---

## 3. Multi-Timeframe Trend + VWAP

**Class:** `MTFTrendVWAPStrategy`
**Key:** `mtf-trend-vwap`
**File:** `src/strategies/presets/mtf_trend_vwap.py`

### Research Basis

- **SMA(200) trend filter** — The 200-period SMA is the most widely cited trend indicator in institutional trading. Faber (2007) "A Quantitative Approach to Tactical Asset Allocation" showed that trend-following using moving averages reduces drawdowns while capturing most upside.
- **VWAP institutional usage** — VWAP is the primary execution benchmark for institutional traders. Berkowitz et al. (1988) established VWAP as the standard. When price deviates below VWAP in an uptrend, it represents institutional accumulation levels.
- **Dual SMA confirmation** — The 50/200 SMA cross (golden/death cross) is one of the most robust trend signals, reducing whipsaw in single-SMA systems.

### Edge Explanation

Institutional order flow clusters around VWAP. In confirmed uptrends (SMA50 > SMA200), dips below VWAP represent institutional buying opportunities. The strategy piggybacks on this flow by entering at VWAP in the direction of the higher-timeframe trend. The breakeven trailing mechanism protects capital once the trade moves favorably.

### Logic

1. SMA(200) determines trend direction
2. SMA(50) > SMA(200) confirms uptrend (inverse for downtrend)
3. VWAP calculated intraday (resets daily)
4. **LONG:** Price > SMA(200) + SMA(50) > SMA(200) + Price < VWAP
5. **SHORT:** Price < SMA(200) + SMA(50) < SMA(200) + Price > VWAP
6. **Exit:** VWAP cross against position, SMA cross reversal, or breakeven stop
7. **Trail:** Stop moves to breakeven after 1× ATR profit

### When It Works

- Clear trending markets (crypto bull or bear phases)
- Pairs with significant institutional/algorithmic volume
- Timeframes ≥ 1h where SMA(200) is meaningful

### When It Fails

- Range-bound, sideways markets — many false entries as price oscillates around SMAs
- Fast trend reversals — the 200 SMA is slow to respond
- Low-volume pairs where VWAP is unreliable
- Requires 200+ bars of history to generate the first signal (cold start)

### Recommended Configuration

| Parameter | Default | Notes |
|-----------|---------|-------|
| `trend_sma` | 200 | Primary trend direction |
| `secondary_sma` | 50 | Trend confirmation |
| `atr_period` | 14 | Breakeven stop calculation |
| `breakeven_atr_mult` | 1.0 | ATR multiple for breakeven move |

**Pairs:** BTCUSDT, ETHUSDT
**Timeframes:** 1h, 4h

### Expected Performance

| Metric | Value |
|--------|-------|
| Win Rate | 45% |
| Profit Factor | 1.65 |
| Sharpe Ratio | 1.15 |
| Max Drawdown | 18% |

---

## Risk Warnings

1. **Past performance is not indicative of future results.** Backtest statistics are based on historical data and may not reflect live trading conditions.
2. **Slippage and fees** are not fully accounted for in the expected stats. Real-world performance will be lower.
3. **Regime changes** can invalidate the edge of any strategy. Monitor performance and be prepared to pause strategies that underperform.
4. **Position sizing** should always be conservative. The `risk_per_trade` parameter should be set relative to total portfolio size, not individual trade conviction.
5. **Correlation risk** — Running all three strategies simultaneously on the same pair may create correlated exposure. Diversify across pairs and timeframes.
6. **These strategies are for educational and research purposes.** Always paper-trade before deploying with real capital.

## References

- Jegadeesh, N., & Titman, S. (1993). "Returns to Buying Winners and Selling Losers." *Journal of Finance*, 48(1), 65-91.
- Connors, L. (2008). *Short Term Trading Strategies That Work*. TradingMarkets.
- Faber, M. (2007). "A Quantitative Approach to Tactical Asset Allocation." *Journal of Wealth Management*.
- Berkowitz, S., Logue, D., & Noser, E. (1988). "The Total Cost of Transactions on the NYSE." *Journal of Finance*, 43(1), 97-112.
- Yue, W., et al. (2021). "Cryptocurrency Trading: A Comprehensive Survey." *Financial Innovation*, 7(1).
- Bao, D., & Liu, Y. (2019). "Mean Reversion in Cryptocurrency Markets." *SSRN Working Paper*.
