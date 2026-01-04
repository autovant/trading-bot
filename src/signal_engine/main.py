"""
FastAPI application for the Confluence Signal Engine.

Endpoints:
- Health check
- Signal retrieval (latest, history)
- Subscription management
- Strategy configuration
- WebSocket streaming
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from src.signal_engine.alert_router import AlertRouter
from src.signal_engine.config import ConfigManager, get_default_strategy
from src.signal_engine.market_data import MarketDataService, SubscriptionManager
from src.signal_engine.schemas import (
    AlertPayload,
    SignalOutput,
    SignalRecord,
    StrategyProfile,
    SubscriptionConfig,
)
from src.signal_engine.signal_engine import SignalEngine, SignalProcessor

logger = logging.getLogger(__name__)

# =============================================================================
# Request/Response Models
# =============================================================================


class HealthResponse(BaseModel):
    status: str
    subscriptions_active: int
    websocket_connections: int
    timestamp: str


class SubscriptionCreate(BaseModel):
    exchange: str
    symbol: str
    timeframe: str
    strategy: str = "default"
    enabled: bool = True


class SubscriptionResponse(BaseModel):
    id: int
    exchange: str
    symbol: str
    timeframe: str
    strategy: str
    enabled: bool


class StrategyCreate(BaseModel):
    name: str
    description: Optional[str] = None
    timeframe: Optional[str] = None
    weights: Optional[Dict[str, float]] = None
    buy_threshold: int = 60
    sell_threshold: int = 40
    min_trend_score: int = 10
    gates: Optional[Dict[str, Any]] = None


class SignalResponse(BaseModel):
    exchange: str
    symbol: str
    tf: str
    ts: int
    score: int
    side: str
    strength: str
    reasons: List[str]
    idempotency_key: str


# =============================================================================
# Global State
# =============================================================================


class SignalEngineState:
    """Global state for the signal engine."""
    
    def __init__(self):
        self.config_manager: Optional[ConfigManager] = None
        self.market_data: Optional[MarketDataService] = None
        self.subscription_manager: Optional[SubscriptionManager] = None
        self.signal_processor: Optional[SignalProcessor] = None
        self.alert_router: Optional[AlertRouter] = None
        
        # Store recent signals for API retrieval
        self.recent_signals: Dict[tuple, SignalOutput] = {}
        self.signal_history: List[SignalOutput] = []
        self.max_history = 1000


state = SignalEngineState()


# =============================================================================
# Lifecycle
# =============================================================================


async def on_candle_update(
    subscription: SubscriptionConfig,
    df,
    candle_closed: bool,
    data_degraded: bool,
) -> None:
    """Callback for subscription updates."""
    if state.signal_processor is None or state.alert_router is None:
        return
    
    if not candle_closed:
        # Only process on candle close
        return
    
    strategy = state.config_manager.get_strategy(subscription.strategy)
    
    # Update processor cache
    state.signal_processor.update_data(
        subscription.exchange,
        subscription.symbol,
        subscription.timeframe,
        df,
    )
    
    if data_degraded:
        state.signal_processor.engine.mark_data_degraded(
            subscription.exchange,
            subscription.symbol,
            subscription.timeframe,
        )
    else:
        state.signal_processor.engine.mark_data_healthy(
            subscription.exchange,
            subscription.symbol,
            subscription.timeframe,
        )
    
    # Process signal
    signal = state.signal_processor.process(
        exchange=subscription.exchange,
        symbol=subscription.symbol,
        timeframe=subscription.timeframe,
        strategy=strategy,
        candle_closed=candle_closed,
    )
    
    if signal:
        # Store signal
        key = (signal.exchange, signal.symbol, signal.timeframe)
        state.recent_signals[key] = signal
        state.signal_history.append(signal)
        
        # Trim history
        if len(state.signal_history) > state.max_history:
            state.signal_history = state.signal_history[-state.max_history:]
        
        # Route alert
        await state.alert_router.route(signal)
        
        logger.info(
            f"Signal emitted: {signal.side.value} {signal.symbol} "
            f"score={signal.score}"
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown."""
    logger.info("Starting Confluence Signal Engine...")
    
    # Initialize components
    state.config_manager = ConfigManager()
    state.market_data = MarketDataService()
    state.subscription_manager = SubscriptionManager(
        state.market_data,
        poll_interval_multiplier=state.config_manager.config.poll_interval_multiplier,
    )
    state.signal_processor = SignalProcessor()
    
    alerts_config = state.config_manager.alerts
    state.alert_router = AlertRouter(
        websocket_enabled=alerts_config.websocket_enabled,
        webhooks=alerts_config.webhooks,
        redis_url=alerts_config.redis_url if alerts_config.redis_enabled else None,
        redis_channel=alerts_config.redis_channel,
    )
    
    # Load subscriptions from config
    for sub in state.config_manager.subscriptions:
        state.subscription_manager.add_subscription(sub)
    
    # Start subscription polling
    # NOTE: Uncomment to auto-start polling on startup
    # await state.subscription_manager.start(on_candle_update)
    
    logger.info("Confluence Signal Engine started")
    
    yield
    
    # Shutdown
    logger.info("Shutting down Confluence Signal Engine...")
    
    if state.subscription_manager:
        await state.subscription_manager.stop()
    
    if state.market_data:
        await state.market_data.close_all()
    
    if state.alert_router:
        await state.alert_router.close()
    
    logger.info("Confluence Signal Engine stopped")


# =============================================================================
# FastAPI Application
# =============================================================================


app = FastAPI(
    title="Confluence Signal Engine",
    description="Multi-asset, multi-timeframe trading signal generation with 0-100 confluence scoring",
    version="1.0.0",
    lifespan=lifespan,
)


# =============================================================================
# Health Endpoints
# =============================================================================


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Check service health."""
    ws_count = 0
    if state.alert_router and state.alert_router.ws_manager:
        ws_count = state.alert_router.ws_manager.connection_count
    
    sub_count = len(state.subscription_manager._subscriptions) if state.subscription_manager else 0
    
    return HealthResponse(
        status="healthy",
        subscriptions_active=sub_count,
        websocket_connections=ws_count,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


# =============================================================================
# Signal Endpoints
# =============================================================================


@app.get("/signals/latest")
async def get_latest_signals(
    exchange: Optional[str] = Query(None),
    symbol: Optional[str] = Query(None),
    tf: Optional[str] = Query(None),
):
    """Get latest signals, optionally filtered."""
    if exchange and symbol and tf:
        key = (exchange, symbol, tf)
        signal = state.recent_signals.get(key)
        if signal:
            return AlertPayload.from_signal(signal).model_dump()
        raise HTTPException(status_code=404, detail="No signal found for this subscription")
    
    # Return all recent signals
    return [AlertPayload.from_signal(s).model_dump() for s in state.recent_signals.values()]


@app.get("/signals/history")
async def get_signal_history(
    exchange: Optional[str] = Query(None),
    symbol: Optional[str] = Query(None),
    tf: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
):
    """Get signal history."""
    signals = state.signal_history
    
    # Filter if specified
    if exchange:
        signals = [s for s in signals if s.exchange == exchange]
    if symbol:
        signals = [s for s in signals if s.symbol == symbol]
    if tf:
        signals = [s for s in signals if s.timeframe == tf]
    
    # Return most recent
    signals = signals[-limit:]
    
    return [AlertPayload.from_signal(s).model_dump() for s in reversed(signals)]


# =============================================================================
# Subscription Endpoints
# =============================================================================


@app.get("/subscriptions", response_model=List[SubscriptionResponse])
async def list_subscriptions():
    """List all subscriptions."""
    if not state.subscription_manager:
        return []
    
    return [
        SubscriptionResponse(
            id=sub.id or 0,
            exchange=sub.exchange,
            symbol=sub.symbol,
            timeframe=sub.timeframe,
            strategy=sub.strategy,
            enabled=sub.enabled,
        )
        for sub in state.subscription_manager._subscriptions.values()
    ]


@app.post("/subscriptions", response_model=SubscriptionResponse)
async def create_subscription(request: SubscriptionCreate):
    """Create a new subscription."""
    if not state.subscription_manager:
        raise HTTPException(status_code=500, detail="Service not initialized")
    
    sub = SubscriptionConfig(
        exchange=request.exchange,
        symbol=request.symbol,
        timeframe=request.timeframe,
        strategy=request.strategy,
        enabled=request.enabled,
    )
    
    sub_id = state.subscription_manager.add_subscription(sub)
    
    return SubscriptionResponse(
        id=sub_id,
        exchange=sub.exchange,
        symbol=sub.symbol,
        timeframe=sub.timeframe,
        strategy=sub.strategy,
        enabled=sub.enabled,
    )


@app.delete("/subscriptions/{sub_id}")
async def delete_subscription(sub_id: int):
    """Delete a subscription."""
    if not state.subscription_manager:
        raise HTTPException(status_code=500, detail="Service not initialized")
    
    if state.subscription_manager.remove_subscription(sub_id):
        return {"status": "deleted", "id": sub_id}
    
    raise HTTPException(status_code=404, detail="Subscription not found")


# =============================================================================
# Strategy Endpoints
# =============================================================================


@app.get("/strategies")
async def list_strategies():
    """List all strategies."""
    if not state.config_manager:
        return []
    
    return [
        {
            "name": name,
            "buy_threshold": s.buy_threshold,
            "sell_threshold": s.sell_threshold,
            "timeframe": s.timeframe,
        }
        for name, s in state.config_manager._strategies.items()
    ]


@app.post("/strategies")
async def create_strategy(request: StrategyCreate):
    """Create a new strategy."""
    if not state.config_manager:
        raise HTTPException(status_code=500, detail="Service not initialized")
    
    from src.signal_engine.schemas import BucketWeights, GateConfig
    
    weights = BucketWeights(**(request.weights or {}))
    gates = GateConfig(**(request.gates or {}))
    
    strategy = StrategyProfile(
        name=request.name,
        description=request.description,
        timeframe=request.timeframe,
        weights=weights,
        buy_threshold=request.buy_threshold,
        sell_threshold=request.sell_threshold,
        min_trend_score=request.min_trend_score,
        gates=gates,
    )
    
    state.config_manager.add_strategy(strategy)
    
    return {"status": "created", "name": strategy.name}


@app.delete("/strategies/{name}")
async def delete_strategy(name: str):
    """Delete a strategy."""
    if not state.config_manager:
        raise HTTPException(status_code=500, detail="Service not initialized")
    
    if name == "default":
        raise HTTPException(status_code=400, detail="Cannot delete default strategy")
    
    if state.config_manager.remove_strategy(name):
        return {"status": "deleted", "name": name}
    
    raise HTTPException(status_code=404, detail="Strategy not found")


# =============================================================================
# Control Endpoints
# =============================================================================


@app.post("/start")
async def start_polling():
    """Start polling all subscriptions."""
    if not state.subscription_manager:
        raise HTTPException(status_code=500, detail="Service not initialized")
    
    await state.subscription_manager.start(on_candle_update)
    return {"status": "started"}


@app.post("/stop")
async def stop_polling():
    """Stop polling all subscriptions."""
    if not state.subscription_manager:
        raise HTTPException(status_code=500, detail="Service not initialized")
    
    await state.subscription_manager.stop()
    return {"status": "stopped"}


# =============================================================================
# WebSocket Endpoint
# =============================================================================


@app.websocket("/ws/stream")
async def websocket_stream(
    websocket: WebSocket,
    exchange: Optional[str] = Query(None),
    symbol: Optional[str] = Query(None),
    tf: Optional[str] = Query(None),
):
    """WebSocket stream for real-time signals."""
    await websocket.accept()
    
    if state.alert_router:
        state.alert_router.add_websocket(websocket, exchange, symbol, tf)
    
    try:
        # Send welcome message
        await websocket.send_json({
            "type": "connected",
            "exchange": exchange,
            "symbol": symbol,
            "tf": tf,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        
        # Keep connection alive
        while True:
            try:
                # Wait for any message (ping/pong or disconnect)
                data = await asyncio.wait_for(websocket.receive_text(), timeout=60)
                
                # Echo pings
                if data == "ping":
                    await websocket.send_text("pong")
                    
            except asyncio.TimeoutError:
                # Send heartbeat
                await websocket.send_json({"type": "heartbeat"})
                
    except WebSocketDisconnect:
        pass
    finally:
        if state.alert_router:
            state.alert_router.remove_websocket(websocket)


# =============================================================================
# Entry Point
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    
    uvicorn.run(app, host="0.0.0.0", port=8086)
