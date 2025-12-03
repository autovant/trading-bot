# Multi-Timeframe ATR Trend Strategy (Zoomex Perps)

## Overview
- **Timeframes**: 5m execution with 1h trend filter.
- **Trend gate**: Only take longs when 1h close > 1h EMA200.
- **Entry**: 5m EMA20 > EMA50 (structure up), price pulls back into/near EMA20 (body cross or wick within `wickAtrBuffer * ATR`), ATR above `minAtrPct | minAtrUsd`, and optional RSI/volume filters pass.
- **Stops/targets**: Stop distance = `max(hardStopMinPct, atrStopMultiple * ATR)`. TP1 = `tp1Multiple * stop_distance`; TP2 = `tp2Multiple * stop_distance`. Default behavior moves the stop to breakeven after TP1 (backtest) and caps hold time via `maxBarsInTrade`.

## When It Works Best
- Clean, directional markets where hourly structure is rising and 5m pullbacks are respected.
- Sessions with enough realized volatility for ATR to clear `minAtrPct`, but not so extreme that `atrRiskScaling` throttles sizing aggressively.
- Assets with steady liquidity (BTC/ETH/SOL perps) so EMA/ATR signals are not dominated by gaps.

## When To Avoid
- Choppy, range-bound regimes where 1h closes churn around EMA200.
- Low-liquidity hours where 5m ATR falls below `minAtrPct` or volume filters often fail.
- News-driven spikes where ATR% explodes far above threshold; consider enabling `atrRiskScaling` to auto-dial risk down.

## Key Config Knobs
- **htfInterval**: Higher timeframe for regime filter (default `60` minutes). Requires ≥200 HTF bars for EMA200 warmup.
- **atrStopMultiple / hardStopMinPct**: Controls initial stop width. Raise `hardStopMinPct` on thin books to avoid micro stops.
- **tp1Multiple / tp2Multiple**: Expressed in R from the ATR stop. TP2 is used for the primary bracket live; TP1 is simulated/managed in backtests.
- **minAtrPct / minAtrUsd**: Volatility floor. Increase to skip drift sessions; decrease for quieter pairs.
- **maxEmaDistanceAtr / wickAtrBuffer**: Chasing and pullback tightness controls. Lower `maxEmaDistanceAtr` to avoid late entries far above EMA20.
- **exitOnTrendFlip / maxBarsInTrade**: Early-exit controls when HTF trend breaks or a position lingers too long.
- **useRsiFilter / useVolumeFilter**: Optional guardrails to avoid overbought prints or dead liquidity periods.
- **atrRiskScaling{Threshold,Factor}**: Reduces `riskPct` when ATR% exceeds the threshold; safety caps (cashDeployCap, margin checks) still apply.

## Operator Notes
- Backtests: run `python tools/backtest_perps.py --symbol BTCUSDT --interval 5 --use-multi-tf-atr-strategy ...` to view R-multiples, TP hit rates, and duration stats.
- Live: the Zoomex bracket uses TP2 and the ATR stop; TP1/breakeven logic is conservative (no added exposure). All safety gates run before entries and before strategy-managed exits.
- Warmup: ensure historical fetches include at least 200 HTF bars plus ATR/EMA warmup on the 5m feed; otherwise, the strategy will stay flat until indicators mature.

## Data Preparation
- History fetchers now reuse `ZoomexV3Client.get_klines`, so `--base-url`/`--testnet` match the runtime client. Output is merged/deduped into `data/history/{SYMBOL}_{INTERVAL}m.csv` with ISO timestamps.
- Single symbol example (6–12 months of 5m data):  
  `python tools/fetch_history.py --symbol SOLUSDT --interval 5 --start 2023-01-01 --end 2023-12-31 --base-url https://openapi.zoomex.com`
- Multiple symbols in one go (BTC/ETH/SOL, respects `--testnet` or `--base-url`):  
  `python tools/fetch_history_all.py --symbols SOLUSDT,BTCUSDT,ETHUSDT --interval 5 --start 2023-01-01 --end 2023-12-31`
- Long ranges paginate automatically; reruns append without duplicating rows. Aim for 6–12 months of data before running sweeps/backtests.

## Backtesting Data Sources
- `--data-source zoomex` (default) pulls klines using the Zoomex public API (still uses ZoomexV3Client paths, live/testnet unchanged).
 - `--data-source csv` loads local OHLCV without hitting the network. Default path: `data/history/{SYMBOL}_{INTERVAL}m.csv` unless overridden by `--csv-path`.
- CSV schema: columns `timestamp|time|start`, `open`, `high`, `low`, `close`, `volume`; timestamp can be ms since epoch or ISO8601 UTC. The loader normalizes to UTC index.

## Building Better Backtests Quickly
- Populate CSV history first to get non-empty strategy sweeps:
  1. `python tools/fetch_history_all.py --start 2023-01-01 --end 2023-12-31`
  2. (or per symbol) `python tools/fetch_history.py --symbol SOLUSDT --interval 5 --start 2023-01-01 --end 2023-12-31`
  3. Re-run `python tools/run_strategy_sweep.py`
- Aim for 6–12 months of 5m data per symbol so the trade-count/profit-factor filters have enough sample size.

## Sweep Modes (production vs exploration)
- `tools/run_strategy_sweep.py` supports `--mode`:
  - `production` (default): stricter trade-count gate for selecting configs.
  - `exploration`: lowers the trade-count floor for diagnostics on short datasets only; not for live config selection.
- Keep runtime safety gates (PerpsService limits, state, AlertSink) enabled regardless of mode.
