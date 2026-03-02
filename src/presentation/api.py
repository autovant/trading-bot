import asyncio
import json
import logging
import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import httpx
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.application.backtest_engine import BacktestExecutionEngine
from src.application.strategy_manager import StrategyManager
from src.domain.entities import MarketData, Order as DomainOrder, OrderType as DomainOrderType, Side as DomainSide, OrderStatus as DomainOrderStatus
from src.services.strategy_store import StrategyStore
from src.strategies.dynamic_engine import DynamicStrategyEngine
from src.strategies.ml_skeleton import MLStrategy
from src.strategies.stat_arb import StatisticalArbitrageStrategy
from src.strategies.volatility_breakout import VolatilityBreakoutStrategy

logger = logging.getLogger(__name__)

app = FastAPI(title="Trading Bot API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class FrontendBridge:
    """Simple WebSocket broadcaster for the cyberpunk dashboard."""

    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        async with self._lock:
            self.active_connections.append(websocket)

    async def disconnect(self, websocket: WebSocket):
        async with self._lock:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)

    async def broadcast_json(self, payload: dict):
        if not self.active_connections:
            return
        message = json.dumps(payload, default=self._default_json)
        async with self._lock:
            stale = []
            for ws in self.active_connections:
                try:
                    await ws.send_text(message)
                except Exception:
                    stale.append(ws)
            for ws in stale:
                if ws in self.active_connections:
                    self.active_connections.remove(ws)

    @staticmethod
    def _default_json(obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return str(obj)


bridge = FrontendBridge()
execution_engine = BacktestExecutionEngine(
    initial_capital=250_000,
    slippage=0.0002,
    fee=0.0004,
    spread_bps=2.0,
    latency_ms=10,
    funding_rate=0.0,
    funding_interval_hours=8,
    maintenance_margin_pct=0.005,
    partial_fill_enabled=True,
    partial_fill_min_slice_pct=0.2,
    partial_fill_max_slices=4
)
# Mock Data Feed in Strategy Manager for now
strategy_manager = StrategyManager(
    execution_engine=execution_engine, data_feed=None, publisher=bridge.broadcast_json
)

strategy_manager.register_strategy(
    "stat_arb",
    StatisticalArbitrageStrategy(("BTC/USDT", "ETH/USDT"), z_score_threshold=2.1),
)
strategy_manager.register_strategy(
    "vol_breakout", VolatilityBreakoutStrategy(symbol="BTC/USDT", lookback=30, k=2.5)
)
strategy_manager.register_strategy(
    "ml_skeleton", MLStrategy(model_path="models/lstm.bin")
)

# --- In-Memory Stores for MVP ---
orders_db = []
signals_db = []
risk_config_db = {
    "killSwitch": False,
    "maxNotional": 100000.0,
    "dailyLossLimit": 5000.0
}

# --- Pydantic Models for API ---

class RiskConfig(BaseModel):
    killSwitch: bool
    maxNotional: float
    dailyLossLimit: float

class OrderRequest(BaseModel):
    symbol: str
    side: str  # BUY/SELL
    type: str  # MARKET/LIMIT/STOP
    size: float
    price: Optional[float] = None
    stopPrice: Optional[float] = None # For Stop orders
    idempotencyKey: Optional[str] = None

class SignalConfig(BaseModel):
    autoExecute: bool
    defaultSize: float
    maxSignalsPerMinute: int

# --- API Endpoints ---

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await bridge.connect(websocket)
    # Send initial status
    await websocket.send_text(
        json.dumps(
            {
                "type": "status",
                "strategies": strategy_manager.status(),
                "equity": execution_engine.initial_capital,
                "connection": "CONNECTED"
            }
        )
    )
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue

            action = payload.get("action")
            
            # Handle Subscriptions
            if action == "subscribe":
                # For now just ack subscription
                channels = payload.get("channels", [])
                await websocket.send_text(json.dumps({"type": "subscription_success", "channels": channels}))
            
            elif action == "toggle_strategy":
                name = payload.get("name")
                enabled = bool(payload.get("enabled", True))
                try:
                    strategy_manager.set_enabled(name, enabled)
                except Exception as exc:  # noqa: BLE001
                    await websocket.send_text(
                        json.dumps({"type": "error", "message": str(exc)})
                    )
                else:
                    await bridge.broadcast_json(
                        {"type": "status", "strategies": strategy_manager.status()}
                    )
            elif action == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
                
    except WebSocketDisconnect:
        await bridge.disconnect(websocket)


@app.get("/health")
async def health_check():
    return {"status": "healthy"}

# --- Market Data ---

BYBIT_REST_URL = "https://api.bybit.com"

# Interval mapping for Bybit V5 API
INTERVAL_MAP = {
    "1m": "1",
    "3m": "3",
    "5m": "5",
    "15m": "15",
    "30m": "30",
    "1h": "60",
    "2h": "120",
    "4h": "240",
    "6h": "360",
    "12h": "720",
    "1d": "D",
    "1w": "W",
    "1M": "M",
    # Direct numeric values (from frontend)
    "1": "1",
    "5": "5",
    "15": "15",
    "60": "60",
    "240": "240",
    "D": "D",
}


@app.get("/api/klines")
async def get_klines(
    symbol: str,
    interval: str = "1h",
    limit: int = 200,
    start: Optional[int] = None,
    end: Optional[int] = None,
):
    """
    Proxy to Bybit V5 Market Kline API with fallback to mock data.
    Returns standard OHLCV structure for the frontend chart.
    
    Args:
        symbol: Trading pair (e.g., 'BTCUSDT')
        interval: Kline interval (1m, 5m, 15m, 30m, 1h, 4h, 1d)
        limit: Number of candles to return (max 1000)
        start: Start timestamp in milliseconds
        end: End timestamp in milliseconds
    """
    # Map interval to Bybit format
    bybit_interval = INTERVAL_MAP.get(interval, "60")
    
    # Build request params
    params = {
        "category": "linear",
        "symbol": symbol,
        "interval": bybit_interval,
        "limit": min(limit, 1000),  # Bybit max is 1000
    }
    
    if start:
        params["start"] = start
    if end:
        params["end"] = end
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{BYBIT_REST_URL}/v5/market/kline",
                params=params,
            )
            
            # Check if we got blocked (403) or other HTTP error
            if response.status_code != 200:
                logger.warning(f"Bybit API returned {response.status_code}, using fallback data")
                return _generate_mock_klines(symbol, interval, limit, end)
            
            data = response.json()
            
            # Check for API errors
            if data.get("retCode") != 0:
                logger.warning(f"Bybit API error: {data.get('retMsg')}, using fallback data")
                return _generate_mock_klines(symbol, interval, limit, end)
            
            # Transform Bybit response to frontend format
            # Bybit returns: [startTime, openPrice, highPrice, lowPrice, closePrice, volume, turnover]
            raw_list = data.get("result", {}).get("list", [])
            
            if not raw_list:
                return _generate_mock_klines(symbol, interval, limit, end)
            
            # Bybit returns data in descending order (newest first), we need ascending
            candles = []
            for item in reversed(raw_list):
                ts = int(item[0])
                candles.append({
                    "time": datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%H:%M"),
                    "timestamp": ts,
                    "open": float(item[1]),
                    "high": float(item[2]),
                    "low": float(item[3]),
                    "close": float(item[4]),
                    "volume": float(item[5]),
                })
            
            return candles
            
    except (httpx.TimeoutException, httpx.ConnectError) as e:
        logger.warning(f"Bybit API connection error: {e}, using fallback data")
        return _generate_mock_klines(symbol, interval, limit, end)
    except Exception as e:
        logger.warning(f"Bybit API error: {e}, using fallback data")
        return _generate_mock_klines(symbol, interval, limit, end)


def _generate_mock_klines(symbol: str, interval: str, limit: int, end_ms: Optional[int] = None) -> list:
    """
    Generate realistic mock klines when live API is unavailable.
    Uses deterministic random seeding for consistency.
    """
    # Base prices for different symbols
    base_prices = {
        "BTCUSDT": 93000.0,
        "ETHUSDT": 3400.0,
        "SOLUSDT": 180.0,
        "XRPUSDT": 2.2,
        "DOGEUSDT": 0.35,
    }
    
    price = base_prices.get(symbol, 50000.0)
    
    # Determine minutes per interval
    interval_minutes = {
        "1m": 1, "1": 1,
        "5m": 5, "5": 5,
        "15m": 15, "15": 15,
        "1h": 60, "60": 60,
        "4h": 240, "240": 240,
        "1d": 1440, "D": 1440,
    }
    minutes = interval_minutes.get(interval, 60)
    
    # Generate from end time backwards
    if end_ms:
        anchor_time = datetime.fromtimestamp(end_ms / 1000, tz=timezone.utc)
    else:
        anchor_time = datetime.now(timezone.utc)
    
    candles = []
    random.seed(42)  # Deterministic for consistency
    
    for i in range(limit):
        timestamp = anchor_time - timedelta(minutes=minutes * (limit - 1 - i))
        ts_ms = int(timestamp.timestamp() * 1000)
        
        # Random walk with mean reversion
        change = random.gauss(0, 0.003)  # 0.3% std dev
        price = price * (1 + change)
        
        # Generate OHLC with realistic wicks
        wick_up = abs(random.gauss(0, 0.001))
        wick_down = abs(random.gauss(0, 0.001))
        body = random.gauss(0, 0.002)
        
        open_p = price * (1 - body/2)
        close_p = price * (1 + body/2)
        high_p = max(open_p, close_p) * (1 + wick_up)
        low_p = min(open_p, close_p) * (1 - wick_down)
        
        candles.append({
            "time": timestamp.strftime("%H:%M"),
            "timestamp": ts_ms,
            "open": round(open_p, 2),
            "high": round(high_p, 2),
            "low": round(low_p, 2),
            "close": round(close_p, 2),
            "volume": round(random.uniform(100, 2000), 2),
        })
    
    return candles


# --- Orders ---

@app.get("/api/orders")
async def get_orders():
    return orders_db

@app.post("/api/orders")
async def place_order(request: OrderRequest):
    order_id = str(uuid.uuid4())
    event_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc)
    
    # Determine order status based on type
    if request.type == "MARKET":
        status = "FILLED"
    elif request.type == "STOP":
        status = "PENDING"  # Stop orders wait for trigger
    else:
        status = "OPEN"
    
    new_order = {
        "id": order_id,
        "symbol": request.symbol,
        "side": request.side,
        "type": request.type,
        "size": request.size,
        "price": request.price or 0.0,
        "stopPrice": request.stopPrice,
        "status": status,
        "timestamp": int(timestamp.timestamp() * 1000),
        "exchange": "BYBIT",
        "isSimulation": True,
        "idempotencyKey": request.idempotencyKey,
        "filledSize": request.size if status == "FILLED" else 0,
        "avgFillPrice": request.price if status == "FILLED" else None,
        "sequence": 0,
        "eventId": event_id
    }
    
    orders_db.append(new_order)
    
    # Broadcast order update via WebSocket
    await bridge.broadcast_json({
        "type": "ORDER_UPDATE",
        "data": {
            "orderId": order_id,
            "status": status,
            "filledSize": new_order["filledSize"],
            "avgFillPrice": new_order["avgFillPrice"],
            "sequence": 1,
            "eventId": event_id,
            "timestamp": new_order["timestamp"],
            "isReplay": False
        }
    })
    
    return {"success": True, "orderId": order_id}

@app.delete("/api/orders/{order_id}")
async def cancel_order(order_id: str):
    # Find and update order
    for order in orders_db:
        if order["id"] == order_id:
            order["status"] = "CANCELLED"
            await bridge.broadcast_json({
                "type": "ORDER_UPDATE",
                "data": order
            })
            return {"success": True}
    raise HTTPException(status_code=404, detail="Order not found")

# --- Risk ---

@app.get("/api/risk")
async def get_risk_config():
    return risk_config_db

@app.post("/api/risk")
async def update_risk_config(config: RiskConfig):
    global risk_config_db
    risk_config_db = config.dict()
    return risk_config_db

# --- Signals ---

@app.get("/api/signals")
async def get_signals(limit: int = 20):
    return signals_db[-limit:]

@app.post("/api/signals/{signal_id}/execute")
async def execute_signal(signal_id: str):
    # Mock execution logic
    return {"success": True, "message": "Signal executed successfully"}

# --- Background Simulation ---

async def market_data_simulator():
    """Simulates live ticker and orderbook updates"""
    price = 50_000.0
    while True:
        drift = random.uniform(-25, 25)
        price = max(500.0, price + drift)
        
        # Broadcast Ticker
        await bridge.broadcast_json({
            "type": "ticker",
            "data": {
                "symbol": "BTC-PERP",
                "price": price,
                "timestamp": int(datetime.utcnow().timestamp() * 1000)
            }
        })
        
        # Broadcast OrderBook (Partial)
        await bridge.broadcast_json({
            "type": "orderBook",
            "data": {
                "bids": [{"price": price - i*10, "size": random.uniform(0.1, 2), "total": 0, "percent": 0} for i in range(1, 6)],
                "asks": [{"price": price + i*10, "size": random.uniform(0.1, 2), "total": 0, "percent": 0} for i in range(1, 6)]
            }
        })
        
        await asyncio.sleep(1.0) # 1 sec update rate

@app.on_event("startup")
async def startup_event():
    await strategy_manager.start()
    asyncio.create_task(market_data_simulator())


dynamic_engine = DynamicStrategyEngine()
strategy_store = StrategyStore()


class Trigger(BaseModel):
    indicator: str
    timeframe: str
    operator: str
    value: str | float
    params: dict = Field(default_factory=dict)


class RiskBlock(BaseModel):
    initial_capital: float = 100_000.0
    risk_per_trade_pct: float = 1.0
    stop_loss_pct: float = 1.0
    take_profit_pct: float = 2.0


class StrategyConfig(BaseModel):
    name: str
    triggers: List[Trigger]
    logic: str = "AND"
    risk: RiskBlock = RiskBlock()


class OptimizationConfig(BaseModel):
    trigger_index: int = 0
    start: float
    end: float
    step: float


class BacktestRequest(BaseModel):
    strategy: StrategyConfig
    symbol: str
    start_date: str
    end_date: str
    optimization: Optional[OptimizationConfig] = None


@app.post("/api/backtest/dynamic")
async def run_dynamic_backtest(request: BacktestRequest):
    strategy_dict = request.strategy.model_dump()
    opt = request.optimization.model_dump() if request.optimization else None
    try:
        result = await dynamic_engine.run_backtest(
            strategy_dict,
            request.symbol,
            request.start_date,
            request.end_date,
            optimization=opt,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@app.post("/api/strategies")
async def save_strategy(strategy: StrategyConfig):
    strategy_id = strategy_store.save(strategy.model_dump())
    return {"id": strategy_id, "name": strategy.name}


@app.get("/api/strategies")
async def list_strategies():
    return strategy_store.list()


@app.get("/api/strategies/{strategy_id}")
async def get_strategy(strategy_id: int):
    strategy = strategy_store.get(strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return strategy
