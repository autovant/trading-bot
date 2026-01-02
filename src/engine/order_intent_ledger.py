from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Optional, Tuple

from src.database import (
    DatabaseManager,
    OrderFill,
    OrderIntent,
    OrderIntentEvent,
)

logger = logging.getLogger(__name__)

TERMINAL_INTENT_STATUSES = {"filled", "canceled", "failed"}


def _normalize_price(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), 8)


def _normalize_qty(value: float) -> float:
    return round(float(value), 8)


class OrderIntentLedger:
    """Persistent ledger for order intents and lifecycle events."""

    def __init__(self, database: DatabaseManager, *, mode: str, run_id: str) -> None:
        self.database = database
        self.mode = mode
        self.run_id = run_id

    @staticmethod
    def build_idempotency_key(payload: dict) -> str:
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    @staticmethod
    def build_child_idempotency_key(
        parent_key: str, child_type: str, payload: dict
    ) -> str:
        canonical = {
            "parent": parent_key,
            "child_type": child_type,
            "payload": payload,
        }
        return OrderIntentLedger.build_idempotency_key(canonical)

    @staticmethod
    def client_id_from_key(idempotency_key: str, run_id: str) -> str:
        return f"{run_id}-{idempotency_key[:24]}"

    async def get_intent(self, idempotency_key: str) -> Optional[OrderIntent]:
        return await self.database.get_order_intent(idempotency_key)

    async def create_intent(
        self,
        *,
        idempotency_key: str,
        client_id: str,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        price: Optional[float],
        stop_price: Optional[float],
        reduce_only: bool,
        status: str = "created",
    ) -> OrderIntent:
        intent = OrderIntent(
            idempotency_key=idempotency_key,
            client_id=client_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=_normalize_qty(quantity),
            price=_normalize_price(price),
            stop_price=_normalize_price(stop_price),
            reduce_only=reduce_only,
            status=status,
            mode=self.mode,
            run_id=self.run_id,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await self.database.create_order_intent(intent)
        await self.record_event(idempotency_key, status, None)
        return intent

    async def get_or_create_intent(
        self,
        *,
        idempotency_key: str,
        client_id: str,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        price: Optional[float],
        stop_price: Optional[float],
        reduce_only: bool,
    ) -> Tuple[OrderIntent, bool]:
        existing = await self.database.get_order_intent(idempotency_key)
        if existing:
            return existing, False
        created = await self.create_intent(
            idempotency_key=idempotency_key,
            client_id=client_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            stop_price=stop_price,
            reduce_only=reduce_only,
        )
        return created, True

    async def record_event(
        self, idempotency_key: str, status: str, details: Optional[str]
    ) -> None:
        event = OrderIntentEvent(
            idempotency_key=idempotency_key,
            status=status,
            details=details,
            created_at=datetime.now(timezone.utc),
        )
        await self.database.create_order_intent_event(event)

    async def update_intent_status(
        self,
        intent: OrderIntent,
        *,
        status: str,
        order_id: Optional[str] = None,
        filled_qty: Optional[float] = None,
        avg_fill_price: Optional[float] = None,
        last_error: Optional[str] = None,
    ) -> None:
        intent.status = status
        if order_id is not None:
            intent.order_id = order_id
        if filled_qty is not None:
            intent.filled_qty = filled_qty
        if avg_fill_price is not None:
            intent.avg_fill_price = avg_fill_price
        if last_error is not None:
            intent.last_error = last_error
        await self.database.update_order_intent(intent)
        await self.record_event(intent.idempotency_key, status, last_error)

    async def record_fill(
        self,
        *,
        intent: OrderIntent,
        trade_id: str,
        order_id: Optional[str],
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        fee: float = 0.0,
        timestamp: Optional[datetime] = None,
    ) -> None:
        fill = OrderFill(
            idempotency_key=intent.idempotency_key,
            trade_id=trade_id,
            order_id=order_id,
            symbol=symbol,
            side=side,
            quantity=_normalize_qty(quantity),
            price=_normalize_price(price) or 0.0,
            fee=fee,
            timestamp=timestamp or datetime.now(timezone.utc),
        )
        await self.database.create_order_fill(fill)

    @staticmethod
    def is_terminal(status: str) -> bool:
        return status.lower() in TERMINAL_INTENT_STATUSES

