# 1. Config Wiring Overview
The table below maps each safety-related configuration field to its implementation site so you can see exactly which knob affects which behavior.

| YAML path | Pydantic field | Where used | Behavior / notes |
| --- | --- | --- | --- |
| `perps.enabled` | `PerpsConfig.enabled` (`src/config.py:105-124`) | `run_bot.py:72-77`, `src/services/perps.py:38-68` | When false, `PerpsService.initialize()` logs "Perps trading disabled" and returns, so no orders or background jobs run. |
| `perps.useTestnet` | `PerpsConfig.useTestnet` | `src/services/perps.py:43-55`, `run_bot.py:96-112` | Selects Zoomex base URL/mode. `_validate_mode` forces `useTestnet=True` in testnet runs and forbids `True` in `live` mode to avoid routing orders to the wrong venue. |
| `perps.consecutiveLossLimit` | `PerpsConfig.consecutiveLossLimit` | `src/services/perps.py:292-299` | Optional circuit breaker. When set and `pnl_tracker.consecutive_losses >= limit`, `_check_risk_limits` logs a warning and stops the cycle before fetching data. |
| `perps.maxMarginRatio` | `PerpsConfig.maxMarginRatio` | `src/services/perps.py:176-185` | `_enter_long` calls `client.get_margin_info()` and refuses to place orders while Zoomex reports `marginRatio > maxMarginRatio`. |
| `perps.maxRequestsPerSecond` | `PerpsConfig.maxRequestsPerSecond` | `src/services/perps.py:49-55`, `src/exchanges/zoomex_v3.py:134-155` | Passed into `ZoomexV3Client`. `_rate_limit` sleeps to keep the per-second pace under this value. |
| `perps.maxRequestsPerMinute` | `PerpsConfig.maxRequestsPerMinute` | same as above | Enforces a rolling one-minute cap by sleeping for the remainder of the minute when the counter hits this limit. |
| `perps.sessionMaxTrades` | `PerpsConfig.sessionMaxTrades` | `src/services/perps.py:216-237, 332-365` | Optional session guard; `_check_session_limits` blocks new entries once `session_trades` reaches the limit. |
| `perps.sessionMaxRuntimeMinutes` | `PerpsConfig.sessionMaxRuntimeMinutes` | `src/services/perps.py:216-237, 332-365` | Optional session duration guard; `_check_session_limits` compares elapsed minutes since `initialize()` and halts new entries once exceeded. |
| `perps.stateFile` | `PerpsConfig.stateFile` | `src/services/perps.py:70-115`, `src/state/perps_state_store.py` | JSON path for persisted risk state (`peak_equity`, `daily_pnl_by_date`, `consecutive_losses`). Defaults to `data/perps_state.json`; `SAFETY_STATE_LOAD` logs when restored. |
| `perps.riskPct` | `PerpsConfig.riskPct` | `src/services/perps.py:198-205`, `src/engine/perps_executor.py:13-26` | Determines risk capital per trade (`equity * riskPct`) before the stop-distance adjustment in `risk_position_size`. |
| `perps.stopLossPct` | `PerpsConfig.stopLossPct` | `src/services/perps.py:198-227` | Used in sizing math (`risk_dollars/stopLossPct`) and to compute the stop price for brackets. |
| `perps.takeProfitPct` | `PerpsConfig.takeProfitPct` | `src/services/perps.py:225-236` | Sets take-profit distance and the logged risk/reward ratio. |
| `perps.cashDeployCap` | `PerpsConfig.cashDeployCap` | `src/engine/perps_executor.py:13-26` | Limits USD deployed per trade to `cashDeployCap * equity` regardless of stop distance. |
| `perps.leverage` | `PerpsConfig.leverage` | `src/services/perps.py:187-195` | Applied once per process via `set_leverage` before the first order so that Zoomex account leverage matches the config. |
| `perps.triggerBy` | `PerpsConfig.triggerBy` | `src/services/perps.py:224-250`, `src/exchanges/zoomex_v3.py:279-306` | Passed as both `tpTriggerBy` and `slTriggerBy` in the bracket order payload. |
| `perps.earlyExitOnCross` | `PerpsConfig.earlyExitOnCross` | `src/services/perps.py:100-144` | If true and the fast MA crosses below the slow MA, `_check_early_exit` issues a reduce-only order and clears `current_position_qty` before new entries are evaluated. |
| `trading.max_daily_risk` | `TradingConfig.max_daily_risk` (`src/config.py:137-144`) | Passed into `PerpsService` via `run_bot.py`/`src/main.py` and stored as `self.max_daily_loss_pct`, which `_check_risk_limits` now uses directly (no hard-coded fallback unless trading config is absent). |
| `risk_management.crisis_mode.drawdown_threshold` | `CrisisModeConfig.drawdown_threshold` | Likewise injected into `PerpsService` as `self.drawdown_threshold`; `_check_risk_limits` compares drawdown against this configurable percentage rather than the previous 10% literal. |
| `risk_management.crisis_mode.volatility_multiplier` | `CrisisModeConfig.volatility_multiplier` | Defined in config, but no module references it; there is no volatility-based limiter in the current code. |

**Unused safety knobs.**
- `risk_management.crisis_mode.volatility_multiplier` is present in every YAML example yet never read in any module.

**Strategy independence.**
- `perps.useMultiTfAtrStrategy` and its ATR/EMA tuning knobs only influence signal generation. All safety gates (`_check_risk_limits`, `_check_session_limits`, margin checks, reconciliation guard) still run ahead of `_enter_long`, and strategy-managed exits rely on reduce-only orders so they cannot increase exposure.

# 2. PnL & Circuit Breaker Wiring

**PnLTracker design (`src/engine/pnl_tracker.py`).**
- `peak_equity` tracks the high-water mark of wallet equity so drawdowns can be expressed as `(peak - current)/peak`.
- `daily_pnl` is a dict keyed by `YYYY-MM-DD`; `record_trade` adds the trade PnL to the current date and logs the running total (lines 31-52).
- `consecutive_losses` increments when `pnl < 0` and resets to zero on any non-negative trade (lines 38-42).
- `trade_history` stores dicts with timestamp, pnl, and date for deduplication and later inspection.
- Helper methods: `update_peak_equity` logs new highs (lines 17-21), `get_drawdown` computes the percentage drawdown (lines 22-26), `get_daily_pnl` fetches the current day's tally (lines 54-58), and `cleanup_old_days` prunes stale records (lines 59-68). No other module currently calls `cleanup_old_days`.

**Integration points in `PerpsService` (`src/services/perps.py`).**
- `PerpsService.__init__` creates `self.pnl_tracker = PnLTracker()` (line 37), so all counters reset whenever the process or strategy restarts.
- `_check_risk_limits` (lines 292-330) is the only runtime gate that consults the tracker before data fetching. It reads `consecutive_losses`, `get_daily_pnl()`, `peak_equity`, and `get_drawdown(self.equity_usdt)` to decide whether to block the cycle.
- `_check_position_pnl` (lines 332-365) is the sole producer of tracker data. After throttling to once per 5 minutes, it calls `client.get_closed_pnl` and, for each unseen entry, feeds the realized `closedPnl` and its `createdTime` timestamp into `record_trade` before calling `update_peak_equity(self.equity_usdt)`.
- `_load_persisted_state` reads `perps.stateFile` via `src/state/perps_state_store.py` and, when present, seeds the tracker while logging `SAFETY_STATE_LOAD`. `_persist_state` rewrites that JSON snapshot after every recorded trade or new peak so daily-loss/drawdown/circuit-breaker counters survive process restarts.

**Definition of a closed trade.**
- The bot does not infer closes from internal fills. Instead, `_check_position_pnl` fetches Zoomex's `closed-pnl` endpoint for the configured symbol (lines 343-360) with a lookback of 24 hours and `limit=10`. Any rows returned by the exchange are treated as closed trades.
- Deduplication is timestamp-only: if a `createdTime` matches any `trade_history["timestamp"]`, it is skipped (lines 356-359), so two fills with identical timestamps will be merged even if quantities differ.
- Entry and exit prices are whatever Zoomex's API used to compute `closedPnl`; the bot never recalculates PnL from position history.

**Consecutive loss circuit breaker.**
- `record_trade` increments `consecutive_losses` only when `pnl < 0`; any profitable or breakeven trade resets the counter (lines 38-42).
- `_check_risk_limits` compares the counter to `self.config.consecutiveLossLimit` and logs `logger.warning("Circuit breaker: %d consecutive losses (limit=%d)", ...)` before returning `False` when the limit is reached (lines 293-299).
- Because `run_cycle` (lines 68-114) runs the same path for both live and testnet accounts, the circuit breaker applies identically in both modes—as long as `_check_position_pnl` successfully records trades.

**Operational caveats.**
- `_check_position_pnl` now runs while flat and is throttled via `self.last_position_check_time`, which is initialized to `None` in `PerpsService.__init__`. The method stamps the timestamp after every fetch, so the first invocation succeeds instead of raising `AttributeError`.
- No part of the bot persists tracker state, so restarting the bot still clears `daily_pnl`, `consecutive_losses`, and `peak_equity` and effectively disables the breaker until fresh trades occur.

# 3. Entry Gating Logic (What Checks Run Before a Trade)

1. `run_cycle` (`src/services/perps.py:68-74`) exits immediately if perps trading is disabled or the Zoomex client failed to initialize during `initialize()`.
2. `_refresh_account_state` (lines 163-170) now runs before any gating so the latest wallet equity and position size drive every subsequent check.
3. `_check_position_pnl` (lines 332-365) executes after the refresh to ingest closed trades even when the bot is flat; it is throttled to once every five minutes via `last_position_check_time`.
4. `_check_risk_limits` (lines 292-330) then enforces:
   - `config.consecutiveLossLimit` (circuit breaker).
   - `TradingConfig.max_daily_risk` via the injected `self.max_daily_loss_pct`.
   - `risk_management.crisis_mode.drawdown_threshold` via the injected `self.drawdown_threshold`.
   - The reconciliation guard, which blocks new entries if startup detected a short/hedged position externally.
   If any condition fails, `run_cycle` skips signal generation and order placement for that candle.
5. `_check_session_limits` (lines 332-365) evaluates optional session guardrails: elapsed runtime vs. `sessionMaxRuntimeMinutes` and filled trades vs. `sessionMaxTrades`. Any breach logs a `SAFETY_SESSION_*` tag and halts entries for the rest of the run.
6. Market data: `client.get_klines(symbol, interval, limit=100)` (lines 80-88). If the DataFrame is empty or shorter than 35 rows, the bot logs "Insufficient klines data" and returns without trading.
6. `_closed_candle_view` (lines 154-161) trims the final, still-open candle unless enough time has elapsed. If fewer than 35 closed candles remain, the bot waits for more history.
7. Duplicate candle guard: `if self.last_candle_time == last_closed_time: return` (lines 93-95) once a candle has already been processed.
8. Signal evaluation: `compute_signals` returns a dict, and if `signals["long_signal"]` is `False`, `run_cycle` returns. When `config.earlyExitOnCross` is `True`, `_check_early_exit` (lines 118-134) now emits a single reduce-only exit (with clear logging) instead of the previous double-send bug.
9. Position occupancy: if `self.current_position_qty > 0`, the bot logs "Already in position, skipping entry" (lines 105-107) to avoid pyramiding.
11. `_enter_long` (lines 171-259) executes the sequence of pre-order checks:
    - Wallet sanity: if `equity_usdt <= 0`, it logs "Wallet equity unavailable" and aborts (lines 171-175).
    - Margin ratio: `client.get_margin_info` returns `marginRatio`, and entries are skipped when `marginRatio > config.maxMarginRatio` (lines 176-185).
    - Leverage: the first order sets leverage via `set_leverage(symbol, buy=sell=config.leverage)` (lines 187-195).
    - Position sizing: `risk_position_size` (`src/engine/perps_executor.py:13-26`) converts account equity, `riskPct`, `stopLossPct`, and `cashDeployCap` into a raw quantity.
    - Precision: the code attempts to fetch instrument precision and calls `round_quantity` (`src/engine/perps_executor.py:29-38`) to enforce `min_qty`/`qty_step`. If rounding returns `None`, it logs a warning and aborts (lines 215-223).
    - Exit plans: take-profit and stop prices derive directly from `takeProfitPct` and `stopLossPct` (lines 225-236).
    - Order placement: `enter_long_with_brackets` (`src/engine/perps_executor.py:41-69`) submits a market order with bracket TP/SL, using a generated `order_link_id`. After a successful response, `current_position_qty` is set to the rounded quantity, `entry_equity` stores the pre-trade equity snapshot, and `_refresh_account_state` runs again (lines 244-259).

`PerpsService` performs no additional throttles beyond the klines, signal, and risk gates shown above. Once `_enter_long` starts, the next possible refusal point is the margin or sizing guard.

# 4. Daily Loss & Drawdown Enforcement

**Daily loss limit.**
- `_check_risk_limits` computes `daily_pnl = self.pnl_tracker.get_daily_pnl()` (line 301) and, as long as `self.equity_usdt > 0`, derives `daily_loss_pct = abs(daily_pnl) / self.equity_usdt` when `daily_pnl < 0` (lines 301-304).
- The limit is `self.max_daily_loss_pct`, which is populated from `TradingConfig.max_daily_risk` (default 5%) when `PerpsService` is constructed in `run_bot.py` and `src/main.py`. If the bot were ever instantiated without a trading config, it falls back to 5%.
- Realized PnL still comes entirely from the `closed-pnl` endpoint, but `_check_position_pnl` now runs while flat so losses propagate to the daily counter before the next entry attempt.
 - Daily boundaries remain implicit: `get_daily_pnl()` uses the current UTC date string, so a new entry starts at zero each UTC midnight once a trade has been recorded for that day. The latest per-day map (and the `consecutive_losses` counter) are mirrored into `perps.stateFile`, so restarting the bot mid-day retains the current daily loss figure and applies it immediately after `SAFETY_STATE_LOAD`.

**Drawdown limit.**
- Drawdown enforcement only runs when `self.pnl_tracker.peak_equity > 0` (line 316). `peak_equity` is updated via `update_peak_equity` inside `_check_position_pnl`, so it can lag or reset to zero on restart.
- When a peak exists, `_check_risk_limits` calls `pnl_tracker.get_drawdown(self.equity_usdt)` (lines 316-318) and compares it against `self.drawdown_threshold`, which now mirrors `risk_management.crisis_mode.drawdown_threshold`.
- A drawdown exceeding the configured percentage triggers `Drawdown limit exceeded: X% (limit=Y%)` and blocks the cycle, and the latest `peak_equity` snapshot is mirrored into `perps.stateFile`, so restarting the bot uses the last known high-water mark and continues enforcing drawdown immediately.

**Scope and persistence.**
- Both limits are enforced per process using in-memory state that is neither checkpointed nor restored. Restarting the bot fully clears daily PnL, drawdown, and consecutive loss history.
- `run_cycle` now refreshes wallet equity before `_check_risk_limits` executes, so daily loss and drawdown math rely on the latest balances instead of the previous cycle's snapshot.

# 5. Margin & Rate Limiting Behavior

**Margin ratio gate.**
- `_enter_long` now fetches `margin_info = await self.client.get_margin_info(symbol, position_idx)` so the client can filter by both symbol and `positionIdx`. `ZoomexV3Client.get_margin_info` (`src/exchanges/zoomex_v3.py:330-347`) returns `{"marginRatio": float, "availableBalance": float, "found": bool}`.
- When the Zoomex payload does not contain a matching position the client logs `Margin info not found...` and returns `found=False` with a conservative ratio of 0. `_enter_long` surfaces that condition with a warning and continues instead of silently using the first element.
- The guard remains `if margin_ratio > self.config.maxMarginRatio: ... skip entry`. `availableBalance` is still unused but is included for visibility/logging needs.

**Zoomex API rate limiting.**
- When `PerpsService.initialize` instantiates `ZoomexV3Client`, it passes `max_requests_per_second=self.config.maxRequestsPerSecond` and `max_requests_per_minute=self.config.maxRequestsPerMinute` (lines 49-55).
- Every high-level client method calls `_request`, and `_request` awaits `_rate_limit()` before performing the HTTP call (`src/exchanges/zoomex_v3.py:83-155`), so all REST traffic flows through the limiter.
- `_rate_limit` keeps the delta between requests above `1 / max_requests_per_second`, resets the minute counter every 60 seconds, and sleeps for the remaining time when the per-minute counter reaches the configured cap (lines 134-155). Whenever it sleeps, it now logs `SAFETY_RATE_LIMIT` at DEBUG level with the computed duration and limit values.

# 6. Position Reconciliation on Startup
- `PerpsService.initialize` refreshes account state, then calls `_reconcile_positions()` before declaring the service ready (lines 57-60).
- `_reconcile_positions` (`src/services/perps.py:260-291`) retrieves `client.get_positions(symbol)` and iterates through the exchange response looking for a row where `positionIdx == self.config.positionIdx`.
  - **Case A – No open position on exchange.** If Zoomex's response lacks a `"list"` key or every matching position has `size == 0`, the bot logs `logger.info("No open position found for %s during reconciliation", symbol)` and leaves `current_position_qty = 0`.
  - **Case B – One matching position.** When `size > 0`, it copies `abs(size)` into `self.current_position_qty`, parses `avgPrice` and `unrealisedPnl` purely for logging, and emits a warning `POSITION RECONCILIATION: Adopted existing position ... Side=<side>` (lines 270-286). The method also logs that PnL tracking may be inaccurate until the live position is closed. If the exchange reports a short (`side in {"Sell","Short"}`), `self.reconciliation_block_active` is set so `_check_risk_limits` blocks new entries until an operator intervenes.
  - **Case C – Exceptions or unexpected payloads.** Any exception (HTTP error, JSON mismatch) is logged as `logger.error("Position reconciliation failed: %s", e, exc_info=True)` (lines 288-290). If multiple non-zero positions exist, the method simply returns after the first match; extra legs are neither logged nor closed.

Because reconciliation only adjusts `current_position_qty`, the rest of the bot still believes it started the day flat: there is no sync of `entry_equity`, and no validation that the adopted position's direction matches the long-only strategy. (PnL counters are handled separately via the persisted `perps.stateFile`.)

# 7. Example Log Messages for Each Safety Event
- **Circuit breaker triggered** (WARNING):
  `WARNING src.services.perps SAFETY_CIRCUIT_BREAKER: 3 consecutive losses (limit=3)`
- **Daily loss limit hit** (WARNING):
  `WARNING src.services.perps SAFETY_DAILY_LOSS: Daily loss limit exceeded: 6.20% (limit=5.00%)`
- **Max drawdown limit hit** (WARNING):
  `WARNING src.services.perps SAFETY_DRAWDOWN: Drawdown limit exceeded: 12.00% (limit=10.00%)`
- **Margin ratio too high** (WARNING):
  `WARNING src.services.perps SAFETY_MARGIN_BLOCK: Margin ratio 85.00% exceeds limit 80.00%, skipping entry`
- **Position reconciliation adopted an open position** (WARNING):
  `WARNING src.services.perps SAFETY_RECON_ADOPT: Adopted existing position for SOLUSDT | Qty=1.000000 | Entry=$180.0000 | Unrealized PnL=$25.00 | Side=Buy`
- **Reconciliation guard blocking entries** (WARNING):
  `WARNING src.services.perps SAFETY_RECON_BLOCK: Reconciliation guard activated due to Sell exposure. New entries will be blocked until manual intervention.`
- **Session guards** (WARNING):
  `WARNING src.services.perps SAFETY_SESSION_RUNTIME: Session runtime 130.4 minutes exceeded limit=120; halting new entries for this run.`
  `WARNING src.services.perps SAFETY_SESSION_TRADES: Session trades=10 reached limit=10; halting new entries for this run.`
- **State restored on startup** (INFO):
  `INFO src.services.perps SAFETY_STATE_LOAD: Restored risk state peak_equity=$2500.00 consecutive_losses=2`
- **Rate limiter delaying a request** (DEBUG):
  `DEBUG src.exchanges.zoomex_v3 SAFETY_RATE_LIMIT: Sleeping 0.250s to respect per-second limit (sec=4)`

Each of these warnings also causes the `LoggingAlertSink` to emit an `ALERT[...]` line (for example, `ALERT[safety_daily_loss]: Daily loss 6.20% exceeded limit 5.00% | context={"symbol": "SOLUSDT", ...}`) that can be forwarded to external channels later.
# 8. Gaps, Ambiguities, and Recommended Clarifications
- **Unused `volatility_multiplier`.** The crisis-mode volatility multiplier is never read anywhere. Either remove it from configs or implement the intended volatility-based safety switch so operators know what to expect.
- **State persistence is local-only.** `perps.stateFile` lives in the local filesystem without replication/encryption; operators should back it up or migrate to a shared store if multiple bots share the same account.
- **Rate-limit visibility is DEBUG-only.** `_rate_limit` now emits `SAFETY_RATE_LIMIT` at DEBUG level; consider surfacing INFO metrics/alerts if throttling becomes common in production.
- **Reconciliation only updates quantity.** `_reconcile_positions` still ignores entry price, stop orders, and PnL tracker seeding. Even with the new guard, operators should expect some metrics (e.g., current drawdown) to remain inaccurate until the exchange position is flattened or additional state is synchronized.
- **Timestamp-only deduplication.** `_check_position_pnl` considers trades duplicates if their `createdTime` matches, even if the exchange reports multiple fills with the same timestamp. Incorporate additional keys (orderId, positionSeq) or store the exchange's `id` to avoid missing trades.
- **Economic assumptions not documented.** `record_trade` logs raw `closedPnl` from Zoomex without stating whether fees and funding are included. Operators need confirmation from exchange docs or additional logging so they know whether the daily loss metric already includes costs.

# Fix Pack 1 Updates
- **Config-driven limits:** `run_bot.py` and `src/main.py` now pass `TradingConfig.max_daily_risk` and `risk_management.crisis_mode.drawdown_threshold` into `PerpsService`, so `_check_risk_limits` enforces the same numbers as the rest of the bot instead of literals.
- **PnL ingestion reliability:** `last_position_check_time` is initialized in `PerpsService.__init__`, `_check_position_pnl` runs while flat, and its timestamp is updated after each fetch to avoid `AttributeError` and ensure fresh losses feed the circuit breaker.
- **Precision and margin safety:** `_enter_long` requests instrument precision via `ZoomexV3Client.get_precision`, and `get_margin_info` now filters by symbol/index and returns a `found` flag so the service can log missing data before proceeding.
- **Early-exit cleanup:** `_check_early_exit` logs the symbol/quantity once per bear cross and issues a single reduce-only order rather than two redundant orders.
- **Reconciliation guard:** `_reconcile_positions` logs side/qty for adopted positions and activates a guard that blocks new entries if a short/hedged position is detected on startup.

# Fix Pack 2 Updates
- **Safety log instrumentation:** `_check_risk_limits`, `_reconcile_positions`, `_enter_long`, and session guards now emit `SAFETY_*` tags covering every breaker (circuit, daily loss, drawdown, margin, reconciliation, session length/count). `ZoomexV3Client._rate_limit` also logs `SAFETY_RATE_LIMIT` whenever it sleeps.

# Fix Pack 3 Updates
- **Risk-state persistence and `SAFETY_STATE_LOAD`:** `perps.stateFile` is restored on startup and rewritten after every trade/peak-equity update so daily loss, drawdown, and consecutive-loss counters survive restarts.
- **Alert sink abstraction:** All critical `SAFETY_*` events (plus runtime errors) now flow through `AlertSink`, with the default `LoggingAlertSink` producing structured `ALERT[category]` log lines that can later be forwarded to chat/email.
- **Safety harness coverage:** `tests/test_safety_scenarios.py` and `tools/run_safety_validation.py` gained a `state_persistence` scenario to prove state restoration works end-to-end alongside the existing margin/session/risk tests.
- **Session guardrails:** `PerpsConfig` adds `sessionMaxTrades` / `sessionMaxRuntimeMinutes`; `_check_session_limits` halts entries mid-run with `SAFETY_SESSION_*` warnings once thresholds are exceeded.
- **Operator runbook:** `docs/TESTNET_SAFETY_RUNBOOK.md` documents the harness, sample configs, log-grep workflows, and intentional stress tests for each safety control.
