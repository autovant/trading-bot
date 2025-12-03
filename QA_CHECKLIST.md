# QA Checklist: End-to-End Verification

## Test Set 1 – Mode & Safety
- [ ] **Start backend in paper mode (default)**
    - [ ] Verify `/api/mode` returns `"mode": "paper"`.
    - [ ] Verify UI header indicates **PAPER**.
- [ ] **Attempt to switch to live mode without keys**
    - [ ] Call `/api/mode` to set `live`.
    - [ ] Call `/api/bot/start`.
    - [ ] Expect: Rejection (400/500) or clear error. No live calls.

## Test Set 2 – Simple “Always Long” Strategy E2E
- [x] **Create trivial strategy**
    - [x] Define "QA_AlwaysLong" strategy (Enter Long if Close > 0) via API.
    - [x] Save and Activate.
- [x] **Verify DB + backend**
    - [x] Confirm row in DB with `active = true`.
    - [x] Restart/Reload backend.
    - [x] Confirm logs show strategy loaded from DB.
- [x] **Run controlled backtest**
    - [x] Generate synthetic OHLCV data (1m, 5m, 1h) for "QA".
    - [x] Run `tools/backtest.py --symbol QA`.
    - [x] **Verify:**
        - [x] Backtest runs without error.
        - [x] Trades are generated (should be immediately upon start).
        - [x] Results JSON is produced.

## Test Set 3 – Strategy Builder → Paper Trading
- [ ] **Start backend in paper mode**
- [ ] **Confirm active strategy**
    - [ ] UI/API shows correct strategy name.
- [ ] **Run bot in paper mode**
    - [ ] Start via `/api/bot/start`.
    - [ ] Verify logic fires on live feed.
    - [ ] Verify positions in PositionsTable.
    - [ ] Verify PnL updates.
- [ ] **Stop bot**
    - [ ] `/api/bot/stop` works cleanly.

## Test Set 4 – Stop Loss / Take Profit Behavior
- [ ] **Create SL/TP strategy**
- [ ] **Run backtests**
    - [ ] Scenario A: Price hits SL first.
    - [ ] Scenario B: Price hits TP first.
    - [ ] Scenario C: Both hit in bar, verify H/L sequencing logic.

## Test Set 5 – ManualTradePanel & Contexts Wiring
- [ ] **Manual orders**
    - [ ] Place Long -> Close.
    - [ ] Place Short -> Close.
    - [ ] Verify `executeOrder` payload and backend logs.
    - [ ] Verify PositionsTable updates.
- [ ] **OrderBook / Chart consistency**
    - [ ] Verify prices match across components.
- [ ] **Keyboard safety**
    - [ ] Typing in inputs does NOT trigger shortcuts.

## Test Set 6 – Resilience & Reloads
- [ ] **Backend restart while UI running**
    - [ ] Kill backend -> UI shows disconnected.
    - [ ] Restart backend -> UI reconnects, state restores.
- [ ] **Config reload with active bot**
    - [ ] Trigger reload.
    - [ ] Verify seamless transition or clean restart.
