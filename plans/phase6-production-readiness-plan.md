# Phase 6: Production Readiness & Validation

**Source**: Gap analysis of [unified-platform-plan.md](./unified-platform-plan.md)  
**Created**: 2026-03-04  
**Status**: Active  
**Goal**: Close the gap between "architecture complete" and "production-ready" — real-data testing, live exchange validation, cross-browser E2E, UI polish, operational readiness.

---

## Sprint 1: Critical Fixes & Testing Foundation

**Goal**: Fix broken/outdated code, establish testing infrastructure, add coverage reporting.

### Epic 6.1 — Critical Bug Fixes
**Agent**: @frontend-engineer, @backend-engineer  

| # | Subtask | Agent | Depends | Status |
|---|---------|-------|---------|--------|
| 6.1.1 | Fix `SignalsPanel.tsx` — replace hardcoded `http://localhost:3001` with `backendApi` calls to `/api/signals/*`, `/api/webhook/tradingview` | @frontend-engineer | — | [x] |
| 6.1.2 | Fix `ChartWidget.tsx` — complete candlestick wick drawing logic OR integrate TradingView Lightweight Charts for production-grade price chart | @frontend-engineer | — | [x] |
| 6.1.3 | Add `pytest-cov` to requirements.txt, configure in `pytest.ini` with 40% minimum threshold, add coverage report to CI | @backend-engineer | — | [x] |
| 6.1.4 | Fix `PositionRow.tsx` — audit and ensure it renders correctly with real position data shapes from backend | @frontend-engineer | — | [x] |

### Epic 6.2 — Database Migration System
**Files**: `alembic.ini` (new), `alembic/` (new), `src/database.py` (edit)  
**Agent**: @backend-engineer  

| # | Subtask | Agent | Depends | Status |
|---|---------|-------|---------|--------|
| 6.2.1 | Install Alembic, create `alembic.ini` + `alembic/env.py` wired to existing SQLAlchemy models in `src/database.py` | @backend-engineer | — | [x] |
| 6.2.2 | Generate initial migration from current schema (auto-generate from models) | @backend-engineer | 6.2.1 | [ ] |
| 6.2.3 | Add migration check to CI — verify `alembic upgrade head` applies cleanly on fresh DB | @backend-engineer | 6.2.2 | [ ] |

### Epic 6.3 — UI Component Library Foundation
**Files**: `trading-bot-ai-studio/components/ui/` (new files)  
**Agent**: @frontend-engineer  

| # | Subtask | Agent | Depends | Status |
|---|---------|-------|---------|--------|
| 6.3.1 | Create reusable `Button.tsx` — variants: primary, secondary, danger, ghost, icon; sizes: sm, md, lg; loading state with spinner | @frontend-engineer | — | [x] |
| 6.3.2 | Create reusable `Input.tsx` — text, number, password types; label, error message, helper text slots; disabled state | @frontend-engineer | — | [x] |
| 6.3.3 | Create reusable `Modal.tsx` — overlay, title, body, footer slots; close on Escape/backdrop click; focus trap | @frontend-engineer | — | [x] |
| 6.3.4 | Create reusable `Select.tsx` — single select, searchable, option groups; keyboard navigation | @frontend-engineer | — | [x] |
| 6.3.5 | Create reusable `Skeleton.tsx` — rectangle, circle, text-line variants; pulse animation; composable for card/list/table skeletons | @frontend-engineer | — | [x] |

---

## Sprint 2: Real-Data & Exchange Testing

**Goal**: Validate strategies against real market data, test live exchange connectivity.

### Epic 6.4 — Real-Data Strategy Validation
**Files**: `tests/test_strategy_real_data.py` (new), `tests/fixtures/` (new)  
**Agent**: @Strategy Developer  

| # | Subtask | Agent | Depends | Status |
|---|---------|-------|---------|--------|
| 6.4.1 | Download and store a golden dataset: BTCUSDT 1h candles 2024-01-01 to 2024-12-31 as Parquet in `tests/fixtures/btcusdt_1h_2024.parquet` | @Strategy Developer | — | [x] |
| 6.4.2 | Create `tests/test_strategy_real_data.py` — run `TradingStrategy` against golden dataset, assert: Sharpe > 0, MaxDD < 30%, > 50 trades generated | @Strategy Developer | 6.4.1 | [x] |
| 6.4.3 | Create golden backtest regression test — run backtest with fixed params, assert results match known-good output within 1% tolerance | @Strategy Developer | 6.4.1 | [x] |
| 6.4.4 | Test walk-forward optimizer with real data — verify it detects overfitting (in-sample vs out-of-sample degradation) | @Strategy Developer | 6.4.1 | [x] |
| 6.4.5 | Test Monte Carlo simulator with real backtest trades — verify confidence intervals are reasonable (p5 equity > 0) | @Strategy Developer | 6.4.2 | [x] |
| 6.4.6 | Multi-symbol strategy test — BTCUSDT + ETHUSDT simultaneously, verify portfolio risk manager enforces correlation limits | @Strategy Developer | 6.4.1 | [x] |

### Epic 6.5 — Exchange Testnet Integration
**Files**: `tests/test_exchange_testnet.py` (new)  
**Agent**: @backend-engineer  
**Prereq**: Bybit testnet API keys in `.env.test`

| # | Subtask | Agent | Depends | Status |
|---|---------|-------|---------|--------|
| 6.5.1 | Create `tests/test_exchange_testnet.py` — connect to Bybit testnet via ccxt, fetch balance, verify non-zero response | @backend-engineer | — | [ ] |
| 6.5.2 | Test order placement on testnet — place limit buy BTCUSDT, verify order appears in open orders, cancel it, verify canceled | @backend-engineer | 6.5.1 | [ ] |
| 6.5.3 | Test market data fetch — fetch BTCUSDT ticker, orderbook, 1h klines from testnet, verify data shapes match expected types | @backend-engineer | 6.5.1 | [ ] |
| 6.5.4 | Test paper-to-live mode switch — verify mode guard blocks live orders without explicit enable, verify credentials decrypt and exchange connects | @backend-engineer | 6.5.1 | [ ] |
| 6.5.5 | Test order reconciliation — place an order, fetch open orders, verify local state matches exchange state | @backend-engineer | 6.5.2 | [ ] |

---

## Sprint 3: Full-Stack & Browser Testing

**Goal**: E2E tests against real backend, cross-browser coverage, accessibility.

### Epic 6.6 — Full-Stack E2E Tests
**Files**: `tests/test_full_stack_smoke.py` (new), `trading-bot-ai-studio/tests/full-stack.spec.ts` (new)  
**Agent**: @tester  

| # | Subtask | Agent | Depends | Status |
|---|---------|-------|---------|--------|
| 6.6.1 | Create `tests/test_full_stack_smoke.py` — docker compose up, wait for all `/health` endpoints (API, execution, feed, risk, reporter, agent-orchestrator), verify all respond 200, tear down | @tester | — | [ ] |
| 6.6.2 | Create `tests/full-stack.spec.ts` — Playwright test that starts Vite dev server + real FastAPI backend, tests: dashboard loads, submit a paper order via UI, verify it appears in positions | @tester | 6.6.1 | [ ] |
| 6.6.3 | WebSocket E2E test — connect to `/ws`, subscribe to `positions` topic, place an order via REST, verify WS receives position update event | @tester | 6.6.2 | [ ] |
| 6.6.4 | Agent lifecycle E2E — create agent via UI, verify it appears in list, trigger backtest gate, verify status changes via WebSocket | @tester | 6.6.2 | [ ] |
| 6.6.5 | Kill switch E2E — activate kill switch via UI, verify all agents pause, verify WS broadcasts shutdown event | @tester | 6.6.2 | [ ] |
| 6.6.6 | Error state E2E — mock API 500 responses, verify error banners show, verify recovery on retry | @tester | 6.6.2 | [ ] |

### Epic 6.7 — Cross-Browser & Accessibility Testing
**Files**: `playwright.config.ts` (edit), `tests/accessibility.spec.ts` (new)  
**Agent**: @tester  

| # | Subtask | Agent | Depends | Status |
|---|---------|-------|---------|--------|
| 6.7.1 | Update `playwright.config.ts` — add Firefox and WebKit projects, add mobile viewport (iPhone 14, Pixel 7) | @tester | — | [x] |
| 6.7.2 | Create `tests/accessibility.spec.ts` — integrate `@axe-core/playwright`, run axe scan on every tab, assert zero critical/serious violations | @tester | 6.7.1 | [x] |
| 6.7.3 | Add keyboard navigation tests — Tab through order form, verify focus order, verify Enter submits, verify Escape closes modals | @tester | 6.7.1 | [x] |
| 6.7.4 | Add form validation tests — submit empty order form, verify inline error messages, submit invalid values, verify rejection | @tester | 6.3.2 | [ ] |
| 6.7.5 | Add ARIA roles to all major components — `role="list"` for agent list, `role="dialog"` for modals, `aria-live="polite"` for real-time updates | @frontend-engineer | — | [x] |

---

## Sprint 4: State Management & UX Polish

**Goal**: Global state management, better loading UX, form validation, preferences.

### Epic 6.8 — State Management & Data Caching
**Files**: `trading-bot-ai-studio/hooks/` (new files), `trading-bot-ai-studio/package.json` (edit)  
**Agent**: @frontend-engineer  

| # | Subtask | Agent | Depends | Status |
|---|---------|-------|---------|--------|
| 6.8.1 | Install TanStack Query (`@tanstack/react-query`), create `QueryClientProvider` wrapper in `App.tsx` | @frontend-engineer | — | [x] |
| 6.8.2 | Create `hooks/useAgents.ts` — `useQuery` for agent list, `useMutation` for create/update/delete with optimistic updates | @frontend-engineer | 6.8.1 | [x] |
| 6.8.3 | Create `hooks/usePositions.ts` — `useQuery` for positions, integrate WebSocket updates via `queryClient.setQueryData` | @frontend-engineer | 6.8.1 | [x] |
| 6.8.4 | Create `hooks/useStrategies.ts` — `useQuery` for strategies, `useMutation` for CRUD | @frontend-engineer | 6.8.1 | [x] |
| 6.8.5 | Refactor `AgentManager.tsx`, `PortfolioDashboard.tsx`, `TradeJournal.tsx` to use TanStack Query hooks instead of raw `useEffect` + `useState` | @frontend-engineer | 6.8.2, 6.8.3, 6.8.4 | [x] |

### Epic 6.9 — Form Validation & UX
**Files**: `trading-bot-ai-studio/package.json` (edit), various components  
**Agent**: @frontend-engineer  

| # | Subtask | Agent | Depends | Status |
|---|---------|-------|---------|--------|
| 6.9.1 | Install `react-hook-form` + `zod` + `@hookform/resolvers` | @frontend-engineer | — | [x] |
| 6.9.2 | Create Zod schemas for: `OrderFormSchema`, `AgentCreateSchema`, `CredentialSchema`, `StrategySchema` | @frontend-engineer | 6.9.1 | [x] |
| 6.9.3 | Refactor order form in `App.tsx` to use `useForm` + `zodResolver`, show inline errors next to fields | @frontend-engineer | 6.9.2, 6.3.2 | [ ] |
| 6.9.4 | Refactor agent creation form in `AgentManager.tsx` to use `useForm` + `zodResolver` | @frontend-engineer | 6.9.2, 6.3.2 | [x] |
| 6.9.5 | Refactor credential form in `SettingsView.tsx` to use `useForm` + `zodResolver` | @frontend-engineer | 6.9.2, 6.3.2 | [x] |

---

## Sprint 5: Notifications, Observability & Ops

**Goal**: Expand notification channels, add Grafana dashboards, structured logging, operational runbooks.

### Epic 6.10 — Notification Expansion
**Files**: `src/notifications/` (new files), `src/api/routes/` (edit)  
**Agent**: @backend-engineer  

| # | Subtask | Agent | Depends | Status |
|---|---------|-------|---------|--------|
| 6.10.1 | Create `src/notifications/telegram.py` — Telegram bot integration via `python-telegram-bot` or raw HTTP API. Env: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | @backend-engineer | — | [ ] |
| 6.10.2 | Create notification preferences API — `GET /api/notifications/preferences`, `PUT /api/notifications/preferences`. Stored per-user in DB. Fields: channels (discord/telegram), event types (trade_fill, alarm, daily_summary, agent_status) | @backend-engineer | — | [ ] |
| 6.10.3 | Create in-app notification component — bell icon in Navbar with unread badge, dropdown with notification history, mark-as-read | @frontend-engineer | — | [x] |
| 6.10.4 | Test Discord webhook delivery — integration test that sends a test webhook and verifies 204 response | @tester | — | [ ] |

### Epic 6.11 — Observability & Operational Readiness
**Files**: `grafana/dashboards/` (new), `src/logging_config.py` (new)  
**Agent**: @backend-engineer  

| # | Subtask | Agent | Depends | Status |
|---|---------|-------|---------|--------|
| 6.11.1 | Create Grafana dashboard JSON — `grafana/dashboards/trading-overview.json`: panels for active agents, open positions, P&L, order rate, error rate, circuit breaker status | @backend-engineer | — | [x] |
| 6.11.2 | Create `src/logging_config.py` — structured JSON logging via `python-json-logger`, correlation IDs via middleware, log level from env | @backend-engineer | — | [x] |
| 6.11.3 | Wire structured logging into all services — replace `logging.getLogger()` calls with structured logger, add request_id to all API logs | @backend-engineer | 6.11.2 | [ ] |
| 6.11.4 | Create operational runbook — `docs/runbook.md`: common failure scenarios, recovery procedures, escalation contacts, monitoring alerts | @documenter | — | [ ] |

---

## Sprint 6: Agent Quality & Security Hardening

**Goal**: Validate agent decision quality, add audit logging, input sanitization.

### Epic 6.12 — Agent Decision Quality
**Files**: `tests/test_agent_decision_quality.py` (new)  
**Agent**: @tester  

| # | Subtask | Agent | Depends | Status |
|---|---------|-------|---------|--------|
| 6.12.1 | Create LLM response validation tests — send known market scenarios to LLM proxy, verify JSON schema of response, verify no hallucinated fields | @tester | — | [x] |
| 6.12.2 | Create agent decision bounds test — simulate 100 OODA cycles with mocked market data, verify: no position exceeds risk limits, no leverage exceeds config, all decisions have confidence scores | @tester | — | [x] |
| 6.12.3 | Multi-agent stress test — run 5 agents simultaneously against synthetic market data, verify portfolio risk manager correctly blocks correlated positions | @tester | — | [x] |

### Epic 6.13 — Security Hardening
**Files**: `tests/test_security.py` (new), `src/api/middleware/` (edit)  
**Agent**: @security-auditor, @backend-engineer  

| # | Subtask | Agent | Depends | Status |
|---|---------|-------|---------|--------|
| 6.13.1 | Create input sanitization tests — SQL injection attempts via webhook body, XSS via agent names, path traversal via symbol params | @security-auditor | — | [x] |
| 6.13.2 | Add audit log table — `audit_log` with action, actor, resource, old_value, new_value, ip, timestamp. Log: kill switch, credential CRUD, agent lifecycle, mode changes | @backend-engineer | — | [x] |
| 6.13.3 | Add API key rotation endpoint — `POST /api/auth/rotate-key`, generates new key, invalidates old after grace period (24h) | @backend-engineer | — | [ ] |

---

## Dependency Graph

```
Sprint 1 (Foundation) ──────────────────────────────────────────────
  6.1 Critical Fixes ──┐
  6.2 DB Migrations ───┤  (all independent, parallel)
  6.3 UI Components ───┘

Sprint 2 (Real Data) ───────────────────────────────────────────────
  6.4 Real-Data Strategy ──┐  (independent of Sprint 1)
  6.5 Exchange Testnet ────┘  (independent of Sprint 1)

Sprint 3 (E2E Testing) ─────────────────────────────────────────────
  6.6 Full-Stack E2E ──────┐  (needs working backend + frontend)
  6.7 Cross-Browser/A11y ──┘  (6.7.4 needs 6.3.2 Input component)

Sprint 4 (UX Polish) ───────────────────────────────────────────────
  6.8 State Management ──┐  (needs 6.3.* UI components)
  6.9 Form Validation ───┘  (needs 6.3.2 Input, 6.9.1 libs)

Sprint 5 (Ops) ─────────────────────────────────────────────────────
  6.10 Notifications ──┐  (independent)
  6.11 Observability ──┘  (independent)

Sprint 6 (Hardening) ───────────────────────────────────────────────
  6.12 Agent Quality ──┐  (needs agent system working)
  6.13 Security ───────┘  (independent)
```

## Execution Order

**Sprint 1** (immediate): Epics 6.1, 6.2, 6.3 in parallel  
**Sprint 2** (after Sprint 1): Epics 6.4, 6.5 in parallel  
**Sprint 3** (after Sprint 1): Epics 6.6, 6.7 in parallel  
**Sprint 4** (after Sprint 1+3): Epics 6.8, 6.9 in parallel  
**Sprint 5** (after Sprint 2): Epics 6.10, 6.11 in parallel  
**Sprint 6** (after Sprint 4): Epics 6.12, 6.13 in parallel  

## Files Created/Modified Summary

### New Files (25+)
| File | Sprint | Purpose |
|------|--------|---------|
| `alembic.ini` | 1 | Alembic config |
| `alembic/env.py` | 1 | Migration environment |
| `alembic/versions/*.py` | 1 | Initial migration |
| `components/ui/Button.tsx` | 1 | Reusable button |
| `components/ui/Input.tsx` | 1 | Reusable input |
| `components/ui/Modal.tsx` | 1 | Reusable modal |
| `components/ui/Select.tsx` | 1 | Reusable select |
| `components/ui/Skeleton.tsx` | 1 | Loading skeleton |
| `tests/fixtures/btcusdt_1h_2024.parquet` | 2 | Golden test dataset |
| `tests/test_strategy_real_data.py` | 2 | Real-data strategy tests |
| `tests/test_exchange_testnet.py` | 2 | Exchange integration tests |
| `tests/test_full_stack_smoke.py` | 3 | Docker smoke test |
| `tests/full-stack.spec.ts` | 3 | Full-stack Playwright |
| `tests/accessibility.spec.ts` | 3 | Axe-core a11y tests |
| `hooks/useAgents.ts` | 4 | TanStack Query agents |
| `hooks/usePositions.ts` | 4 | TanStack Query positions |
| `hooks/useStrategies.ts` | 4 | TanStack Query strategies |
| `src/notifications/telegram.py` | 5 | Telegram integration |
| `grafana/dashboards/trading-overview.json` | 5 | Grafana dashboard |
| `src/logging_config.py` | 5 | Structured logging |
| `docs/runbook.md` | 5 | Operational runbook |
| `tests/test_agent_decision_quality.py` | 6 | Agent quality tests |
| `tests/test_security.py` | 6 | Security tests |

### Modified Files (10+)
| File | Sprint | Changes |
|------|--------|---------|
| `components/SignalsPanel.tsx` | 1 | Replace localhost:3001 with backendApi |
| `components/ChartWidget.tsx` | 1 | Fix candlestick rendering |
| `requirements.txt` | 1 | Add pytest-cov, alembic |
| `pytest.ini` | 1 | Add coverage config |
| `src/database.py` | 1 | Wire Alembic metadata |
| `playwright.config.ts` | 3 | Add Firefox, WebKit, mobile |
| `App.tsx` | 4 | Add QueryClientProvider |
| `package.json` | 4 | Add TanStack Query, RHF, Zod |
| `AgentManager.tsx` | 4 | Use TanStack Query + RHF |
| `SettingsView.tsx` | 4 | Use RHF for credential form |
