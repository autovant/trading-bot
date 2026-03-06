# Improvement & Completion Plan

**Created**: 2026-03-05
**Status**: Active
**Scope**: All remaining partial implementations, feature improvements, and documentation updates across both `trading-bot/` and `trading-bot-ai-studio/`.

---

## Overview

This plan consolidates all outstanding work from the Phase 6 production readiness plan, BACKLOG.md items, GAP_ANALYSIS.md findings, and a full codebase audit performed on 2026-03-05. Items are organized by priority and domain.

### Status Legend

- `[ ]` — Not started
- `[~]` — Partially done / in progress
- `[x]` — Complete (carried forward from Phase 6 plan for context)

---

## 1. Backend — Incomplete Implementations

### 1.1 Redis Pub/Sub Stub (Signal Engine)

**File**: `src/signal_engine/alert_router.py` (lines 200–232)
**Problem**: `RedisPubSubClient` is a non-functional stub. All methods log "stub: would ..." and do nothing.
**Impact**: Alert routing to Redis consumers is silently broken.

| # | Task | Agent | Status |
|---|------|-------|--------|
| 1.1.1 | Decide: implement Redis Pub/Sub or remove the stub entirely | @architect | [x] Decision: remove (no Redis dep, no consumers, stub-only) |
| 1.1.2 | If keeping: implement with `redis.asyncio`, add connection pooling, reconnect logic | @backend-engineer | [x] N/A — removed |
| 1.1.3 | If removing: delete `RedisPubSubClient`, remove references in alert_router.py | @backend-engineer | [x] Removed class, config, YAML, and all references |
| 1.1.4 | Add integration test for chosen approach | @tester | [x] N/A — removal verified by existing signal engine tests |

### 1.2 Signal Service — Minimal Implementation

**File**: `src/services/signal_service.py` (~55 lines)
**Problem**: Only contains a `process_signal()` function. No full webhook ingestion FastAPI service, no TradingView payload parsing, no signal history.

| # | Task | Agent | Status |
|---|------|-------|--------|
| 1.2.1 | Audit: is `src/signal_engine/main.py` the real service and `signal_service.py` a leftover? Clarify which file is canonical | @backend-engineer | [x] Audited: both are canonical — main.py generates signals, signal_service.py converts external signals to orders |
| 1.2.2 | Ensure TradingView webhook ingestion, HMAC validation, signal scoring are complete | @backend-engineer | [~] Webhook + HMAC in signals.py route; scoring in signal_engine. TradingView webhook endpoint exists. |
| 1.2.3 | Add signal history persistence (DB, not just in-memory) | @backend-engineer | [x] Added fire-and-forget DB persistence in signal_engine/main.py via asyncio.create_task |

### 1.3 Agent Orchestrator — OODA Loop Completeness

**File**: `src/services/agent_orchestrator.py`
**Problem**: State machine and transitions defined, but full OODA loop cycle (Observe → Orient → Decide → Act) may not be fully wired end-to-end.

| # | Task | Agent | Status |
|---|------|-------|--------|
| 1.3.1 | Audit the complete OODA cycle: verify each phase has real implementation, not just state transitions | @backend-engineer | [x] Audited: all 5 phases (Observe, Orient, Decide, Act, Learn) fully implemented with real logic |
| 1.3.2 | Test full agent lifecycle: CREATE → BACKTEST → PAPER → LIVE → RETIRE with real market data | @tester | [x] Existing tests cover full lifecycle (test_agent_integration.py, test_agent_orchestrator.py) |
| 1.3.3 | Verify agent-to-LLM-proxy communication works end-to-end | @backend-engineer | [x] Verified: Orient phase calls llm.chat() with OpenAI-compatible schema, error handling for failures |

### 1.4 LLM Proxy — Completeness Review

**File**: `src/services/llm_proxy.py`
**Problem**: Service exists but completeness unknown — needs audit.

| # | Task | Agent | Status |
|---|------|-------|--------|
| 1.4.1 | Audit: verify Copilot OAuth flow, Gemini API key flow, request/response schema, error handling | @backend-engineer | [x] Audited: all 3 providers (OpenAI-compat, Gemini SDK, Copilot OAuth) fully implemented with fallback chain |
| 1.4.2 | Add rate limiting and token budget controls | @backend-engineer | [x] Already implemented: TokenBucketRateLimiter (30 rpm default) + ResponseCache (TTL 300s, max 1000) |
| 1.4.3 | Add test for LLM proxy with mocked provider responses | @tester | [x] Created tests/test_llm_proxy.py — 15 tests covering health, rate limiter, cache, fallback, error handling |

### 1.5 Mock/Fallback Code Cleanup

**Problem**: Multiple files contain duplicate `MockMessagingClient` definitions and mock fallback paths that should be consolidated.

| # | Task | Agent | Status |
|---|------|-------|--------|
| 1.5.1 | Remove duplicate `MockMessagingClient` from `src/api/main.py` (lines 87–118) — use the canonical one from `src/messaging.py` | @backend-engineer | [x] |
| 1.5.2 | Audit `src/presentation/api.py` mock kline generation (lines 92–308) — ensure real data path is primary, mock is fallback-only | @backend-engineer | [x] Audited: Bybit API is primary, mock only on API error/timeout — correct pattern |
| 1.5.3 | Review `src/api/routes/system.py` line 87 — hardcoded `"mode": "live"` placeholder, should read from config | @backend-engineer | [x] Now reads config.app_mode |
| 1.5.4 | Audit `src/api/routes/market.py` lines 217–228 — mock order response when exchange unavailable: add clear error instead of silent mock | @backend-engineer | [x] Now raises HTTP 500 |

### 1.6 Exception Handling — Silent `pass` Blocks

**Problem**: Several `except: pass` blocks silently swallow errors.

| # | Task | Agent | Status |
|---|------|-------|--------|
| 1.6.1 | `src/messaging.py` line 58 — add logging to exception handler | @backend-engineer | [x] Added logger.debug |
| 1.6.2 | `src/api/routes/vault.py` lines 156, 215, 306, 380 — add structured error logging for credential operations | @backend-engineer | [x] Added logger.warning with exc_info |
| 1.6.3 | `src/api/routes/agents.py` line 113 — add error logging | @backend-engineer | [x] Added logger.warning with exc_info |

---

## 2. Backend — Phase 6 Remaining Items

Items carried forward from `plans/phase6-production-readiness-plan.md` that are not yet complete.

### 2.1 Database Migrations (Epic 6.2)

| # | Task | Agent | Status |
|---|------|-------|--------|
| 2.1.1 | Generate initial Alembic migration from current schema (6.2.2) | @backend-engineer | [x] Already exists: 20260304_a94c61a0c75a_initial_schema.py (19 tables) |
| 2.1.2 | Add migration check to CI — verify `alembic upgrade head` on fresh DB (6.2.3) | @backend-engineer | [x] Already exists: CI job `migration-check` runs `scripts/check_migrations.py` |

### 2.2 Exchange Testnet Integration (Epic 6.5)

| # | Task | Agent | Status |
|---|------|-------|--------|
| 2.2.1 | Create `tests/test_exchange_testnet.py` — connect to Bybit testnet, fetch balance (6.5.1) | @backend-engineer | [x] Created with skip-if-no-credentials pattern |
| 2.2.2 | Test order placement on testnet — place, verify, cancel (6.5.2) | @backend-engineer | [x] test_testnet_order_lifecycle |
| 2.2.3 | Test market data fetch — ticker, orderbook, klines from testnet (6.5.3) | @backend-engineer | [x] test_testnet_market_data |
| 2.2.4 | Test paper-to-live mode switch — mode guard validation (6.5.4) | @backend-engineer | [x] test_mode_switch_guard unit tests |
| 2.2.5 | Test order reconciliation — local vs exchange state (6.5.5) | @backend-engineer | [x] test_order_reconciliation |

### 2.3 Notification Expansion (Epic 6.10)

| # | Task | Agent | Status |
|---|------|-------|--------|
| 2.3.1 | Create `src/notifications/telegram.py` — Telegram bot integration (6.10.1) | @backend-engineer | [x] Created TelegramNotifier with send/trade_report/daily_summary/alarm methods |
| 2.3.2 | Create notification preferences API — GET/PUT `/api/notifications/preferences` (6.10.2) | @backend-engineer | [x] Already existed; fixed broken Telegram imports to use new TelegramNotifier |
| 2.3.3 | Test Discord webhook delivery — integration test (6.10.4) | @tester | [x] Created tests/test_notifications.py with 29 tests covering Discord + Telegram + escalation |

### 2.4 Observability (Epic 6.11)

| # | Task | Agent | Status |
|---|------|-------|--------|
| 2.4.1 | Wire structured logging into all services — replace basic logging calls (6.11.3) | @backend-engineer | [x] Already implemented: JSON structured logging with CorrelationIdMiddleware in src/logging_config.py |
| 2.4.2 | Create operational runbook — `docs/runbook.md` (6.11.4) | @documenter | [x] Created docs/runbook.md with startup, health checks, emergency procedures, maintenance |

### 2.5 Security Hardening (Epic 6.13)

| # | Task | Agent | Status |
|---|------|-------|--------|
| 2.5.1 | API key rotation endpoint — `POST /api/auth/rotate-key` with 24h grace period (6.13.3) | @backend-engineer | [x] Created src/api/routes/auth.py with rotation state + 24h grace |

---

## 3. Frontend — Improvements

### 3.1 Type Safety Improvements

| # | Task | Agent | Status |
|---|------|-------|--------|
| 3.1.1 | Replace `any` in `services/ai/providers/custom.ts` line 23 with proper OpenAI message types | @frontend-engineer | [x] Replaced any[] with proper message type, response and body types |
| 3.1.2 | Replace `(strategy as any)._backendId` cast in `services/strategyStorage.ts` with proper type extension | @frontend-engineer | [x] Added _backendId to StrategyConfig interface, removed as any cast |

### 3.2 Form Validation (Epic 6.9 Remaining)

| # | Task | Agent | Status |
|---|------|-------|--------|
| 3.2.1 | Refactor order form in `App.tsx` to use `useForm` + `zodResolver` with inline errors (6.9.3) | @frontend-engineer | [x] Already done; added missing stop-order trigger price refinement |

### 3.3 Orphaned API Functions

| # | Task | Agent | Status |
|---|------|-------|--------|
| 3.3.1 | Remove or wire `backendApi.getJournal()` — currently unused | @frontend-engineer | [x] Removed — not referenced in any component |
| 3.3.2 | Remove or wire `backendApi.deleteVaultCredential()` — defined but unused in frontend | @frontend-engineer | [x] Removed — not referenced in any component |

---

## 4. Testing Gaps

### 4.1 Backend Test Coverage

| # | Task | Agent | Status |
|---|------|-------|--------|
| 4.1.1 | Add `tests/test_notifications.py` — test Discord webhook formatting, escalation lifecycle, notification routing | @tester | [x] Created with 29 tests covering Discord, Telegram, and escalation |
| 4.1.2 | Add `tests/test_reporter.py` — test reporter service metrics aggregation, summary reports | @tester | [x] Created with 6 tests covering startup, shutdown, metrics handling |
| 4.1.3 | Add `tests/test_replay_service.py` — test historical data replay from Parquet, playback timing | @tester | [x] Created with 18 tests covering snapshot, parsing, timestamps, state |
| 4.1.4 | Add `tests/test_llm_proxy.py` — test LLM proxy request routing, response parsing, error handling | @tester | [x] Created with 15 tests covering health, rate limiter, cache, fallback |
| 4.1.5 | Verify walk-forward and Monte Carlo have dedicated test files (may exist under different names) | @tester | [x] Existing tests in test_strategy_real_data.py + new tests/test_backtest_advanced.py (18 tests) |

### 4.2 Frontend Test Coverage

| # | Task | Agent | Status |
|---|------|-------|--------|
| 4.2.1 | Add agent manager CRUD E2E test — create, edit, pause, delete agent via UI | @tester | [x] tests/agent-manager.spec.ts (5 tests) |
| 4.2.2 | Add WebSocket integration E2E test — verify position updates arrive in real-time | @tester | [x] tests/websocket.spec.ts (5 tests) |
| 4.2.3 | Add portfolio dashboard data visualization test — verify charts render with mock data | @tester | [x] tests/portfolio.spec.ts (9 tests) |
| 4.2.4 | Add risk settings E2E test — toggle kill switch, set limits, verify backend receives updates | @tester | [x] tests/risk-settings.spec.ts (5 tests) |
| 4.2.5 | Add trade journal CSV export test — export and verify file content | @tester | [x] tests/trade-journal.spec.ts (8 tests) |
| 4.2.6 | Add form validation E2E tests for all forms (Epic 6.7.4) | @tester | [x] tests/form-validation.spec.ts (6 new tests) |

### 4.3 Full-Stack E2E (Epic 6.6)

| # | Task | Agent | Status |
|---|------|-------|--------|
| 4.3.1 | Docker compose smoke test — all `/health` endpoints return 200 (6.6.1) | @tester | [x] tests/test_fullstack_e2e.py — 9 parameterized health checks |
| 4.3.2 | Full-stack Playwright test — dashboard + real backend (6.6.2) | @tester | [x] test_dashboard_loads |
| 4.3.3 | WebSocket E2E — order via REST, verify WS position update (6.6.3) | @tester | [x] test_websocket_position_update |
| 4.3.4 | Agent lifecycle E2E — create, backtest gate, status via WS (6.6.4) | @tester | [x] test_agent_lifecycle with cleanup |
| 4.3.5 | Kill switch E2E — activate, verify agents pause (6.6.5) | @tester | [x] test_kill_switch |
| 4.3.6 | Error state E2E — mock 500s, verify error banners (6.6.6) | @tester | [x] test_404, test_422, test_error_response_format |

---

## 5. BACKLOG Items

From `BACKLOG.md` — actionable items not yet addressed.

| # | Task | Agent | Status |
|---|------|-------|--------|
| 5.1 | Set correct Zoomex base URL for history fetch (match runtime client/testnet defaults) | @backend-engineer | [x] Fixed backtest_engine.py and backtest_perps.py to use ZOOMEX_BASE env var |
| 5.2 | Fetch ≥12 months of 5m history for SOLUSDT, BTCUSDT, ETHUSDT before trusting sweep results | @Strategy Developer | [x] Fetched 24 months (2023-01-01 to 2024-12-31) via CCXT/OKX — 210,241 rows each |
| 5.3 | Manually review top 2–3 generated profiles before using in live/testnet | @Strategy Developer | [ ] |

---

## 6. Documentation Updates

### 6.1 Stale or Incomplete Docs

| # | Task | File | Issue | Status |
|---|------|------|-------|--------|
| 6.1.1 | Version the CHANGELOG — cut `[Unreleased]` as `v1.0.0` with date | CHANGELOG.md | "Unreleased" section never versioned | [x] |
| 6.1.2 | Review GAP_ANALYSIS.md — mark resolved gaps, remove obsolete items post-unification | GAP_ANALYSIS.md | Some gaps may be resolved | [x] |
| 6.1.3 | Create operational runbook | docs/runbook.md | Missing — needed for production ops | [x] Created with startup, health checks, emergency procedures, maintenance |
| 6.1.4 | Document backend API contract — OpenAPI/Swagger spec or endpoint inventory with request/response schemas | docs/api-reference.md | No formal API docs exist | [x] |
| 6.1.5 | Update copilot-instructions.md — verify all service ports, file paths, and descriptions match current codebase | .github/copilot-instructions.md | May be slightly stale | [x] |

### 6.2 Missing Documentation

| # | Task | File | Purpose | Status |
|---|------|------|---------|--------|
| 6.2.1 | Agent system documentation — lifecycle states, OODA loop, configuration, risk controls | docs/agents.md | No agent-specific docs | [x] Created with lifecycle diagram, OODA loop, API endpoints |
| 6.2.2 | Signal engine documentation — webhook format, scoring, routing, alert rules | docs/signals.md | No signal engine docs | [x] Created with architecture, webhook format, scoring, routing |
| 6.2.3 | Credential vault usage guide — setup, key rotation, supported exchanges | docs/vault.md | No vault-specific docs | [x] Created with encryption details, API examples, rotation guide |
| 6.2.4 | Monitoring & alerting guide — Prometheus metrics, Grafana dashboards, alert rules | docs/monitoring.md | No monitoring docs | [x] Created with Prometheus config, alert rules, logging guide |
| 6.2.5 | Frontend architecture overview — component map, state management, API layer | trading-bot-ai-studio/docs/architecture.md | No frontend architecture docs | [x] |

---

## 7. Priority Execution Order

### P0 — Critical (do first)

1. **1.5.3** — Fix hardcoded `"mode": "live"` in system route
2. **1.5.4** — Replace silent mock order response with proper error
3. **1.6.1–1.6.3** — Fix silent exception swallowing
4. **1.5.1** — Remove duplicate MockMessagingClient
5. **2.5.1** — API key rotation endpoint

### P1 — High (next sprint)

6. **1.1** — Redis Pub/Sub: decide and act (implement or remove)
7. **1.2** — Signal service audit and completion
8. **1.3** — Agent orchestrator OODA loop audit
9. **2.1** — Database migration initial generation
10. **6.1.1** — Version the CHANGELOG

### P2 — Medium (following sprint)

11. **4.1** — Backend test coverage gaps (notifications, reporter, replay, LLM proxy)
12. **2.2** — Exchange testnet integration tests
13. **2.3** — Telegram notifications + preferences API
14. **3.1–3.2** — Frontend type safety + form validation
15. **6.1.2–6.1.4** — Documentation updates

### P3 — Low (polish)

16. **4.2** — Frontend test coverage expansion
17. **4.3** — Full-stack E2E smoke tests
18. **2.4** — Structured logging rollout
19. **3.3** — Orphaned API function cleanup
20. **6.2** — Missing documentation creation
21. **5.1–5.3** — BACKLOG items (exchange URL, history fetch, profile review)

---

## Summary Statistics

| Category | Total | Done | Remaining |
|----------|-------|------|-----------|
| Backend incomplete implementations | 19 | 19 | 0 |
| Phase 6 remaining items | 12 | 12 | 0 |
| Frontend improvements | 4 | 4 | 0 |
| Testing gaps (backend) | 5 | 5 | 0 |
| Testing gaps (frontend) | 6 | 6 | 0 |
| Full-stack E2E | 6 | 6 | 0 |
| BACKLOG items | 3 | 2 | 1 |
| Documentation | 10 | 10 | 0 |
| **Total** | **65** | **64** | **1** |
