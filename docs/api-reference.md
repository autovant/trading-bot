# API Reference

**Base URL**: `http://localhost:8000/api`
**Authentication**: API key via `X-API-Key` header (required for write operations)
**Content-Type**: `application/json`

---

## Table of Contents

- [System](#system)
- [Auth](#auth)
- [Market](#market)
- [Strategy](#strategy)
- [Backtest](#backtest)
- [Agents](#agents)
- [Signals](#signals)
- [Risk](#risk)
- [Data](#data)
- [Presets](#presets)
- [Notifications](#notifications)
- [Portfolio](#portfolio)
- [Intelligence](#intelligence)
- [Vault](#vault)
- [WebSocket](#websocket)

---

## System

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` or `/api/health` | Health check |
| GET | `/metrics` | Prometheus metrics |
| GET | `/api/mode` | Get current trading mode |
| POST | `/api/mode` | Set trading mode (requires API key) |
| GET | `/api/bot/status` | Get bot status (enabled, symbol, mode) |
| POST | `/api/bot/start` | Start the bot (requires API key) |
| POST | `/api/bot/stop` | Stop the bot (requires API key) |
| GET | `/api/presets` | List preset strategy configurations |

### Key Details

**GET /api/mode**
Returns: `{ "mode": "paper|live|replay", "shadow": bool }`

**POST /api/mode** (requires `X-API-Key`)
Body: `{ "mode": "paper|live|replay", "shadow": bool }`

**GET /api/bot/status**
Returns: `{ "enabled": bool, "status": "running|stopped", "symbol": "BTC-PERP", "mode": "paper" }`

```bash
curl http://localhost:8000/api/health
curl http://localhost:8000/api/bot/status
curl -X POST http://localhost:8000/api/bot/start -H "X-API-Key: $API_KEY"
```

---

## Auth

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/auth/rotate-key` | Rotate API key with 24h grace period |

**POST /api/auth/rotate-key** (requires current `X-API-Key`)
Body: `{ "new_key": "string" }`
Returns: `{ "status": "rotated", "grace_expires": "ISO-8601" }`

Old key remains valid for 24 hours after rotation.

---

## Market

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/account` | Account summary (equity, balance, margin) |
| GET | `/api/positions` | List open positions |
| GET | `/api/trades` | List recent trades |
| GET | `/api/orders` | List orders (optional `?status_filter=`) |
| POST | `/api/orders` | Place an order |
| GET | `/api/klines` | Get candlestick data |

### Key Details

**GET /api/account**
Returns: `{ "equity": float, "balance": float, "used_margin": float, "free_margin": float, "unrealized_pnl": float, "leverage": float, "currency": "USDT" }`

**GET /api/trades**
Query: `?limit=50` (1–1000)

**POST /api/orders**
Body: `{ "symbol": "BTCUSDT", "side": "buy|sell", "quantity": 0.01, "price": 50000.0, "type": "limit|market" }`

**GET /api/klines**
Query: `?symbol=BTCUSDT&interval=15&limit=200`
Returns: Array of `{ "time": int, "open": float, "high": float, "low": float, "close": float, "volume": float }`

```bash
curl http://localhost:8000/api/account
curl "http://localhost:8000/api/klines?symbol=BTCUSDT&interval=60&limit=100"
curl -X POST http://localhost:8000/api/orders \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTCUSDT","side":"buy","quantity":0.01,"type":"market"}'
```

---

## Strategy

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/strategies` | List all strategies |
| POST | `/api/strategies` | Create a strategy |
| GET | `/api/strategies/{name_or_id}` | Get strategy by name or ID |
| PUT | `/api/strategies/{id}` | Update a strategy |
| POST | `/api/strategies/{id}/activate` | Activate a strategy |
| POST | `/api/strategies/{id}/deactivate` | Deactivate a strategy |

### Key Details

**POST /api/strategies**
Body: `{ "name": "my_strategy", "config": { ... } }`
Returns: `{ "id": int, "name": str, "config": {}, "is_active": bool, "created_at": str, "updated_at": str }`

```bash
curl http://localhost:8000/api/strategies
curl -X POST http://localhost:8000/api/strategies \
  -H "Content-Type: application/json" \
  -d '{"name":"ema_cross","config":{"fast_ema":9,"slow_ema":21}}'
```

---

## Backtest

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/backtests` | Submit a backtest job (202 Accepted) |
| GET | `/api/backtests/history` | List past backtest runs |
| GET | `/api/backtests/{job_id}` | Get backtest job status |
| GET | `/api/backtests/{job_id}/results` | Get full results (completed only) |
| POST | `/api/backtests/compare` | Compare multiple backtest runs |

### Key Details

**POST /api/backtests**
Body:
```json
{
  "symbol": "BTCUSDT",
  "start": "2024-01-01",
  "end": "2024-06-01",
  "strategy_name": "ema_cross",
  "strategy_params": { "fast_ema": 9 },
  "walk_forward_windows": 5,
  "monte_carlo_runs": 1000
}
```
Returns: `{ "job_id": "uuid", "status": "queued" }`

**POST /api/backtests/compare**
Body: `{ "job_ids": ["uuid1", "uuid2"] }` (2–10 job IDs)

```bash
curl -X POST http://localhost:8000/api/backtests \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTCUSDT","start":"2024-01-01","end":"2024-06-01"}'
curl http://localhost:8000/api/backtests/history?limit=10
```

---

## Agents

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/agents` | List agents (optional `?status_filter=`) |
| POST | `/api/agents` | Create an agent |
| GET | `/api/agents/{id}` | Get agent details |
| PUT | `/api/agents/{id}` | Update agent config |
| POST | `/api/agents/{id}/start` | Start agent (→ backtesting) |
| POST | `/api/agents/{id}/pause` | Pause agent |
| POST | `/api/agents/{id}/resume` | Resume agent (→ backtesting) |
| POST | `/api/agents/{id}/retire` | Retire agent permanently |
| POST | `/api/agents/{id}/promote` | Promote agent paper → live |
| DELETE | `/api/agents/{id}` | Delete agent |
| GET | `/api/agents/{id}/journal` | Agent OODA decision journal |
| GET | `/api/agents/{id}/performance` | Agent performance metrics |

### Key Details

**POST /api/agents**
Body:
```json
{
  "name": "btc_trend_agent",
  "config": {},
  "allocation_usd": 5000,
  "strategy_name": "ema_cross",
  "strategy_params": { "fast_ema": 9, "slow_ema": 21 }
}
```

**Agent Lifecycle**: `created → backtesting → paper → live → retired` (with `paused` available from most states)

**POST /api/agents/{id}/promote**
Query: `?force=false` — evaluates PaperGate criteria (14 days paper data, Sharpe ≥ 0.5, win rate ≥ 40%, max drawdown ≤ 15%)

```bash
curl http://localhost:8000/api/agents
curl -X POST http://localhost:8000/api/agents \
  -H "Content-Type: application/json" \
  -d '{"name":"my_agent","allocation_usd":1000}'
curl -X POST http://localhost:8000/api/agents/1/start
```

---

## Signals

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/webhook/tradingview` | TradingView webhook (HMAC-validated) |
| GET | `/api/signals/history` | Paginated signal history |
| GET | `/api/signals/config` | Get signal config |
| PUT | `/api/signals/config` | Toggle auto-execution, set allowed symbols |

### Key Details

**POST /api/webhook/tradingview**
Header: `X-TV-Signature: <HMAC-SHA256>` (if `TRADINGVIEW_WEBHOOK_SECRET` is set)
Body:
```json
{
  "symbol": "BTCUSDT",
  "side": "buy",
  "price": 50000,
  "stop_loss": 49000,
  "take_profit": 52000,
  "confidence": 0.85,
  "message": "EMA crossover detected"
}
```

**PUT /api/signals/config**
Body: `{ "auto_execute": true, "allowed_symbols": ["BTCUSDT", "ETHUSDT"] }`

```bash
curl http://localhost:8000/api/signals/history?limit=20
curl -X PUT http://localhost:8000/api/signals/config \
  -H "Content-Type: application/json" \
  -d '{"auto_execute":true}'
```

---

## Risk

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/risk/status` | Risk status, kill switch state, limits |
| PUT | `/api/risk/limits` | Update risk limits |
| POST | `/api/risk/kill-switch` | Emergency kill switch |
| GET | `/api/risk/alarms` | List alarms (optional `?include_acknowledged=true`) |
| POST | `/api/risk/alarms/{id}/ack` | Acknowledge an alarm |

### Key Details

**PUT /api/risk/limits**
Body (all fields optional):
```json
{
  "max_total_exposure_usd": 100000,
  "max_per_agent_exposure_usd": 20000,
  "max_symbol_concentration": 0.30,
  "max_daily_loss_usd": 5000,
  "max_correlation": 0.70
}
```

**POST /api/risk/kill-switch**
Actions: publishes kill command to NATS, pauses all active agents, activates kill switch.
Returns: `{ "status": "activated", "activated_at": "ISO-8601", "actions": ["..."] }`

```bash
curl http://localhost:8000/api/risk/status
curl -X POST http://localhost:8000/api/risk/kill-switch
```

---

## Data

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/data/download` | Trigger historical data download (202) |
| GET | `/api/data/download/{job_id}` | Check download job status |
| GET | `/api/data/datasets` | List available Parquet datasets |
| GET | `/api/data/datasets/{filename}` | Get dataset metadata |
| DELETE | `/api/data/datasets/{filename}` | Delete a dataset |

### Key Details

**POST /api/data/download**
Body:
```json
{
  "symbol": "BTCUSDT",
  "timeframe": "5m",
  "start_date": "2024-01-01",
  "end_date": "2024-06-01",
  "source": "binance"
}
```
Allowed timeframes: `1m`, `5m`, `15m`, `1h`, `4h`, `1d`

```bash
curl -X POST http://localhost:8000/api/data/download \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTCUSDT","timeframe":"1h","start_date":"2024-01-01","end_date":"2024-06-01"}'
curl http://localhost:8000/api/data/datasets
```

---

## Presets

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/strategies/presets` | List strategy presets |
| GET | `/api/strategies/presets/{key}` | Get preset details + default params |
| POST | `/api/strategies/presets/{key}/backtest` | Validate and prepare a preset for backtest |

### Key Details

**POST /api/strategies/presets/{key}/backtest**
Body: `{ "symbol": "BTCUSDT", "timeframe": "1h", "start_date": "2024-01-01", "end_date": "2024-06-01", "params": {} }`

```bash
curl http://localhost:8000/api/strategies/presets
```

---

## Notifications

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/notifications/preferences` | Get notification preferences |
| PUT | `/api/notifications/preferences` | Update preferences (channels, events) |
| POST | `/api/notifications/telegram/test` | Send test Telegram message |
| POST | `/api/notifications/send` | Manually send a notification (202) |

### Key Details

**PUT /api/notifications/preferences**
Body:
```json
{
  "trade_executed": true,
  "risk_alert": true,
  "circuit_breaker": true,
  "channels": ["discord", "telegram"],
  "discord_webhook_url": "https://discord.com/api/webhooks/...",
  "telegram": {
    "bot_token": "123:ABC",
    "chat_id": "-100123",
    "enabled": true
  }
}
```

**POST /api/notifications/send**
Body: `{ "title": "Test", "message": "Hello", "severity": "info|success|warning|critical" }`

```bash
curl http://localhost:8000/api/notifications/preferences
```

---

## Portfolio

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/portfolio/overview` | Aggregated portfolio overview |

### Key Details

**GET /api/portfolio/overview**
Query: `?days=30`
Returns:
```json
{
  "total_equity": 50000,
  "total_pnl": 1200,
  "today_pnl": 85,
  "total_trades": 340,
  "overall_win_rate": 0.62,
  "overall_sharpe": 1.45,
  "overall_max_drawdown": 0.08,
  "agents": [...],
  "strategies": [...],
  "equity_curve": [{ "date": "2024-01-15", "value": 10500 }],
  "daily_pnl": [{ "date": "2024-01-15", "pnl": 85 }]
}
```

```bash
curl "http://localhost:8000/api/portfolio/overview?days=30"
```

---

## Intelligence

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/intelligence/pulse/{symbol}` | Real-time market snapshot (no LLM) |
| GET | `/api/intelligence/analysis/{symbol}` | LLM-synthesised market analysis |
| GET | `/api/intelligence/suggest/{symbol}` | LLM trade suggestion |
| GET | `/api/intelligence/agents/briefing` | Portfolio-level agent briefing |
| POST | `/api/intelligence/chat` | Conversational AI chat |

### Key Details

**GET /api/intelligence/pulse/{symbol}**
Returns: `{ "symbol": str, "price": float, "rsi": float, "ema_20": float, "regime": "trending_up|trending_down|ranging|volatile", "momentum": "bullish|bearish|neutral", ... }`

**POST /api/intelligence/chat**
Body: `{ "message": "Should I go long on BTC?", "context": {} }`
Returns: `{ "response": str, "market_analysis": {...}, "trade_suggestion": {...} }`

```bash
curl http://localhost:8000/api/intelligence/pulse/BTCUSDT
```

---

## Vault

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/vault/credentials` | Store encrypted exchange credentials |
| GET | `/api/vault/credentials` | List stored credentials (metadata only) |
| DELETE | `/api/vault/credentials/{id}` | Delete a credential |
| POST | `/api/vault/credentials/{id}/test` | Test credential connectivity via CCXT |

### Key Details

**POST /api/vault/credentials**
Body:
```json
{
  "exchange_id": "bybit",
  "label": "Bybit Main",
  "api_key": "...",
  "api_secret": "...",
  "passphrase": null,
  "is_testnet": false
}
```
Supported exchanges: `bybit`, `binance`, `okx`, `coinbase`, `kraken`, `bitget`, `kucoin`, `gate`, `htx`

Credentials are encrypted with AES-256-GCM at rest. API keys/secrets are never returned in GET responses.

```bash
curl http://localhost:8000/api/vault/credentials
curl -X POST http://localhost:8000/api/vault/credentials/{id}/test
```

---

## WebSocket

**URL**: `ws://localhost:8000/ws` (or `wss://` for TLS)

### Connection Flow

1. Connect to `/ws` → receive `{ "type": "connected", "id": "conn_id" }`
2. Subscribe to topics → `{ "action": "subscribe", "topics": ["positions", "fills", "alarms", "agents", "market"] }`
3. Receive confirmation → `{ "type": "subscribed", "topics": ["positions", "fills", ...] }`
4. Receive real-time data → `{ "topic": "positions", "data": { ... } }`

### Available Topics

| Topic | Description |
|-------|-------------|
| `positions` | Position updates (open, close, PnL changes) |
| `fills` | Order execution reports (fill, partial fill, reject) |
| `alarms` | Risk alerts and circuit breaker events |
| `agents` | Agent lifecycle status changes |
| `market` | Market data updates |

### Message Types (Server → Client)

| Type | Description |
|------|-------------|
| `connected` | Connection established with `id` field |
| `subscribed` | Topic subscription confirmed |
| `ping` | Server heartbeat (every 15s) — respond with `{ "action": "pong" }` |
| `error` | Error message |

### Client Actions

| Action | Payload | Description |
|--------|---------|-------------|
| `subscribe` | `{ "action": "subscribe", "topics": ["positions"] }` | Subscribe to topics |
| `unsubscribe` | `{ "action": "unsubscribe", "topics": ["market"] }` | Unsubscribe from topics |
| `pong` | `{ "action": "pong" }` | Heartbeat response |

### NATS Bridge

The WebSocket manager bridges NATS subjects to WebSocket topics:

| NATS Subject | WebSocket Topic |
|---|---|
| `trading.positions` | `positions` |
| `trading.executions` | `fills` |
| `risk.alarms` | `alarms` |
| `agent.status` | `agents` |
| `market.data` | `market` |

Stale connections (no pong for 30s) are automatically reaped.

---

## Error Responses

All endpoints return errors in a consistent format:

```json
{
  "detail": "Human-readable error message"
}
```

| Status Code | Meaning |
|-------------|---------|
| 400 | Bad request / validation error |
| 401 | Missing or invalid authentication |
| 403 | Forbidden (insufficient permissions) |
| 404 | Resource not found |
| 409 | Conflict (e.g., duplicate agent name) |
| 422 | Validation error (Pydantic) |
| 429 | Rate limit exceeded |
| 500 | Internal server error |
| 503 | Service unavailable (e.g., vault key not configured) |
