# Perps Strategy Sweep Report
Date: 2025-11-30T17:17:35.654214
Data Source: CSV (data\history)
Mode: exploration

> [!WARNING]
> Running in EXPLORATION mode. Filters are relaxed (trades >= 10). Do not use these configs for live trading without further validation.


> [!NOTE]
> To get statistically meaningful results, first run:
> `python tools/fetch_history_all.py`
> then run: `python tools/run_strategy_sweep.py`
> You should have at least 6–12 months of 5m data per symbol.

## Summary
| Symbol | Profile | PF | Max DD % | Win % | Avg R | Trades | RiskPct |
|--------|---------|----|----------|-------|-------|--------|---------|
| BTCUSDT | Conservative | N/A | - | - | - | - | - |
| BTCUSDT | Standard | N/A | - | - | - | - | - |
| BTCUSDT | Aggressive | N/A | - | - | - | - | - |

## BTCUSDT Analysis
Top 3 Configs by Score:

| Rank | PF | DD% | Trades | Params |
|------|----|-----|--------|--------|
| 1 | 1.07 | -0.57 | 16 | atrStopMultiple=1.5, tp2Multiple=2.0, maxBarsInTrade=100 |
| ETHUSDT | Conservative | N/A | - | - | - | - | - |
| ETHUSDT | Standard | 1.66 | -0.39% | 77.3% | 0.17 | 22 | 0.003 |
| ETHUSDT | Aggressive | 1.66 | -0.39% | 77.3% | 0.17 | 22 | 0.004 |

## ETHUSDT Analysis
Top 3 Configs by Score:

| Rank | PF | DD% | Trades | Params |
|------|----|-----|--------|--------|
| 1 | 1.66 | -0.39 | 22 | atrStopMultiple=1.5, tp2Multiple=2.0, maxBarsInTrade=100 |
| 2 | 1.50 | -0.39 | 21 | atrStopMultiple=1.5, tp2Multiple=2.0, maxBarsInTrade=100 |
| SOLUSDT | Conservative | N/A | - | - | - | - | - |
| SOLUSDT | Standard | 1.72 | -0.92% | 65.7% | 0.29 | 35 | 0.003 |
| SOLUSDT | Aggressive | 1.72 | -0.92% | 65.7% | 0.29 | 35 | 0.004 |

## SOLUSDT Analysis
Top 3 Configs by Score:

| Rank | PF | DD% | Trades | Params |
|------|----|-----|--------|--------|
| 1 | 1.72 | -0.92 | 35 | atrStopMultiple=1.5, tp2Multiple=2.0, maxBarsInTrade=100 |
| 2 | 1.72 | -0.92 | 35 | atrStopMultiple=1.5, tp2Multiple=2.0, maxBarsInTrade=100 |