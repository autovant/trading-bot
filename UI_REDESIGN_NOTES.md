# Frontend Refactoring Walkthrough

This document explains the key frontend changes made to improve **WebSocket safety**, **state performance**, and **UI/UX correctness** for the trading bot interface.

---

## 1. WebSocket & State Management

### 1.1 Shared WebSocket Hook (`hooks/useWebSocket.ts`)

**What changed**

- Introduced a shared `useWebSocket<T>` hook that centralizes:
  - Socket creation (`new WebSocket(url)`)
  - `onopen` / `onmessage` / `onclose` / `onerror` wiring
  - Reconnection with a single active timer
  - Cleanup on unmount

**Behavior**

- Accepts:
  - `url: string`
  - `onMessage: (msg: T) => void`
  - Optional `validator?: (raw: unknown) => raw is T` to type-check messages
- Guarantees:
  - At most one `WebSocket` instance per hook instance
  - Reconnection after disconnect, without stacking multiple timers
  - Automatic cleanup of sockets and timeouts in `useEffect` cleanup

**Caller responsibility**

- Supply a validator or ensure the backend message format is stable.
- Handle domain-specific state updates in the caller (e.g., contexts).

**Failure / validation behavior**

- If `validator` is provided and returns `false` for an incoming message:
  - The message is ignored.
  - A warning is logged to the console (no state updates are applied).
- On connection errors:
  - The hook logs the error.
  - The socket is closed and a reconnection is scheduled using a single active timer.
- There is currently no exponential backoff or max retry count; this can be added later if needed.

---

### 1.2 Market Data Context (`contexts/MarketDataContext.tsx`)

**What it provides**

- `marketData: OrderBookData | null`
- `lastPrice: number | null`
- `isConnected: boolean`

**Implementation details**

- Uses `useWebSocket<OrderBookData>` to subscribe to `ws://…/ws/market-data`.
- Uses a validator (where available) before updating state.
- Wraps the context `value` in `useMemo`:

  ```ts
  const value = useMemo(
    () => ({ marketData, lastPrice, isConnected }),
    [marketData, lastPrice, isConnected]
  );
  ```

**Why**

- Prevents unnecessary re-renders for components that don’t depend on market data.
- Ensures a single, well-managed WS connection for market data.

---

### 1.3 Account Context (`contexts/AccountContext.tsx`)

**What it provides**

- `positions: Position[]`
- `openOrders: Order[]`
- `summary: AccountSummary`
- `isConnected: boolean`
- `refreshPositions(): Promise<void>`
- `executeOrder(args: ExecuteOrderArgs): Promise<void>`

**Implementation details**

- Uses `useWebSocket<ExecutionReport>` to subscribe to `ws://…/ws/executions`.

- `refreshPositions` and `executeOrder` are wrapped in `useCallback` so they are stable across renders:

  ```ts
  const refreshPositions = useCallback(async () => { /* fetch /api/positions */ }, []);
  const executeOrder = useCallback(async (args: ExecuteOrderArgs) => { /* POST /api/orders */ }, []);
  ```

- Exposed via a memoized context `value`:

  ```ts
  const value = useMemo(
    () => ({
      positions,
      openOrders,
      summary,
      isConnected,
      refreshPositions,
      executeOrder,
    }),
    [positions, openOrders, summary, isConnected, refreshPositions, executeOrder]
  );
  ```

**Current limitations (intentional)**

- `AccountSummary` still derives some fields from positions (e.g., `unrealized_pnl`) and assumes backend provides a consistent `balance` / `margin_used`. Back-end driven summary should replace this in a later iteration.

**State source of truth**

- WebSocket `ExecutionReport` messages are treated as the primary driver for incremental updates.
- `refreshPositions()` is intended as a reconciliation mechanism (e.g., on reconnect or manual refresh), not something the UI calls on every tick.

---

### 1.4 Environment Configuration

**Endpoints**

- HTTP base: `NEXT_PUBLIC_API_BASE_URL`
- WebSocket base: `NEXT_PUBLIC_WS_BASE_URL`

All previous `http://localhost:8000` and `ws://localhost:8000` references are now built from these envs. For local dev:

```bash
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
NEXT_PUBLIC_WS_BASE_URL=ws://localhost:8000
```

---

### 1.5 System Status Context (`contexts/SystemStatusContext.tsx`)

**What it provides**

- `status: SystemStatus` with fields such as:
  - `status: 'ok' | 'error'` (Note: `warning` is planned but not currently used)
  - `message: string`
  - `latency_ms: number`
  - `last_updated: string`
  - `connected: boolean`

**Implementation details**

- Subscribes to connectivity from:
  - `MarketDataContext.isConnected`
  - `AccountContext.isConnected`
- Periodically polls the backend `/health` endpoint using `NEXT_PUBLIC_API_BASE_URL` to measure latency and basic availability.
- Updates `status` whenever:
  - Either WS connection drops (sets `status` to `'error'` and updates the message).
  - Health check responds successfully (updates `latency_ms` and `last_updated`).

**Usage**

- UI components such as `HealthMonitor` and the global header read from `useSystemStatus()` to display:
  - Overall system health
  - Connection status
  - Backend latency
- Bot control / trading components can also use this to disable critical actions when the system is in an error state.

---

## 2. Safety & UX Changes

### 2.1 Keyboard Shortcuts (`app/page.tsx`)

**Shortcuts**

- `Ctrl+Space`: Open **Bot Control** modal
- `Ctrl+Shift+O`: Open **Emergency “Cancel All Orders”** modal
- `Esc`: Close modals

**Safety guards**

- Shortcuts **do not fire** when the user is typing in:

  - `input`
  - `textarea`
  - `select`
  - `contentEditable` elements
- Shortcuts are ignored when `document.visibilityState !== 'visible'`.

This prevents accidental bot actions while editing fields.

---

### 2.2 Emergency Confirmation (`EmergencyConfirmModal`)

**What changed**

- Replaced `window.confirm("EMERGENCY: Cancel ALL Open Orders?")` with a Tailwind-styled React modal.
- The modal exposes:

  - `isOpen: boolean`
  - `onConfirm(): void`
  - `onCancel(): void`

**Behavior**

- `Ctrl+Shift+O` opens the `EmergencyConfirmModal`.
- Confirming triggers the “cancel all orders” handler (currently a stub or wired to the backend, depending on environment).

---

### 2.3 Bot Control (`BotControlModal.tsx`)

**Props**

- `isOpen: boolean`
- `status: 'running' | 'stopped' | 'paused'` (from context, planned)
- `onStart(): void`
- `onStop(): void`
- `onHalt(): void`
- `onClose(): void`

**Current implementation**

- Buttons call the corresponding callbacks.
- Callers are responsible for:

  - Hitting the appropriate backend endpoints.
  - Updating any local “bot state” context.

> **Note:** In the current iteration, these callbacks may log only (`console.log`) if backend endpoints are not yet implemented. This is intentional and should be replaced with real API calls.

---

### 2.4 Manual Trading (`ManualTradePanel.tsx`)

**Wiring**

- “Buy / Long” and “Sell / Short” buttons now call `executeOrder` from `AccountContext` with:

  - `symbol`
  - `side`
  - `size`
  - `type` (e.g., market or limit)
  - Optional price for limit orders

**Current behavior**

- For now, this may log actions and rely on the execution WebSocket to reconcile UI once the backend processes the order.
- Final behavior depends on backend endpoints being implemented.

---

## 3. Data Integrity

### 3.1 Order Book (`components/dashboard/OrderBook.tsx`)

**What changed**

- Removed all random depth generation (`Math.random()`-based fake depth).
- The order book now renders only depth levels provided by the backend `OrderBookData` structure.

**Why**

- Fake depth is misleading for trading decisions.
- The UI now accurately reflects the available data; no invented liquidity.

---

### 3.2 Positions Table (`components/dashboard/PositionsTable.tsx`)

**What changed**

- Removed hardcoded mock logs.
- Table now displays:

  - Real positions from `AccountContext`, or
  - A clear “No open positions” / “No data” empty state.

---

### 3.3 Trading Chart (`components/TradingChart.tsx`)

**What changed**

- Removed random/mock data generation on initial render to avoid SSR/client mismatch.
- Chart now relies on live or derived data from `MarketDataContext` only.

**Result**

- No hydration warnings due to `Math.random()`.
- Chart behavior is deterministic given the current market data.

---

## 4. API Contracts & Error Handling

> **Note:** The contracts below represent the intended API behavior. In the current implementation, some handlers may still be stubbed (logging only) until the backend endpoints are fully wired.

### 4.1 Execute Order

**Signature**
```ts
executeOrder(args: ExecuteOrderArgs): Promise<void>
```

**Arguments**
```ts
interface ExecuteOrderArgs {
  symbol: string;
  side: 'buy' | 'sell';
  type: 'market' | 'limit';
  quantity: number;
  price?: number; // Required if type is 'limit'
}
```

**Behavior**
- **Success**: Resolves when the HTTP POST to `/api/orders` returns 200 OK.
- **Failure**: Rejects with `Error('Order execution failed')` if non-200 or network error.
- **UI Update**: Optimistic updates are NOT implemented. The UI waits for the `ExecutionReport` via WebSocket to update `openOrders` and `positions`.

**Error surfacing (planned pattern)**

- Callers of `executeOrder` and bot control functions should:
  - Catch rejections.
  - Surface errors via a consistent UI mechanism (e.g., toast notifications or a centralized Logs/Alerts panel).
- A future iteration should introduce a shared `useNotifications` or `LogsContext` to standardize how user-facing errors are displayed.

Until a shared notification/alert mechanism is implemented, callers SHOULD:
- Catch errors from `executeOrder` and bot control functions.
- Show a non-blocking error indicator (e.g., inline message or temporary toast) and avoid infinite retries.

### 4.2 Bot Control

**Signatures**
```ts
startBot(): Promise<void>
stopBot(): Promise<void>
haltBot(): Promise<void>
```

**Endpoints**
- `POST /api/bot/start`
- `POST /api/bot/stop`
- `POST /api/bot/halt` (Cancel all + Stop)

**Behavior**
- **Success**: Resolves on 200 OK.
- **Failure**: Rejects on error.
- **State**: The `SystemStatusContext` should poll or receive WS updates to reflect the new state (`running` | `stopped` | `error`).

**Current implementation status**
- Frontend functions `startBot`, `stopBot`, and `haltBot` are defined and wired to `BotControlModal`.
- If the corresponding backend endpoints are not available, these functions currently log the action and reject with an error. The UI should surface this via a toast/log once a global error handling pattern is in place.

---

## 5. How to Verify

1. **Run frontend**

   ```bash
   npm run dev
   ```

2. **Check WebSocket behavior**

   - Open dev tools → Console.
   - Confirm single connections to:

     - `${NEXT_PUBLIC_WS_BASE_URL}/ws/market-data`
     - `${NEXT_PUBLIC_WS_BASE_URL}/ws/executions`
   - Verify reconnections on backend restart without multiple concurrent sockets.

3. **Test keyboard shortcuts**

   - `Ctrl+Space`: Bot Control modal opens.
   - `Ctrl+Shift+O`: Emergency modal opens.
   - Type in an input field and press these combos → **nothing should happen**.

4. **Test trading controls**

   - Use BotControl buttons; confirm `onStart` / `onStop` / `onHalt` handlers fire.
   - Use ManualTradePanel Buy/Sell → check console or network tab for executeOrder calls.

5. **Verify data display**

   - Order book shows real backend levels only.
   - Positions table shows real positions or a clear empty state.
   - Chart renders based on real market data (or a safe “no data yet” state on startup).

6. **Simulate backend restart / disconnect**

   - Stop and restart the backend while the UI is running.
   - Confirm:
     - WebSockets disconnect and reconnect cleanly (no multiple connections).
     - `SystemStatus` transitions to error and back to ok.
     - Positions / order book resync correctly after reconnect.

## 6. Known Limitations & Future Work

- `SystemStatus.status` only supports `'ok' | 'error'`; `'warning'` is not yet used.
- `AccountSummary` still derives key fields from positions instead of using a backend-provided summary.
- `useWebSocket` does not implement exponential backoff or a max retry count.
- Error surfacing (toasts / alerts) is not yet standardized; callers must handle rejections manually.
- Bot control (`startBot`/`stopBot`/`haltBot`) and `executeOrder` may be wired to stub endpoints in some environments; verify backend availability before relying on them in production.
