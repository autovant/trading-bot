import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)

from src.api.models import (
    AccountSummaryResponse,
    OrderResponse,
    PositionResponse,
    TradeResponse,
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
        logger.exception("Failed to fetch account summary")
        raise HTTPException(status_code=500, detail="Failed to fetch account summary") from e


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
            created_at=p.created_at.isoformat() if p.created_at else None,
            updated_at=p.updated_at.isoformat() if p.updated_at else None
        ) for p in open_positions]
    except Exception as e:
        logger.exception("Failed to fetch positions")
        raise HTTPException(status_code=500, detail="Failed to fetch positions") from e

@market_router.get("/api/trades", response_model=List[TradeResponse])
async def get_trades(limit: int = Query(50, ge=1, le=1000), db: DatabaseManager = Depends(get_db)) -> List[TradeResponse]:
    try:
        trades = await db.get_trades(limit=limit)

        # Build agent lookup: map client_id prefix → (agent_name, strategy_name)
        agents = await db.list_agents()
        # For each agent, load recent decisions that have trade_ids
        cid_to_agent: dict[str, tuple[str, str]] = {}
        for agent in agents:
            if not agent.id:
                continue
            decisions = await db.get_agent_decisions(agent.id, limit=200)
            for d in decisions:
                if d.trade_ids:
                    for tid in d.trade_ids:
                        cid_to_agent[tid] = (agent.name, agent.strategy_name or '')

        result: list[TradeResponse] = []
        for t in trades:
            # Match client_id prefix (before the last hyphen-delimited segment)
            cid_prefix = '-'.join(t.client_id.split('-')[:-1]) if '-' in t.client_id else t.client_id
            agent_info = cid_to_agent.get(cid_prefix, (None, None))
            result.append(TradeResponse(
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
                mark_price=0.0,
                slippage_bps=0.0,
                achieved_vs_signal_bps=t.achieved_vs_signal_bps,
                latency_ms=t.latency_ms,
                maker=t.maker,
                mode=t.mode,
                run_id=t.run_id,
                timestamp=t.timestamp.isoformat() if t.timestamp else None,
                is_shadow=t.is_shadow,
                agent_name=agent_info[0],
                strategy_name=agent_info[1],
            ))
        return result
    except Exception as e:
        logger.exception("Failed to fetch trades")
        raise HTTPException(status_code=500, detail="Failed to fetch trades") from e


@market_router.get("/api/orders", response_model=List[OrderResponse])
async def get_orders(status_filter: Optional[str] = None, db: DatabaseManager = Depends(get_db)) -> List[OrderResponse]:
    try:
        orders = await db.get_orders(status=status_filter)
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
        logger.exception("Failed to fetch orders")
        raise HTTPException(status_code=500, detail="Failed to fetch orders") from e

@market_router.get("/api/klines")
async def get_klines(
    symbol: str,
    interval: str = "15",
    limit: int = Query(200, ge=1, le=1000),
    exchange = Depends(get_exchange),
):
    try:
        klines, _ = await exchange.get_klines(symbol, interval, limit)
        # Format for frontend Candle interface: { time, open, high, low, close, volume }
        formatted = []
        for k in klines:
            if isinstance(k, dict):
                formatted.append({
                    "time": k.get("timestamp") or k.get("time") or k.get("t", 0),
                    "open": float(k.get("open") or k.get("o", 0)),
                    "high": float(k.get("high") or k.get("h", 0)),
                    "low": float(k.get("low") or k.get("l", 0)),
                    "close": float(k.get("close") or k.get("c", 0)),
                    "volume": float(k.get("volume") or k.get("v", 0)),
                })
            elif isinstance(k, (list, tuple)) and len(k) >= 6:
                formatted.append({
                    "time": k[0],
                    "open": float(k[1]),
                    "high": float(k[2]),
                    "low": float(k[3]),
                    "close": float(k[4]),
                    "volume": float(k[5]),
                })
            else:
                formatted.append(k)
        return formatted
    except Exception as e:
        logger.exception("Failed to fetch klines")
        raise HTTPException(status_code=500, detail="Failed to fetch klines") from e


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
        logger.exception("Failed to place order for %s", request.symbol)
        raise HTTPException(
            status_code=500,
            detail=f"Order placement failed: {e}",
        ) from e


@market_router.delete("/api/orders/{order_id}")
async def cancel_order(order_id: str, exchange = Depends(get_exchange)):
    """Cancel an order via the exchange adapter."""
    if not exchange:
        raise HTTPException(status_code=503, detail="Exchange not initialized")
    try:
        result = await exchange.cancel_order(order_id)
        return {"status": "cancelled", "order_id": order_id, "result": result}
    except Exception as e:
        logger.exception("Failed to cancel order")
        raise HTTPException(status_code=500, detail="Failed to cancel order") from e
