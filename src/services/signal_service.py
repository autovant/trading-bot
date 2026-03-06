"""
Signal Service — processes incoming signals and converts them to order intents.

Used by the TradingView webhook route for auto-execution.
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from src.database import DatabaseManager, Signal

logger = logging.getLogger(__name__)


async def process_signal(
    signal: Signal,
    db: DatabaseManager,
    messaging: Optional[object] = None,
) -> bool:
    """
    Process a validated signal into an order intent.

    Maps the signal to an order intent dict and publishes to NATS
    ``trading.orders`` (if messaging client is available).

    Returns True if the order intent was submitted.
    """
    if signal.side not in ("buy", "sell"):
        logger.warning("Invalid signal side: %s", signal.side)
        return False

    order_intent = {
        "idempotency_key": f"signal-{signal.id or uuid.uuid4().hex[:12]}",
        "symbol": signal.symbol,
        "side": signal.side,
        "order_type": "limit" if signal.entry_price else "market",
        "price": signal.entry_price,
        "stop_loss": signal.stop_loss,
        "take_profit": signal.take_profit,
        "source": signal.source,
        "signal_id": signal.id,
        "confidence": signal.confidence,
    }

    logger.info(
        "Processing signal → order intent: %s %s %s @ %s",
        order_intent["side"],
        order_intent["symbol"],
        order_intent["order_type"],
        order_intent.get("price", "market"),
    )

    if messaging and hasattr(messaging, "publish"):
        await messaging.publish("trading.orders", order_intent)
        logger.info("Published order intent to trading.orders")
    else:
        logger.warning("No messaging client — order intent not published")

    return True
