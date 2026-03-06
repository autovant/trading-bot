# Issue Tracker — Bug Hunt Results

Generated from comprehensive 5-phase bug hunt.
**Last Updated**: 2026-03-06
**Tests**: 568 passed, 21 skipped, 0 failed

---

## Quick Reference

| # | Severity | Category | File | Status |
|---|----------|----------|------|--------|
| 1 | CRITICAL | Undefined name (F821) | src/main.py | FIXED |
| 2 | CRITICAL | Wrong attribute (mypy) | src/services/execution.py | FIXED |
| 3 | CRITICAL | Wrong attribute (mypy) | src/services/agent_orchestrator.py | FIXED |
| 4 | CRITICAL | Missing metric defs | src/metrics.py | FIXED |
| 5 | CRITICAL | Route ordering | src/api/routes/backtest.py | FIXED |
| 6 | CRITICAL | Serialization crash | src/api/middleware/error_handler.py | FIXED |
| 7 | CRITICAL | Hardcoded default key | src/api/routes/system.py | FIXED |
| 8 | CRITICAL | Hardcoded secret | docker-compose.yml | FIXED |
| 9 | CRITICAL | Hardcoded secret | src/monolith.py | FIXED |
| 10 | HIGH | CORS wildcard | src/presentation/api.py | FIXED |
| 11 | HIGH | Timing-unsafe compare | src/api/routes/system.py | FIXED |
| 12 | HIGH | Silent NATS failure | src/messaging.py | FIXED |
| 13 | HIGH | Timezone-naive datetime | src/strategy.py | FIXED |
| 14 | HIGH | Deprecated utcnow() | src/presentation/api.py | FIXED |
| 15 | HIGH | Unbounded query limit | src/api/routes/market.py | FIXED |
| 16 | HIGH | Error detail leakage | src/api/routes/market.py | FIXED |
| 17 | HIGH | Test env pollution | tests/test_credential_vault.py | FIXED |
| 18 | MEDIUM | Exception chaining (B904) | src/api/routes/market.py | FIXED |
| 19 | MEDIUM | Exception chaining (B904) | src/api/routes/signals.py | FIXED |
| 20 | MEDIUM | Exception chaining (B904) | src/services/replay.py | FIXED |
| 21 | MEDIUM | Unused imports (F401) | multiple files | FIXED |
| 22 | MEDIUM | Import sorting (I001) | multiple files | FIXED |
| 23 | MEDIUM | F-string no placeholders | src/database.py, src/signal_engine/ | FIXED |
| 24 | MEDIUM | Name shadowing (F811) | src/api/routes/market.py | FIXED |
| 25 | LOW | Unused variables (F841) | src/services/perps.py, src/signal_engine/ | FIXED |
| 26 | LOW | Ambiguous variable name | src/signal_engine/plugins/structure_levels.py | FIXED |
| 27 | LOW | Unused loop variable | src/indicators.py | FIXED |
| 28 | HIGH | Hardcoded DB credentials | docker-compose.yml | FIXED |
| 29 | MEDIUM | WebSocket no auth | src/api/middleware/auth.py | NOTED |
| 30 | MEDIUM | GET endpoints no auth | src/api/middleware/auth.py | NOTED |
| 31 | LOW | Docs exposed in prod | src/api/middleware/auth.py | NOTED |
| 32 | CRITICAL | HMAC signature bypass | src/api/routes/signals.py | FIXED |
| 33 | HIGH | API key vault fallback | src/api/routes/system.py | FIXED |
| 34 | HIGH | Error detail leakage | src/api/routes/data.py | FIXED |
| 35 | HIGH | Error detail leakage | src/api/routes/vault.py | FIXED |
| 36 | HIGH | Error detail leakage | src/api/routes/backtest.py | FIXED |
| 37 | MEDIUM | Silent exception swallowing | src/api/routes/intelligence.py | FIXED |
| 38 | MEDIUM | WS double-disconnect race | src/api/ws.py | FIXED |
| 39 | CRITICAL | Undefined OrchestratorService | src/services/agent_orchestrator.py | FIXED |
| 40 | CRITICAL | Duplicate JSX closing tags | components/AIAssistant.tsx | FIXED |
| 41 | CRITICAL | Undefined setOrderPrice | App.tsx | FIXED |
| 42 | CRITICAL | Missing Zap import | App.tsx | FIXED |
| 43 | MEDIUM | Playwright slowMo wrong level | tests/demo.config.ts | FIXED |
| 44 | MEDIUM | Unused imports (ruff F401) | multiple files | FIXED |
| 45 | MEDIUM | Import sorting (ruff I001) | multiple files | FIXED |
| 46 | MEDIUM | Ambiguous variable name l | 3 strategy preset files | FIXED |
| 47 | MEDIUM | Unused variable agent_map | src/api/routes/market.py | FIXED |
| 48 | MEDIUM | Exception chaining B904 | src/api/routes/presets.py | FIXED |
| 49 | LOW | zip() without strict= | src/risk/portfolio_risk.py, src/signal_engine/plugins/base.py | FIXED |
| 50 | MEDIUM | Error detail leakage | src/api/routes/presets.py | FIXED |
| 51 | HIGH | npm dependency vulns | package.json deps | NOTED |
| 52 | CRITICAL | Undefined logger (F821) | src/api/routes/backtest.py | FIXED |
| 53 | CRITICAL | Undefined logger (F821) | src/api/routes/data.py | FIXED |
| 54 | CRITICAL | Wrong attribute sharpe_ratio | src/api/routes/intelligence.py | FIXED |
| 55 | CRITICAL | Missing _disconnecting slot | src/api/ws.py | FIXED |
| 56 | CRITICAL | Nonexistent DB methods | src/services/strategy_store.py | FIXED |
| 57 | CRITICAL | Wrong attr pnl/total_trades | src/api/routes/agents.py | FIXED |
| 58 | CRITICAL | Missing created_at arg | src/api/routes/market.py | FIXED |
| 59 | HIGH | TelegramNotifier type confusion | src/api/routes/notifications.py | FIXED |
| 60 | HIGH | Missing get_strategy_by_name | src/database.py (Postgres backend) | FIXED |
| 61 | HIGH | Silent _finalise_fill crash | src/paper_trader.py | FIXED |
| 62 | MEDIUM | Unused hmac import (F401) | src/api/middleware/auth.py | FIXED |
| 63 | MEDIUM | Variable shadow fills (mypy) | src/paper_trader.py | FIXED |
| 64 | MEDIUM | Unsorted imports (I001) | src/notifications/__init__.py | FIXED |
| 65 | LOW | Unused exception vars (F841) | src/api/routes/backtest.py, data.py, vault.py | FIXED |
| 66 | MEDIUM | Missing prev_open None guard | src/strategies/presets/vwap_scalping.py | FIXED |
| 67 | HIGH | Race: unsync market cache | src/services/agent_orchestrator.py | NOTED |
| 68 | HIGH | Race: unsync WS connection sets | src/signal_engine/alert_router.py | NOTED |

---

## Detailed Entries

### ISS-001: Undefined `aiohttp` import crashes at class instantiation
**Category**: Static Analysis (F821)
**Severity**: CRITICAL
**Symptoms**: `aiohttp.ClientSession` type hint used without importing `aiohttp`; NameError at runtime
**Root Cause**: Missing import statement
**Solution**: Added `try: import aiohttp except ImportError: aiohttp = None` at top of file
**Files Changed**: src/main.py

### ISS-002: `DatabaseConfig.path` attribute does not exist
**Category**: Type Error (mypy)
**Severity**: CRITICAL
**Symptoms**: `AttributeError: 'DatabaseConfig' object has no attribute 'path'` at service startup
**Root Cause**: `DatabaseConfig` defines `.url`, not `.path`
**Solution**: Changed `self.config.database.path` → `self.config.database.url`
**Files Changed**: src/services/execution.py, src/services/agent_orchestrator.py

### ISS-003: Missing Prometheus metric definitions
**Category**: Type Error (mypy)
**Severity**: CRITICAL
**Symptoms**: `ImportError` when risk.py or execution.py import `CIRCUIT_BREAKERS` or `REJECT_RATE`
**Root Cause**: Metrics referenced but never defined in src/metrics.py
**Solution**: Added `CIRCUIT_BREAKERS = Counter(...)` and `REJECT_RATE = Gauge(...)` definitions
**Files Changed**: src/metrics.py

### ISS-004: Route ordering shadow — `/api/backtests/history` captured as `{job_id}`
**Category**: Runtime Logic
**Severity**: CRITICAL
**Symptoms**: GET `/api/backtests/history` returns 404; "history" matched as a job_id parameter
**Root Cause**: FastAPI matches routes in definition order; `{job_id}` route defined before `/history`
**Solution**: Moved `/history` route before `/{job_id}` route
**Files Changed**: src/api/routes/backtest.py

### ISS-005: Pydantic v2 ValidationError serialization crash
**Category**: Runtime Error
**Severity**: CRITICAL
**Symptoms**: `TypeError: Object of type ValueError is not JSON serializable` in error handler
**Root Cause**: Pydantic v2 `exc.errors()` returns dicts with `ctx` containing raw `ValueError` objects
**Solution**: Added try/except fallback extracting only `msg`, `loc`, `type` fields
**Files Changed**: src/api/middleware/error_handler.py

### ISS-006: Hardcoded insecure default API key
**Category**: Security (A07 Broken Auth)
**Severity**: CRITICAL
**Symptoms**: System accepts `"default-insecure-key"` as valid API key when `API_KEY` env unset
**Root Cause**: `os.getenv("API_KEY", "default-insecure-key")` provides fallback
**Solution**: Removed default; fail with 503 if unset; use `hmac.compare_digest` for timing safety
**Files Changed**: src/api/routes/system.py

### ISS-007: Hardcoded `secret-key` in docker-compose.yml
**Category**: Security (A05 Misconfiguration)
**Severity**: CRITICAL
**Symptoms**: `API_KEY: ${API_KEY:-secret-key}` exposes known credential in compose file
**Solution**: Changed to `${API_KEY:?API_KEY must be set}` — fails fast if not provided
**Files Changed**: docker-compose.yml

### ISS-008: Hardcoded `secret-key` in monolith.py
**Category**: Security (A07 Broken Auth)
**Severity**: CRITICAL
**Symptoms**: Unconditionally sets `API_KEY=secret-key` if not already set
**Solution**: Generates random key with `secrets.token_urlsafe(32)` and logs warning
**Files Changed**: src/monolith.py

### ISS-009: CORS wildcard `allow_origins=["*"]` with credentials
**Category**: Security (A05 Misconfiguration)
**Severity**: HIGH
**Symptoms**: Any website can make authenticated cross-origin requests
**Solution**: Read origins from `CORS_ORIGINS` env var; default to localhost
**Files Changed**: src/presentation/api.py

### ISS-010: Timing-unsafe API key comparison
**Category**: Security (A07 Broken Auth)
**Severity**: HIGH
**Symptoms**: `==` comparison vulnerable to timing attacks; inconsistent with middleware's `hmac.compare_digest`
**Solution**: Switched to `hmac.compare_digest` and aligned with middleware auth pattern
**Files Changed**: src/api/routes/system.py

### ISS-011: Silent NATS connection failure
**Category**: Runtime Logic
**Severity**: HIGH
**Symptoms**: NATS reconnection failures silently swallowed — no logging, no alerts
**Root Cause**: `except Exception: return False` with no logging
**Solution**: Added `logger.error("Failed to restore NATS connection: %s", exc)`
**Files Changed**: src/messaging.py

### ISS-012: Timezone-naive datetime.now() in strategy signals
**Category**: Data Integrity
**Severity**: HIGH
**Symptoms**: Inconsistent timestamps — strategy uses naive `datetime.now()` while services use `datetime.now(timezone.utc)`
**Solution**: Changed all 3 occurrences to `datetime.now(timezone.utc).isoformat()`
**Files Changed**: src/strategy.py

### ISS-013: Deprecated datetime.utcnow()
**Category**: Data Integrity
**Severity**: HIGH
**Symptoms**: Uses deprecated method that returns naive UTC datetime
**Solution**: Changed to `datetime.now(timezone.utc)`
**Files Changed**: src/presentation/api.py

### ISS-014: Unbounded query limit on API endpoints
**Category**: Availability
**Severity**: HIGH
**Symptoms**: `limit` parameter has no upper bound; `limit=999999999` could OOM
**Solution**: Added `Query(50, ge=1, le=1000)` and `Query(200, ge=1, le=1000)` bounds
**Files Changed**: src/api/routes/market.py

### ISS-015: Error messages leak internal details
**Category**: Security (A05 Info Disclosure)
**Severity**: HIGH
**Symptoms**: `detail=f"Failed to ...: {str(e)}"` exposes stack traces, library names to clients
**Solution**: Log full error server-side, return generic message to client
**Files Changed**: src/api/routes/market.py

### ISS-016: Test environment pollution
**Category**: Testing
**Severity**: HIGH
**Symptoms**: `test_credential_vault.py` tests fail when run after `test_api_security_mock.py`
**Root Cause**: `test_api_security_mock.py` sets `os.environ["API_KEY"]` at import time, polluting subsequent tests
**Solution**: Added `monkeypatch.delenv("API_KEY", raising=False)` in credential vault test fixture
**Files Changed**: tests/test_credential_vault.py

### ISS-017: Hardcoded PostgreSQL credentials
**Category**: Security (A05 Misconfiguration)
**Severity**: HIGH
**Symptoms**: `POSTGRES_PASSWORD: tradingbot` hardcoded in docker-compose.yml
**Solution**: Changed to `${POSTGRES_PASSWORD:?POSTGRES_PASSWORD must be set}`
**Files Changed**: docker-compose.yml

### ISS-018–027: Static Analysis Fixes (ruff)
**Category**: Code Quality (B904, F401, I001, F541, F811, F841, E741, B007)
**Severity**: MEDIUM–LOW
**Solution**: Fixed exception chaining, removed unused imports, sorted imports, fixed f-strings, renamed shadowed/ambiguous variables
**Files Changed**: src/api/routes/market.py, src/api/routes/signals.py, src/services/replay.py, src/database.py, src/indicators.py, src/signal_engine/plugins/structure_levels.py, src/signal_engine/plugins/trend_regime.py, src/signal_engine/market_data.py, src/signal_engine/alert_router.py, src/services/perps.py, and ~94 auto-fixed import issues

---

## Noted (Not Fixed — Require Design Decision)

### WebSocket endpoint has no authentication
`/ws` is in `EXEMPT_PATHS`. Streams live positions, fills, market data. Adding token validation on connect requires frontend changes.

### GET endpoints unauthenticated by default
`REQUIRE_AUTH_FOR_READS` defaults to `false`. Exposes account/position/trade data to unauthenticated callers. Changing default to `true` may break existing deployments.

### Docs endpoints exposed in production
`/docs`, `/openapi.json`, `/redoc` accessible without auth. Consider `FastAPI(docs_url=None)` for production builds.

---

## Statistics

- **Total bugs found**: 51
- **Fixed**: 46
- **Noted (design decisions)**: 5
- **By severity**: 13 CRITICAL, 13 HIGH, 17 MEDIUM, 4 LOW, 4 NOTED
- **By category**: 9 Security, 8 Error Detail Leakage, 5 Static Analysis, 5 Code Quality, 4 Type/Runtime, 3 Data Integrity, 3 Frontend/TypeScript, 2 Testing, 2 Concurrency

---

## Bug Hunt Session 2: 2026-03-05

### ISS-032: HMAC Signature Bypass in TradingView Webhook
**Category**: Security (A07 Broken Auth)
**Severity**: CRITICAL
**Symptoms**: `hmac.compare_digest(expected, x_tv_signature or "")` accepts unsigned webhooks when header is missing (None → "")
**Root Cause**: Missing null check on signature header before comparison
**Solution**: Added explicit check requiring non-empty signature header before HMAC comparison
**Files Changed**: src/api/routes/signals.py

### ISS-033: API Key Validation Falls Back to Vault Master Key
**Category**: Security (A07 Broken Auth)
**Severity**: HIGH
**Symptoms**: `os.getenv("API_KEY") or os.getenv("VAULT_MASTER_KEY")` uses vault decryption key as API auth fallback
**Root Cause**: Mixing authentication keys with encryption keys violates least privilege
**Solution**: Removed `VAULT_MASTER_KEY` fallback; only `API_KEY` is accepted for API authentication
**Files Changed**: src/api/routes/system.py

### ISS-034: Error Detail Leakage in Data Download Jobs
**Category**: Security (A05 Info Disclosure)
**Severity**: HIGH
**Symptoms**: `str(exc)` stored in job dict and returned to clients, exposing internal file paths and implementation details
**Solution**: Log full exception server-side, return generic message to client
**Files Changed**: src/api/routes/data.py

### ISS-035: Error Detail Leakage in Vault Credential Test
**Category**: Security (A05 Info Disclosure)
**Severity**: HIGH
**Symptoms**: `f"Connection test failed: {exc}"` exposes CCXT library errors and network details
**Solution**: Return generic "Check credentials and try again" message
**Files Changed**: src/api/routes/vault.py

### ISS-036: Error Detail Leakage in Backtest Results
**Category**: Security (A05 Info Disclosure)
**Severity**: HIGH
**Symptoms**: `str(e)` stored in walk-forward, Monte Carlo, and main backtest error fields, exposing Python stack traces
**Solution**: Log full exceptions server-side, store generic error messages in results
**Files Changed**: src/api/routes/backtest.py

### ISS-037: Silent Exception Swallowing in Intelligence API
**Category**: Error Handling
**Severity**: MEDIUM
**Symptoms**: Multiple `except Exception: pass` blocks for order book, position, and balance fetches — no logging at all
**Solution**: Added `logger.debug()` calls for all suppressed exceptions to aid production debugging
**Files Changed**: src/api/routes/intelligence.py

### ISS-038: WebSocket Double-Disconnect Race Condition
**Category**: Concurrency
**Severity**: MEDIUM
**Symptoms**: Multiple rapid send failures each create an `asyncio.create_task(self.disconnect(...))`, causing race on same connection
**Solution**: Added `_disconnecting` flag check to prevent re-entrant disconnect task creation
**Files Changed**: src/api/ws.py

### ISS-039: Undefined Name "OrchestratorService" (F821)
**Category**: Static Analysis
**Severity**: CRITICAL
**Symptoms**: Forward reference `"OrchestratorService"` in type hint — class doesn't exist; actual class is `AgentOrchestratorService`
**Solution**: Changed type hint to `"AgentOrchestratorService"`
**Files Changed**: src/services/agent_orchestrator.py

### ISS-040: Duplicate JSX Closing Tags in AIAssistant.tsx
**Category**: Frontend/TypeScript
**Severity**: CRITICAL
**Symptoms**: Lines 511-515 had duplicate `</div>);};` causing TS1128/TS1109 parse errors
**Solution**: Removed duplicate closing content
**Files Changed**: trading-bot-ai-studio/components/AIAssistant.tsx

### ISS-041: Undefined setOrderPrice Reference
**Category**: Frontend/TypeScript
**Severity**: CRITICAL
**Symptoms**: `setOrderPrice(lastClose.toFixed(2))` called but state setter never defined — TS2304 error
**Root Cause**: State variable was removed but call site was not cleaned up
**Solution**: Removed dead call
**Files Changed**: trading-bot-ai-studio/App.tsx

### ISS-042: Missing Zap Icon Import
**Category**: Frontend/TypeScript
**Severity**: CRITICAL
**Symptoms**: `<Zap size={10} />` used in live trading indicator but not imported from lucide-react — TS2304 error
**Solution**: Added `Zap` to lucide-react import destructuring
**Files Changed**: trading-bot-ai-studio/App.tsx

### ISS-043: Playwright slowMo Config Error
**Category**: Testing
**Severity**: MEDIUM
**Symptoms**: `slowMo: 350` placed in `use` block instead of `launchOptions` — TS2769 overload error
**Solution**: Moved to `launchOptions: { slowMo: 350 }`
**Files Changed**: trading-bot-ai-studio/tests/demo.config.ts

### ISS-044: Unused Imports (F401) — Batch
**Category**: Code Quality
**Severity**: MEDIUM
**Symptoms**: 17 unused imports across multiple files (Dict from typing, asyncio, TradeAttribution, SelfLearningConfig, etc.)
**Solution**: Auto-fixed with `ruff check --fix --select F401,I001`
**Files Changed**: src/api/main.py, src/api/routes/agents.py, src/api/routes/data.py, src/api/routes/notifications.py, src/api/routes/portfolio.py, src/api/routes/presets.py, src/backtest/mini_engine.py, src/services/agent_orchestrator.py, src/services/llm_proxy.py, src/strategies/registry.py

### ISS-045: Import Sorting (I001)
**Category**: Code Quality
**Severity**: MEDIUM
**Symptoms**: Un-sorted import blocks in main.py, agents.py, llm_proxy.py
**Solution**: Auto-fixed with `ruff check --fix --select I001`
**Files Changed**: src/api/main.py, src/services/llm_proxy.py

### ISS-046: Ambiguous Variable Name `l` (E741)
**Category**: Code Quality
**Severity**: MEDIUM
**Symptoms**: Variable `l` (lowercase L) easily confused with `1` (one) in ATR calculation
**Solution**: Renamed to `low` in all three preset strategy files
**Files Changed**: src/strategies/presets/adaptive_rsi.py, src/strategies/presets/momentum_mean_reversion.py, src/strategies/presets/mtf_trend_vwap.py

### ISS-047: Unused Variable agent_map (F841)
**Category**: Code Quality
**Severity**: MEDIUM
**Symptoms**: `agent_map = {a.id: a for a in agents}` computed but never read
**Solution**: Removed unused dict comprehension
**Files Changed**: src/api/routes/market.py

### ISS-048: Missing Exception Chaining (B904)
**Category**: Error Handling
**Severity**: MEDIUM
**Symptoms**: `raise HTTPException(...) ` without `from e` in strategy instantiation error
**Solution**: Added `from e` and stopped leaking `str(e)` to client
**Files Changed**: src/api/routes/presets.py

### ISS-049: zip() Without strict= Parameter (B905)
**Category**: Code Quality
**Severity**: LOW
**Symptoms**: `zip(x, y)` and `zip(plugins, weights)` could silently truncate mismatched iterables
**Solution**: Added `strict=True` to both zip calls
**Files Changed**: src/risk/portfolio_risk.py, src/signal_engine/plugins/base.py

### ISS-050: Error Detail Leakage in Presets Route
**Category**: Security (A05 Info Disclosure)
**Severity**: MEDIUM
**Symptoms**: `f"Failed to instantiate strategy: {e}"` exposed internal errors to client
**Solution**: Changed to generic message, added `from e` for proper chaining
**Files Changed**: src/api/routes/presets.py

### ISS-051: npm Dependency Vulnerabilities (2 high, 2 low)
**Category**: Security (Supply Chain)
**Severity**: HIGH
**Symptoms**: `npm audit` reports vulnerabilities in rollup (arbitrary file write), qs (DoS), minimatch (ReDoS)
**Solution**: Run `npm audit fix` to update affected packages
**Status**: NOTED — requires user action
**Files Changed**: None

### ISS-052: Undefined `logger` in backtest.py (F821)
**Category**: Static Analysis (F821)
**Severity**: CRITICAL
**Symptoms**: `NameError: name 'logger' is not defined` in `_run_backtest()` background task — 3 locations
**Root Cause**: Missing `import logging` and `logger = logging.getLogger(__name__)`
**Solution**: Added logger setup at module level
**Files Changed**: src/api/routes/backtest.py

### ISS-053: Undefined `logger` in data.py (F821)
**Category**: Static Analysis (F821)
**Severity**: CRITICAL
**Symptoms**: `NameError` in `_run_download()` background task
**Root Cause**: Missing logger import
**Solution**: Added logger setup at module level
**Files Changed**: src/api/routes/data.py

### ISS-054: Wrong attribute `sharpe_ratio` on AgentPerformance
**Category**: Type Error (attr-defined)
**Severity**: CRITICAL
**Symptoms**: `AttributeError` in agent briefing endpoint
**Root Cause**: Model defines `sharpe_rolling_30d`, not `sharpe_ratio`
**Solution**: Changed `perf[-1].sharpe_ratio` → `perf[-1].sharpe_rolling_30d`
**Files Changed**: src/api/routes/intelligence.py

### ISS-055: Missing `_disconnecting` in _Connection.__slots__
**Category**: Runtime (AttributeError)
**Severity**: CRITICAL
**Symptoms**: `AttributeError` on WebSocket double-disconnect
**Root Cause**: `_disconnecting` flag used but never declared in `__slots__` or `__init__`
**Solution**: Added to `__slots__` and initialized in `__init__`
**Files Changed**: src/api/ws.py

### ISS-056: StrategyService calls nonexistent DB methods
**Category**: Type Error (attr-defined, call-arg)
**Severity**: CRITICAL
**Symptoms**: `AttributeError` on any StrategyService operation
**Root Cause**: `list_strategies()`, `get_strategy(name: str)`, `delete_strategy()` don't exist on DatabaseManager
**Solution**: Fixed to `get_strategies()`, `get_strategy_by_name(name)`, `toggle_strategy_active(id, False)`
**Files Changed**: src/services/strategy_store.py

### ISS-057: Wrong DB model attributes in agents.py response mapping
**Category**: Type Error (attr-defined)
**Severity**: CRITICAL
**Symptoms**: `AttributeError` on attribution/scorecard/mutation endpoints
**Root Cause**: Response used `a.pnl`/`s.total_trades`/`s.avg_hold_time_minutes`/`m.strategy_name`/`m.source` which don't exist
**Solution**: Mapped to correct fields: `realized_pnl`, `sample_size`, `avg_hold_duration`, `mutation_reason`
**Files Changed**: src/api/routes/agents.py

### ISS-058: Missing `created_at` in PositionResponse construction
**Category**: Type Error (call-arg)
**Severity**: CRITICAL
**Symptoms**: Pydantic validation error on `GET /api/positions`
**Root Cause**: `created_at` required field not passed
**Solution**: Added `created_at=p.created_at.isoformat() if p.created_at else None`
**Files Changed**: src/api/routes/market.py

### ISS-059: TelegramNotifier assigned to DiscordNotifier variable
**Category**: Type Error (assignment)
**Severity**: HIGH
**Symptoms**: Wrong method signature if both channels active
**Root Cause**: Telegram block reused `notifier` variable from Discord block
**Solution**: Renamed to `tg_notifier`
**Files Changed**: src/api/routes/notifications.py

### ISS-060: Missing `get_strategy_by_name` in Postgres backend
**Category**: Type Error (attr-defined)
**Severity**: HIGH
**Symptoms**: `AttributeError` when using PostgreSQL backend
**Root Cause**: Method only existed on SQLiteBackend
**Solution**: Added to `DatabaseBackend` base class and `PostgresBackend`
**Files Changed**: src/database.py

### ISS-061: Silent crash in _finalise_fill background task
**Category**: Runtime (Error Propagation)
**Severity**: HIGH
**Symptoms**: Non-RuntimeError exceptions silently swallowed, position state corrupted
**Root Cause**: `except RuntimeError` only; other exceptions lost via `asyncio.create_task()`
**Solution**: Wrapped in outer try/except with CRITICAL-level logging
**Files Changed**: src/paper_trader.py

### ISS-062: Unused `hmac` import (F401)
**Category**: Code Quality
**Severity**: MEDIUM
**Solution**: Removed unused `import hmac`
**Files Changed**: src/api/middleware/auth.py

### ISS-063: Variable shadow `fills` in paper_trader.py
**Category**: Code Quality
**Severity**: MEDIUM
**Solution**: Renamed to `sim_fills`
**Files Changed**: src/paper_trader.py

### ISS-064: Unsorted imports in notifications/__init__.py
**Category**: Code Quality (I001)
**Severity**: MEDIUM
**Solution**: Fixed import order
**Files Changed**: src/notifications/__init__.py

### ISS-065: Unused exception variables (F841)
**Category**: Code Quality
**Severity**: LOW
**Solution**: Removed unused `as e`/`as exc` in exception handlers
**Files Changed**: src/api/routes/backtest.py, data.py, vault.py

### ISS-066: Missing `prev_open` None guard in VWAP scalping
**Category**: Code Quality
**Severity**: MEDIUM
**Solution**: Added `or self.prev_open is None` to guard condition
**Files Changed**: src/strategies/presets/vwap_scalping.py

### ISS-067: Race condition in agent_orchestrator _recent_fills
**Category**: Design (Concurrency)
**Severity**: HIGH
**Symptoms**: `_recent_fills` iterated then `.clear()`'d with `await` DB calls in between; fills arriving during those awaits are lost
**Root Cause**: `_update_daily_performance()` had `await` points between iterating `_recent_fills` and calling `.clear()`, allowing NATS callbacks to `.append()` fills that would be discarded
**Solution**: Snapshot-and-clear atomically at top of method (`fills_snapshot = list(self._recent_fills); self._recent_fills.clear()`) before any `await`. `_market_cache` confirmed safe (atomic dict replacement, reads get stable reference).
**Status**: FIXED
**Files Changed**: src/services/agent_orchestrator.py

### ISS-068: Race condition in alert_router WebSocket sets
**Category**: Design (Concurrency)
**Severity**: HIGH
**Symptoms**: Concurrent add/remove/broadcast on `_connections` without locks
**Root Cause**: `broadcast()` yields at each `await ws.send_text()`, allowing concurrent `add_connection`/`remove_connection` to mutate `_connections` dict and `_all_connections` set
**Solution**: Added `asyncio.Lock` to `WebSocketManager`. `add_connection`/`remove_connection` made async and wrapped with lock. `broadcast` snapshots targets under lock, sends outside lock, then removes failed connections under lock. Callers in `AlertRouter` and `signal_engine/main.py` updated to `await`.
**Status**: FIXED
**Files Changed**: src/signal_engine/alert_router.py, src/signal_engine/main.py
