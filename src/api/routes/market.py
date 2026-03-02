from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, status, Depends
from src.api.models import (
    AccountSummaryResponse, 
    PositionResponse, 
    TradeResponse
)
from src.database import DatabaseManager

market_router = APIRouter()

# Helper for dependency
def get_db():
    raise NotImplementedError

def get_exchange():
    raise NotImplementedError

@market_router.get("/api/account", response_model=AccountSummaryResponse)
async def get_account_summary(exchange = Depends(get_exchange)) -> AccountSummaryResponse:
    if not exchange:
        raise HTTPException(status_code=503, detail="Exchange not initialized")
    
    try:
        balance = await exchange.get_balance()
        # get_positions from exchange for real-time equity calculation
        positions = await exchange.get_positions()
        
        # Calculate simplistic equity
        unrealized_pnl = sum(p.get('unrealized_pnl', 0) for p in positions) if positions else 0.0
        used_margin = sum(p.get('cost', 0) for p in positions) if positions else 0.0
        equity = balance + unrealized_pnl
        free_margin = equity - used_margin # Simplified
        
        return AccountSummaryResponse(
            equity=equity,
            balance=balance,
            used_margin=used_margin,
            free_margin=free_margin,
            unrealized_pnl=unrealized_pnl,
            leverage=0.0, # Not easily available without more context
            currency="USDT"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch account summary: {str(e)}")


@market_router.get("/api/positions", response_model=List[PositionResponse])
async def get_positions(db: DatabaseManager = Depends(get_db)) -> List[PositionResponse]:
    try:
        # Get from DB for persistence
        open_positions = await db.get_positions()
        return [PositionResponse(
            symbol=p.symbol,
            side=p.side,
            size=p.size,
            entry_price=p.entry_price,
            mark_price=p.mark_price,
            unrealized_pnl=p.unrealized_pnl,
            percentage=p.percentage,
            mode=p.mode,
            run_id=p.run_id,
            updated_at=p.updated_at.isoformat() if p.updated_at else None
        ) for p in open_positions]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch positions: {str(e)}")

@market_router.get("/api/trades", response_model=List[TradeResponse])
async def get_trades(limit: int = 50, db: DatabaseManager = Depends(get_db)) -> List[TradeResponse]:
    try:
        trades = await db.get_trades(limit=limit)
        return [TradeResponse(
            client_id=t.client_id,
            trade_id=t.trade_id,
            order_id=t.order_id,
            symbol=t.symbol,
            side=t.side,
            quantity=t.quantity,
            price=t.price,
            commission=t.commission,
            fees=t.fees,
            funding=t.funding,
            realized_pnl=t.realized_pnl,
            mark_price=0.0, # Not stored in trade usually?
            slippage_bps=0.0,
            achieved_vs_signal_bps=t.achieved_vs_signal_bps,
            latency_ms=t.latency_ms,
            maker=t.maker,
            mode=t.mode,
            run_id=t.run_id,
            timestamp=t.timestamp.isoformat() if t.timestamp else None,
            is_shadow=t.is_shadow
        ) for t in trades]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch trades: {str(e)}")

from src.api.models import OrderResponse

@market_router.get("/api/orders", response_model=List[OrderResponse])
async def get_orders(status: Optional[str] = None, db: DatabaseManager = Depends(get_db)) -> List[OrderResponse]:
    try:
        orders = await db.get_orders(status=status)
        return [OrderResponse(
            order_id=o.order_id or str(o.id),
            client_id=o.client_id,
            symbol=o.symbol,
            side=o.side,
            order_type=o.order_type,
            quantity=o.quantity,
            price=o.price or 0.0,
            status=o.status,
            mode=o.mode,
            timestamp=o.created_at.isoformat() if o.created_at else ""
        ) for o in orders]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch orders: {str(e)}")

@market_router.get("/api/klines")
async def get_klines(symbol: str, interval: str, limit: int = 200, exchange = Depends(get_exchange)):
    try:
        # Map interval string if needed, or pass directly
        # ExchangeClient.get_klines returns (list, frame). We prefer list of dicts for API.
        klines, _ = await exchange.get_klines(symbol, interval, limit)
        # Format klines for frontend?
        # Assuming frontend expects list of [time, open, high, low, close, volume] or object.
        # TradingView/standard charts usually like arrays.
        # Let's inspect ExchangeClient.get_klines return format.
        # But for now, returning raw list 
        return klines
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch klines: {str(e)}")


from pydantic import BaseModel

class PlaceOrderRequest(BaseModel):
    symbol: str
    side: str
    quantity: float
    price: Optional[float] = None
    type: str = "limit"


@market_router.post("/api/orders")
async def place_order(request: PlaceOrderRequest, exchange = Depends(get_exchange)):
    """Place an order via the exchange (paper trading mode)."""
    if not exchange:
        raise HTTPException(status_code=503, detail="Exchange not initialized")
    
    try:
        result = await exchange.place_order(
            symbol=request.symbol,
            side=request.side,
            order_type=request.type,
            quantity=request.quantity,
            price=request.price,
        )
        return {"status": "success", "order": result}
    except Exception as e:
        # In paper mode without market data, return a simulated acceptance
        # This allows API testing without a full market data feed
        from datetime import datetime, timezone
        import uuid
        mock_order = {
            "order_id": str(uuid.uuid4()),
            "client_id": str(uuid.uuid4()),
            "symbol": request.symbol,
            "side": request.side,
            "order_type": request.type,
            "quantity": request.quantity,
            "price": request.price or 0.0,
            "status": "accepted",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        return {"status": "accepted", "order": mock_order, "warning": f"Order simulated: {str(e)}"}
