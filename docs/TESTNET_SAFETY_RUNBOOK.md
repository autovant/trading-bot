# Testnet Safety Harness Runbook

## Overview
The Testnet Safety Harness layers operator-friendly safeguards on top of the perps bot: every critical limiter now emits `SAFETY_*` log tags for quick greps, Zoomex rate limiting announces when it sleeps, and optional session guards (`sessionMaxTrades`, `sessionMaxRuntimeMinutes`) halt new entries when a testnet session exceeds its planned scope. These additions sit alongside the existing `trading.max_daily_risk` and `risk_management.crisis_mode.drawdown_threshold` controls—nothing in the risk math changes, but you can now see and bound behavior much more clearly during extended testnet runs.

## Pre-run Checklist
1. **Config sanity (example cautious profile):**
   ```yaml
   trading:
     max_daily_risk: 0.02          # 2% daily loss cap

   risk_management:
     crisis_mode:
       drawdown_threshold: 0.05     # 5% max drawdown

   perps:
     sessionMaxTrades: 10
     sessionMaxRuntimeMinutes: 120
     consecutiveLossLimit: 3
     maxMarginRatio: 0.80
     useTestnet: true
   ```
2. **Environment:**
   - Launch with `--mode testnet`.
   - Confirm `perps.useTestnet: true` and valid Zoomex testnet API keys/secrets.
   - Ensure `logs/trading.log` is writable so tagged events are captured.

## How to Run a Testnet Session
```bash
python run_bot.py --mode testnet --config configs/zoomex_example.yaml
```
- Run at `INFO` level for normal monitoring; switch to `DEBUG` if you want to see `SAFETY_RATE_LIMIT` sleeps.
- Keep a terminal tailing `logs/trading.log` or use `grep 'SAFETY_' logs/trading.log` to spot safety events in real time.

## How to Interpret Safety Events
Use `grep 'SAFETY_' logs/trading.log` (or specific tags) to review. Each tag signals the following:

| Tag | Meaning | Immediate Action |
| --- | --- | --- |
| `SAFETY_CIRCUIT_BREAKER` | Consecutive loss cap hit via `perps.consecutiveLossLimit`. | Pause and inspect trade history; consider widening limits only after root-cause analysis. |
| `SAFETY_DAILY_LOSS` | Realized daily PnL breached `trading.max_daily_risk`. | Stop the bot, review account PnL, and confirm losses are understood before resuming. |
| `SAFETY_DRAWDOWN` | Equity drawdown exceeded `risk_management.crisis_mode.drawdown_threshold`. | Evaluate current market regime; optionally top up or wait for conditions to stabilize. |
| `SAFETY_MARGIN_BLOCK` | Exchange reported margin ratio above `perps.maxMarginRatio` (entry skipped). | Check Zoomex margin usage / leverage settings and reduce exposure. |
| `SAFETY_RECON_ADOPT` | Startup reconciliation adopted a live position. | Verify position direction/size on Zoomex; run flat before resuming automated entries. |
| `SAFETY_RECON_BLOCK` | Reconciliation detected a short/unsupported position or the guard is still active. | Close or manually manage the exchange position; restart once flat. |
| `SAFETY_SESSION_TRADES` | `sessionMaxTrades` reached—session guard halted new entries. | Restart with higher limit (if desired) or reset counters for a fresh session. |
| `SAFETY_SESSION_RUNTIME` | Session runtime exceeded `sessionMaxRuntimeMinutes`. | Decide whether to restart for another interval or leave the bot idle. |
| `SAFETY_RATE_LIMIT` | Zoomex client is intentionally sleeping to honor API rate caps. | No action needed; informational for debugging throughput. |
| `SAFETY_STATE_LOAD` | Persisted risk state restored from `perps.stateFile`. | Confirm the state file reflects current risk posture; delete it only if you intentionally want to reset limits. |

**Grep examples:**
```bash
grep 'SAFETY_' logs/trading.log
grep 'SAFETY_DAILY_LOSS' logs/trading.log
```

## State Persistence & Alerts
- **Risk state file:** Daily PnL, drawdown peak, and consecutive losses are mirrored into `perps.stateFile` (default `data/perps_state.json`). Keep this file with your deployment so restarts resume the same risk counters; delete it only when you intentionally want to reset limits.
- **Alert sink:** Every `SAFETY_*` warning also emits an `ALERT[...]` log line via `LoggingAlertSink`, e.g. `ALERT[safety_daily_loss]: Daily loss 6.20% exceeded limit 5.00% | context={'symbol': 'SOLUSDT', ...}`. Tail `logs/trading.log` for `ALERT[` to see a condensed feed, or wire a different sink later without touching trading logic.

## Suggested Test Scenarios (Testnet Only)
- **Daily loss trigger:** Set `trading.max_daily_risk: 0.001` and run one losing trade.
- **Drawdown trigger:** Lower `drawdown_threshold` to `0.02` and simulate rapid equity drop.
- **Margin block:** Temporarily set `maxMarginRatio: 0.10` to force `SAFETY_MARGIN_BLOCK` when any exposure exists.
- **Circuit breaker:** Set `consecutiveLossLimit: 1` and log a single losing trade.
- **Session guards:** Configure `sessionMaxTrades: 1` or `sessionMaxRuntimeMinutes: 1` to validate `SAFETY_SESSION_*` tags after one trade or minute.
- **Rate limiter:** Reduce `maxRequestsPerSecond` to `1` and set log level to `DEBUG` to observe `SAFETY_RATE_LIMIT` sleeps.

## Known Limitations / Next Steps
- The persisted state file is a local JSON snapshot—back it up (or move it to shared storage) if multiple hosts manage the same account.
- Alerts currently go to the log sink; hook another `AlertSink` (email/chat/etc.) if you need proactive notifications.
- Funding/fee components in `closedPnl` still follow Zoomex semantics; clarify with exchange docs if precision is critical.
- Closed-trade deduplication is timestamp-based; fills sharing the same `createdTime` may be coalesced.
- Session guards stop new entries but do not cancel open orders/positions—operators must manage exposure on Zoomex when a guard triggers.
