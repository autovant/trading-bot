"""
TradingView Webhook + Signal History routes.

- POST /api/webhook/tradingview — receive TradingView alert webhooks (HMAC-validated)
- GET  /api/signals/history        — paginated signal history
- PUT  /api/signals/config         — toggle auto-execution
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel

from src.database import DatabaseManager, Signal

logger = logging.getLogger(__name__)

signals_router = APIRouter(tags=["signals"])

# In-memory config (could be persisted to DB if needed)
_signal_config: Dict[str, Any] = {
    "auto_execute": False,
    "allowed_symbols": [],  # empty = all symbols allowed
}


# Dependencies — overridden at app startup
async def get_db() -> DatabaseManager:
    raise NotImplementedError


async def get_messaging():
    raise NotImplementedError


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class TradingViewAlert(BaseModel):
    """Expected shape of a TradingView webhook alert."""
    symbol: str
    side: str  # "buy" or "sell"
    price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    confidence: Optional[float] = None
    message: Optional[str] = None


class SignalConfigUpdate(BaseModel):
    auto_execute: Optional[bool] = None
    allowed_symbols: Optional[List[str]] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@signals_router.post("/api/webhook/tradingview")
async def tradingview_webhook(
    request: Request,
    x_tv_signature: Optional[str] = Header(None, alias="X-TV-Signature"),
    db: DatabaseManager = Depends(get_db),
):
    """
    Receive a TradingView webhook alert.

    If ``TRADINGVIEW_WEBHOOK_SECRET`` is set, validates HMAC-SHA256 signature.
    Stores the signal and optionally auto-executes if enabled.
    """
    body = await request.body()

    # HMAC validation
    secret = os.environ.get("TRADINGVIEW_WEBHOOK_SECRET", "")
    if secret:
        if not x_tv_signature:
            raise HTTPException(status_code=401, detail="Missing webhook signature")
        expected = hmac.new(
            secret.encode(), body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, x_tv_signature):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        import json
        payload = json.loads(body)
        alert = TradingViewAlert(**payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid alert payload") from exc

    # Check allowed symbols
    if _signal_config["allowed_symbols"] and alert.symbol not in _signal_config["allowed_symbols"]:
        raise HTTPException(status_code=403, detail=f"Symbol {alert.symbol} not in allowed list")

    # Persist signal
    signal = Signal(
        source="tradingview",
        symbol=alert.symbol,
        side=alert.side,
        confidence=alert.confidence,
        entry_price=alert.price,
        stop_loss=alert.stop_loss,
        take_profit=alert.take_profit,
        status="received",
        raw_payload=payload,
    )

    signal_id = await db.create_signal(signal)
    logger.info("Received TradingView signal: %s %s @ %s (id=%s)", alert.side, alert.symbol, alert.price, signal_id)

    # Auto-execution
    auto_executed = False
    if _signal_config["auto_execute"] and signal_id:
        try:
            from src.services.signal_service import process_signal
            await process_signal(signal, db)
            auto_executed = True
            await db.update_signal_status(signal_id, "executed", auto_executed=True)
        except Exception as e:
            logger.error("Auto-execution failed for signal %s: %s", signal_id, e)
            await db.update_signal_status(signal_id, "execution_failed")

    return {
        "status": "ok",
        "signal_id": signal_id,
        "auto_executed": auto_executed,
    }


@signals_router.get("/api/signals/history")
async def signal_history(
    limit: int = Query(50, ge=1, le=500),
    source: Optional[str] = Query(None),
    db: DatabaseManager = Depends(get_db),
):
    """Get paginated signal history."""
    signals = await db.list_signals(limit=limit, source=source)
    return {"signals": [s.__dict__ for s in signals], "total": len(signals)}


@signals_router.put("/api/signals/config")
async def update_signal_config(update: SignalConfigUpdate):
    """Toggle auto-execution and configure allowed symbols."""
    if update.auto_execute is not None:
        _signal_config["auto_execute"] = update.auto_execute
    if update.allowed_symbols is not None:
        _signal_config["allowed_symbols"] = update.allowed_symbols
    return _signal_config


@signals_router.get("/api/signals/config")
async def get_signal_config():
    """Get current signal configuration."""
    return _signal_config
