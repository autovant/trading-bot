# Safety Validation Report

- Generated: 2025-11-30T22:53:06+00:00
- Commit: `1519982`

| Scenario | Config Highlights | Expected SAFETY Tags | Observed Tags | Result |
| --- | --- | --- | --- | --- |
| `normal_testnet_session` | sessionMaxTrades=5, sessionMaxRuntimeMinutes=5 | None | None | ✅ PASS |
| `session_trade_cap` | sessionMaxTrades=1 | SAFETY_SESSION_TRADES | SAFETY_SESSION_TRADES | ✅ PASS |
| `session_runtime_cap` | sessionMaxRuntimeMinutes=1 | SAFETY_SESSION_RUNTIME | SAFETY_SESSION_RUNTIME | ✅ PASS |
| `margin_block` | maxMarginRatio=0.10 | SAFETY_MARGIN_BLOCK | SAFETY_MARGIN_BLOCK | ✅ PASS |
| `risk_limiters` | max_daily_risk=0.05, drawdown_threshold=0.10 | SAFETY_CIRCUIT_BREAKER, SAFETY_DAILY_LOSS, SAFETY_DRAWDOWN | SAFETY_CIRCUIT_BREAKER, SAFETY_DAILY_LOSS, SAFETY_DRAWDOWN | ✅ PASS |
| `reconciliation_guard` | perps.positionIdx=0 | SAFETY_RECON_ADOPT, SAFETY_RECON_BLOCK | SAFETY_RECON_ADOPT, SAFETY_RECON_BLOCK | ✅ PASS |
| `reconciliation_adopt` | perps.positionIdx=0 | SAFETY_RECON_ADOPT | SAFETY_RECON_ADOPT | ✅ PASS |
| `state_persistence` | stateFile override, consecutiveLossLimit=1 | SAFETY_STATE_LOAD, SAFETY_CIRCUIT_BREAKER | SAFETY_CIRCUIT_BREAKER, SAFETY_STATE_LOAD | ✅ PASS |
| `rate_limit` | maxRequestsPerSecond=1000 | SAFETY_RATE_LIMIT | SAFETY_RATE_LIMIT | ✅ PASS |

## Scenario Details
### normal_testnet_session
Baseline simulation with generous limits; expect no SAFETY_* tags.

- Config overrides: `sessionMaxTrades=5, sessionMaxRuntimeMinutes=5`
- Expected tags: None
- Observed tags: None
- Log file: `logs\validation\normal_testnet_session.log`

### session_trade_cap
sessionMaxTrades=1 should trigger SAFETY_SESSION_TRADES after first trade.

- Config overrides: `sessionMaxTrades=1`
- Expected tags: SAFETY_SESSION_TRADES
- Observed tags: SAFETY_SESSION_TRADES
- Log file: `logs\validation\session_trade_cap.log`

### session_runtime_cap
sessionMaxRuntimeMinutes=1 forces SAFETY_SESSION_RUNTIME once elapsed.

- Config overrides: `sessionMaxRuntimeMinutes=1`
- Expected tags: SAFETY_SESSION_RUNTIME
- Observed tags: SAFETY_SESSION_RUNTIME
- Log file: `logs\validation\session_runtime_cap.log`

### margin_block
Very low maxMarginRatio results in SAFETY_MARGIN_BLOCK when entering.

- Config overrides: `maxMarginRatio=0.10`
- Expected tags: SAFETY_MARGIN_BLOCK
- Observed tags: SAFETY_MARGIN_BLOCK
- Log file: `logs\validation\margin_block.log`

### risk_limiters
Simulated PnL exceeds daily and drawdown caps plus circuit breaker.

- Config overrides: `max_daily_risk=0.05, drawdown_threshold=0.10`
- Expected tags: SAFETY_CIRCUIT_BREAKER, SAFETY_DAILY_LOSS, SAFETY_DRAWDOWN
- Observed tags: SAFETY_CIRCUIT_BREAKER, SAFETY_DAILY_LOSS, SAFETY_DRAWDOWN
- Log file: `logs\validation\risk_limiters.log`

### reconciliation_guard
Startup adopts an existing short position and blocks entries.

- Config overrides: `perps.positionIdx=0`
- Expected tags: SAFETY_RECON_ADOPT, SAFETY_RECON_BLOCK
- Observed tags: SAFETY_RECON_ADOPT, SAFETY_RECON_BLOCK
- Log file: `logs\validation\reconciliation_guard.log`

### reconciliation_adopt
Adopt a long position without triggering the block.

- Config overrides: `perps.positionIdx=0`
- Expected tags: SAFETY_RECON_ADOPT
- Observed tags: SAFETY_RECON_ADOPT
- Log file: `logs\validation\reconciliation_adopt.log`

### state_persistence
Persisted risk state is restored on restart.

- Config overrides: `stateFile override, consecutiveLossLimit=1`
- Expected tags: SAFETY_STATE_LOAD, SAFETY_CIRCUIT_BREAKER
- Observed tags: SAFETY_CIRCUIT_BREAKER, SAFETY_STATE_LOAD
- Log file: `logs\validation\state_persistence.log`

### rate_limit
Zoomex client throttling emits SAFETY_RATE_LIMIT.

- Config overrides: `maxRequestsPerSecond=1000`
- Expected tags: SAFETY_RATE_LIMIT
- Observed tags: SAFETY_RATE_LIMIT
- Log file: `logs\validation\rate_limit.log`

## Appendix: SAFETY_* Tags
Each log line carries a `SAFETY_*` tag to indicate which limiter engaged. Review `docs/TESTNET_SAFETY_RUNBOOK.md` for operational guidance.