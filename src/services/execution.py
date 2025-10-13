"""
Execution service implemented with FastAPI.

The service consumes order intents from NATS, forwards them to the
``PaperBroker`` for simulation, and publishes execution reports.  It
also ingests market data snapshots to keep the broker's view of the
order book current.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import FastAPI
from nats.aio.msg import Msg
from nats.aio.subscription import Subscription
from prometheus_client import Counter, Histogram

from ..config import TradingBotConfig, load_config
from ..database import DatabaseManager
from ..messaging import MessagingClient
from ..paper_trader import MarketSnapshot, PaperBroker
from .base import BaseService, create_app

logger = logging.getLogger(__name__)

ORDER_ACCEPTED = Counter(
    "execution_orders_total",
    "Total number of order intents processed",
    ["status"],
)

FILL_LATENCY = Histogram(
    "execution_fill_latency_seconds",
    "Latency between order receipt and fill completion",
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0),
)


class ExecutionService(BaseService):
    """Paper execution adapter running as a FastAPI service."""

    def __init__(self) -> None:
        super().__init__("execution")
        self.config: Optional[TradingBotConfig] = None
        self.database: Optional[DatabaseManager] = None
        self.messaging: Optional[MessagingClient] = None
        self.broker: Optional[PaperBroker] = None
        self._subscriptions: List[Subscription] = []

    async def on_startup(self) -> None:
        self.config = load_config()
        self.set_mode(self.config.app_mode)

        self.database = DatabaseManager(self.config.database.path)
        await self.database.initialize()

        self.messaging = MessagingClient({"servers": self.config.messaging.servers})
        await self.messaging.connect()

        self.broker = PaperBroker(
            config=self.config.paper,
            database=self.database,
            mode=self.config.app_mode,
            run_id=f"exec-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            initial_balance=self.config.trading.initial_capital,
            execution_listener=self._publish_execution_report,
        )

        orders_subject = self.config.messaging.subjects["orders"]
        market_subject = self.config.messaging.subjects["market_data"]

        order_sub = await self.messaging.subscribe(orders_subject, self._handle_order)
        market_sub = await self.messaging.subscribe(
            market_subject, self._handle_market_data
        )
        if order_sub:
            self._subscriptions.append(order_sub)
        if market_sub:
            self._subscriptions.append(market_sub)

    async def on_shutdown(self) -> None:
        for sub in self._subscriptions:
            try:
                await sub.unsubscribe()
            except Exception:
                logger.exception("Failed to unsubscribe from %s", sub.subject)
        self._subscriptions.clear()

        if self.messaging:
            await self.messaging.close()
        if self.database:
            await self.database.close()

        self.messaging = None
        self.database = None
        self.broker = None

    async def _publish_execution_report(self, report: Dict[str, Any]) -> None:
        """Publish a simulated fill report."""
        if not self.messaging or not self.config:
            return

        try:
            subject = (
                self.config.messaging.subjects["executions_shadow"]
                if report.get("is_shadow")
                else self.config.messaging.subjects["executions"]
            )
            await self.messaging.publish(subject, report)

            latency = report.get("latency_ms")
            if latency is not None:
                FILL_LATENCY.observe(float(latency) / 1000.0)
        except Exception:
            logger.exception("Failed to publish execution report")

    async def _handle_order(self, msg: Msg) -> None:
        if not self.broker or not self.messaging or not self.config:
            logger.warning("Execution service not fully initialised; dropping order")
            return

        try:
            payload = json.loads(msg.data.decode("utf-8"))
        except json.JSONDecodeError:
            logger.error("Received invalid order payload: %s", msg.data)
            ORDER_ACCEPTED.labels(status="invalid").inc()
            return

        try:
            order = await self.broker.place_order(
                symbol=payload["symbol"],
                side=payload["side"],
                order_type=payload.get("type", "market"),
                quantity=float(payload["quantity"]),
                price=payload.get("price"),
                stop_price=payload.get("stop_price"),
                reduce_only=payload.get("reduce_only", False),
                is_shadow=payload.get("is_shadow", False),
                client_id=payload.get("client_id"),
            )

            ORDER_ACCEPTED.labels(status="accepted").inc()

            acknowledgement = {
                "order_id": order.order_id or order.client_id,
                "client_id": order.client_id,
                "symbol": order.symbol,
                "executed": False,
                "mode": self.config.app_mode,
                "run_id": self.broker.run_id if self.broker else "",
                "timestamp": datetime.utcnow().isoformat(),
                "order_type": order.order_type,
                "stop_price": order.stop_price,
                "price": order.price,
                "quantity": order.quantity,
                "is_shadow": payload.get("is_shadow", False),
            }

            await self.messaging.publish(
                self.config.messaging.subjects["executions"], acknowledgement
            )
        except Exception as exc:
            ORDER_ACCEPTED.labels(status="rejected").inc()
            logger.exception("Failed to process order: %s", exc)
            await self.messaging.publish(
                self.config.messaging.subjects["executions"],
                {
                    "order_id": payload.get("client_id"),
                    "client_id": payload.get("client_id"),
                    "symbol": payload.get("symbol"),
                    "executed": False,
                    "error": str(exc),
                    "timestamp": datetime.utcnow().isoformat(),
                    "mode": self.config.app_mode if self.config else "paper",
                },
            )

    async def _handle_market_data(self, msg: Msg) -> None:
        if not self.broker:
            return

        try:
            data = json.loads(msg.data.decode("utf-8"))
            timestamp = data.get("timestamp")
            if timestamp:
                try:
                    ts = datetime.fromisoformat(timestamp)
                except ValueError:
                    ts = datetime.utcnow()
            else:
                ts = datetime.utcnow()

            snapshot = MarketSnapshot(
                symbol=data["symbol"],
                best_bid=float(data.get("best_bid", 0.0)),
                best_ask=float(data.get("best_ask", 0.0)),
                bid_size=float(data.get("bid_size", 0.0)),
                ask_size=float(data.get("ask_size", 0.0)),
                last_price=float(data.get("last_price", 0.0)),
                last_side=data.get("last_side"),
                last_size=float(data.get("last_size", 0.0)),
                funding_rate=float(data.get("funding_rate", 0.0)),
                timestamp=ts,
                order_flow_imbalance=float(data.get("order_flow_imbalance", 0.0)),
            )
        except Exception:
            logger.exception("Invalid market data payload: %s", msg.data)
            return

        await self.broker.update_market(snapshot)


service = ExecutionService()
app: FastAPI = create_app(service)
