import asyncio
import json
import logging
import random
from datetime import datetime
from typing import List, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.application.backtest_engine import BacktestExecutionEngine
from src.application.strategy_manager import StrategyManager
from src.domain.entities import MarketData
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
execution_engine = BacktestExecutionEngine(initial_capital=250_000, slippage=0.0002, fee=0.0004)
strategy_manager = StrategyManager(execution_engine=execution_engine, data_feed=None, publisher=bridge.broadcast_json)

strategy_manager.register_strategy(
    "stat_arb", StatisticalArbitrageStrategy(("BTC/USDT", "ETH/USDT"), z_score_threshold=2.1)
)
strategy_manager.register_strategy("vol_breakout", VolatilityBreakoutStrategy(symbol="BTC/USDT", lookback=30, k=2.5))
strategy_manager.register_strategy("ml_skeleton", MLStrategy(model_path="models/lstm.bin"))


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await bridge.connect(websocket)
    await websocket.send_text(
        json.dumps(
            {"type": "status", "strategies": strategy_manager.status(), "equity": execution_engine.initial_capital}
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
            if action == "toggle_strategy":
                name = payload.get("name")
                enabled = bool(payload.get("enabled", True))
                try:
                    strategy_manager.set_enabled(name, enabled)
                except Exception as exc:  # noqa: BLE001
                    await websocket.send_text(json.dumps({"type": "error", "message": str(exc)}))
                else:
                    await bridge.broadcast_json({"type": "status", "strategies": strategy_manager.status()})
            elif action == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        await bridge.disconnect(websocket)


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


async def market_data_simulator():
    price = 50_000.0
    while True:
        drift = random.uniform(-25, 25)
        price = max(500.0, price + drift)
        now = datetime.utcnow()
        md = MarketData(
            symbol="BTC/USDT",
            timestamp=now,
            open=price,
            high=price + random.uniform(5, 20),
            low=price - random.uniform(5, 20),
            close=price,
            volume=random.uniform(10, 1000),
        )
        await strategy_manager.on_market_data(md)
        await asyncio.sleep(0.5)


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
    strategy_dict = request.strategy.dict()
    opt = request.optimization.dict() if request.optimization else None
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
    strategy_id = strategy_store.save(strategy.dict())
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
