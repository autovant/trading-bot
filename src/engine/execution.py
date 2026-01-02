import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from src.config import TradingBotConfig
from src.database import DatabaseManager, Order, OrderIntent
from src.exchange import IExchange
from src.engine.order_intent_ledger import OrderIntentLedger
from src.messaging import MessagingClient
from src.models import (
    ConfidenceScore,
    MarketRegime,
    OrderResponse,
    OrderType,
    Side,
    TradingSignal,
)
from src.position_manager import PositionManager
from src.risk_manager import RiskManager

logger = logging.getLogger(__name__)


class ExecutionEngine:
    """
    Handles trade execution logic:
    - Order calculation (position sizing)
    - Order placement (exchange interaction)
    - Ladder entries
    - Stop loss / Take profit placement
    - Messaging system notifications
    """

    def __init__(
        self,
        config: TradingBotConfig,
        exchange: IExchange,
        database: DatabaseManager,
        messaging: Optional[MessagingClient],
        position_manager: PositionManager,
        risk_manager: RiskManager,
        run_id: str,
        mode: str,
    ):
        self.config = config
        self.exchange = exchange
        self.database = database
        self.messaging = messaging
        self.position_manager = position_manager
        self.risk_manager = risk_manager
        self.run_id = run_id
        self.mode = mode
        self.pending_orders: List[OrderResponse] = []
        self.intent_ledger = OrderIntentLedger(
            database=database, mode=mode, run_id=run_id
        )
        self.reconciliation_block_active = False
        self._last_reconcile_at: Optional[datetime] = None

    def _generate_client_id(self, symbol: str) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%H%M%S%f")
        return f"{self.run_id}-{symbol}-{timestamp}"

    def _direction_to_side(self, direction: str) -> Side:
        return "buy" if direction.lower() in ("long", "buy") else "sell"

    async def _record_order_ack(self, response: OrderResponse) -> None:
        if self.mode != "live":
            return
        order = Order(
            client_id=response.client_id,
            order_id=response.order_id,
            symbol=response.symbol,
            side=response.side,
            order_type=response.order_type,
            quantity=response.quantity,
            price=response.price,
            status=response.status,
            created_at=response.timestamp,
            mode=self.mode,
            run_id=self.run_id,
        )
        await self.database.create_order(order)

    async def place_order_directly(
        self,
        *,
        symbol: str,
        side: Side,
        order_type: OrderType,
        quantity: float,
        price: Optional[float] = None,
        stop_price: Optional[float] = None,
        reduce_only: bool = False,
        client_id: Optional[str] = None,
        is_shadow: bool = False,
        idempotency_key: Optional[str] = None,
    ) -> Optional[OrderResponse]:
        if self.reconciliation_block_active:
            logger.warning(
                "SAFETY_RECON_BLOCK: Order placement blocked for %s due to reconciliation guard",
                symbol,
            )
            return None

        if not idempotency_key:
            logger.error(
                "SAFETY_IDEMPOTENCY: Missing idempotency key for %s; refusing submit",
                symbol,
            )
            return None

        intent = await self._ensure_intent(
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            stop_price=stop_price,
            reduce_only=reduce_only,
            client_id=client_id,
            idempotency_key=idempotency_key,
        )
        if intent is None:
            return None

        if OrderIntentLedger.is_terminal(intent.status):
            logger.info(
                "Intent %s already terminal (%s); skipping submit",
                intent.idempotency_key,
                intent.status,
            )
            return None

        if intent.status not in ("created", "failed"):
            logger.info(
                "Intent %s already exists with status=%s; reconciling instead of re-submitting",
                intent.idempotency_key,
                intent.status,
            )
            await self._reconcile_all_intents(reason="idempotency_check")
            return None

        try:
            response = await self.exchange.place_order(
                symbol=symbol,
                side=side,
                order_type=order_type,
                quantity=quantity,
                price=price,
                stop_price=stop_price,
                reduce_only=reduce_only,
                client_id=intent.client_id,
                is_shadow=is_shadow,
            )
            if response:
                await self._record_order_ack(response)
                self.pending_orders.append(response)
                intent.order_id = response.order_id
                await self.intent_ledger.update_intent_status(
                    intent,
                    status="acked",
                    order_id=response.order_id,
                    last_error=None,
                )
            return response
        except Exception as exc:
            ambiguous = _is_ambiguous_submit_error(exc)
            status = "submitted" if ambiguous else "failed"
            await self.intent_ledger.update_intent_status(
                intent,
                status=status,
                last_error=str(exc),
            )
            logger.error("Error placing order for %s: %s", symbol, exc)
            return None

    async def execute_signal(
        self,
        symbol: str,
        signal: TradingSignal,
        confidence: ConfidenceScore,
        regime: MarketRegime,
        current_equity: float,
        initial_capital: float,
        vwap_val: Optional[float] = None,
        ob_metrics: Optional[Dict[str, Any]] = None,
    ):
        """Execute a trading signal with full risk check and ladder logic."""
        try:
            # Calculate position size
            position_size = self.position_manager.calculate_position_size(
                signal,
                confidence,
                current_equity,
                initial_capital,
                self.config,
                self.risk_manager.crisis_mode,
            )
            if position_size <= 0:
                logger.info(f"Position size is zero, skipping {symbol}")
                return

            side = self._direction_to_side(signal.direction)
            if signal.timestamp is None:
                logger.error(
                    "SAFETY_IDEMPOTENCY: Missing signal timestamp for %s; refusing submit",
                    symbol,
                )
                return
            idempotency_key = self._build_idempotency_key(
                symbol=symbol,
                side=side,
                order_type="limit",
                quantity=position_size,
                price=signal.entry_price,
                stop_price=signal.stop_loss,
                reduce_only=False,
                intent_timestamp=signal.timestamp,
            )
            client_id = OrderIntentLedger.client_id_from_key(
                idempotency_key, self.run_id
            )

            # Publish order intent
            if self.messaging:
                order_data = {
                    "id": client_id,
                    "symbol": symbol,
                    "type": "limit",
                    "side": side,
                    "price": signal.entry_price,
                    "quantity": position_size,
                    "timestamp": datetime.now().isoformat(),
                }

                context = {
                    "confidence_score": confidence.total_score,
                    "signal_type": signal.signal_type,
                    "regime": regime.regime,
                    "vwap": vwap_val,
                }
                if ob_metrics:
                    context["orderbook_imbalance"] = ob_metrics.get("imbalance")
                    context["spread"] = ob_metrics.get("spread")

                await self.messaging.publish(
                    self.config.messaging.subjects["orders"],
                    {
                        "type": "new_order",
                        "order": order_data,
                        "strategy_context": context,
                    },
                )

            # Execution
            order_response = await self.place_order_directly(
                symbol=symbol,
                side=side,
                order_type="limit",
                quantity=position_size,
                price=signal.entry_price,
                client_id=client_id,
                idempotency_key=idempotency_key,
            )

            if order_response:
                logger.info(
                    "Placed order %s for %s: %s %.4f @ %.2f",
                    order_response.order_id,
                    symbol,
                    side,
                    position_size,
                    signal.entry_price,
                )
                await self.set_stop_losses(
                    symbol,
                    side,
                    signal,
                    position_size,
                    current_equity,
                    parent_intent_key=idempotency_key,
                )

                # We can't update positions here directly as that's state management.
                # Strategy should call update_position after execution.

        except Exception as e:
            logger.error(f"Error executing signal for {symbol}: {e}")

    async def reconcile_startup(self) -> None:
        """Reconcile intents against exchange truth on startup."""
        await self._reconcile_all_intents(reason="startup")

    async def reconcile_periodic(self, interval_seconds: int = 60) -> None:
        now = datetime.now(timezone.utc)
        if self._last_reconcile_at:
            elapsed = (now - self._last_reconcile_at).total_seconds()
            if elapsed < interval_seconds:
                return
        await self._reconcile_all_intents(reason="periodic")
        self._last_reconcile_at = now

    async def _reconcile_all_intents(self, *, reason: str) -> None:
        intents = await self.database.list_open_order_intents(self.mode, self.run_id)
        if not intents:
            return
        open_orders = await self._fetch_open_orders()
        trades = await self._fetch_recent_trades()

        open_by_order_id, open_by_client_id = _index_open_orders(open_orders)
        unknown_open_orders = []

        for intent in intents:
            await self._reconcile_intent(
                intent,
                open_by_order_id=open_by_order_id,
                open_by_client_id=open_by_client_id,
                trades=trades,
            )

        for client_id in open_by_client_id:
            if not any(intent.client_id == client_id for intent in intents):
                unknown_open_orders.append(client_id)

        if unknown_open_orders:
            self.reconciliation_block_active = True
            logger.error(
                "SAFETY_RECON_BLOCK: Unknown open orders detected (%s) during %s",
                ", ".join(unknown_open_orders),
                reason,
            )

    async def _reconcile_intent(
        self,
        intent: OrderIntent,
        *,
        open_by_order_id: Optional[Dict[str, Any]] = None,
        open_by_client_id: Optional[Dict[str, Any]] = None,
        trades: Optional[List[Any]] = None,
    ) -> None:
        if OrderIntentLedger.is_terminal(intent.status):
            return

        open_by_order_id = open_by_order_id or {}
        open_by_client_id = open_by_client_id or {}
        trades = trades or []

        open_order = None
        if intent.order_id:
            open_order = open_by_order_id.get(intent.order_id)
        if not open_order:
            open_order = open_by_client_id.get(intent.client_id)

        if open_order:
            if intent.status in ("created", "submitted", "failed"):
                await self.intent_ledger.update_intent_status(
                    intent,
                    status="acked",
                    order_id=intent.order_id or _extract_order_id(open_order),
                )
            return

        matched_trades = _match_trades(intent, trades)
        if matched_trades:
            await self._apply_trades_to_intent(intent, matched_trades)
            return

        if intent.status in ("submitted", "created"):
            await self.intent_ledger.update_intent_status(
                intent,
                status="failed",
                last_error=intent.last_error or "no_exchange_ack",
            )

    async def _apply_trades_to_intent(
        self, intent: OrderIntent, trades: List[Any]
    ) -> None:
        total_qty, avg_price = _aggregate_trades(trades)
        for trade in trades:
            trade_id = _extract_trade_id(trade)
            if not trade_id:
                continue
            await self.intent_ledger.record_fill(
                intent=intent,
                trade_id=trade_id,
                order_id=_extract_trade_order_id(trade),
                symbol=_extract_trade_symbol(trade, intent.symbol),
                side=_extract_trade_side(trade, intent.side),
                quantity=_extract_trade_qty(trade),
                price=_extract_trade_price(trade),
                fee=_extract_trade_fee(trade),
                timestamp=_extract_trade_time(trade),
            )

        status = "filled" if total_qty >= intent.quantity else "partially_filled"
        await self.intent_ledger.update_intent_status(
            intent,
            status=status,
            filled_qty=total_qty,
            avg_fill_price=avg_price,
        )
        if intent.order_id:
            await self.database.update_order_status(intent.order_id, status)

    async def _ensure_intent(
        self,
        *,
        symbol: str,
        side: Side,
        order_type: OrderType,
        quantity: float,
        price: Optional[float],
        stop_price: Optional[float],
        reduce_only: bool,
        client_id: Optional[str],
        idempotency_key: Optional[str],
    ) -> Optional[OrderIntent]:
        if not idempotency_key:
            logger.error(
                "SAFETY_IDEMPOTENCY: Missing idempotency key for %s; refusing intent",
                symbol,
            )
            return None
        intent_key = idempotency_key
        derived_client_id = client_id or OrderIntentLedger.client_id_from_key(
            intent_key, self.run_id
        )
        intent, _ = await self.intent_ledger.get_or_create_intent(
            idempotency_key=intent_key,
            client_id=derived_client_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            stop_price=stop_price,
            reduce_only=reduce_only,
        )
        return intent

    def _build_idempotency_key(
        self,
        *,
        symbol: str,
        side: Side,
        order_type: OrderType,
        quantity: float,
        price: Optional[float],
        stop_price: Optional[float],
        reduce_only: bool,
        intent_timestamp: Optional[datetime],
    ) -> str:
        timestamp = intent_timestamp or datetime.now(timezone.utc)
        payload = {
            "run_id": self.run_id,
            "symbol": symbol,
            "side": side,
            "order_type": order_type,
            "quantity": round(quantity, 8),
            "price": round(price, 8) if price is not None else None,
            "stop_price": round(stop_price, 8) if stop_price is not None else None,
            "reduce_only": reduce_only,
            "intent_ts": timestamp.isoformat(),
        }
        return OrderIntentLedger.build_idempotency_key(payload)

    async def _fetch_open_orders(self) -> List[Any]:
        if hasattr(self.exchange, "get_open_orders"):
            return await self.exchange.get_open_orders()
        return []

    async def _fetch_recent_trades(self) -> List[Any]:
        if hasattr(self.exchange, "get_recent_trades"):
            return await self.exchange.get_recent_trades()
        return []

    async def set_stop_losses(
        self,
        symbol: str,
        side: Side,
        signal: TradingSignal,
        position_size: float,
        current_equity: float,
        *,
        parent_intent_key: str,
    ):
        """Set dual stop loss system."""
        try:
            # maximize allowable loss based on config hard risk %
            max_loss = (
                current_equity * self.config.risk_management.stops.hard_risk_percent
            )

            hard_stop_price = signal.entry_price
            if side == "buy":
                # For long, price going down is loss
                # Loss = (Entry - Stop) * Size = Max_Loss
                # Entry - Stop = Max_Loss / Size
                # Stop = Entry - (Max_Loss / Size)
                hard_stop_price -= max_loss / position_size
            else:
                # For short, price going up is loss
                # Loss = (Stop - Entry) * Size
                # Stop - Entry = Max_Loss / Size
                # Stop = Entry + (Max_Loss / Size)
                hard_stop_price += max_loss / position_size

            stop_payload = {
                "symbol": symbol,
                "side": "sell" if side == "buy" else "buy",
                "order_type": "stop_market",
                "quantity": round(position_size, 8),
                "stop_price": round(hard_stop_price, 8),
                "reduce_only": True,
            }
            stop_key = OrderIntentLedger.build_child_idempotency_key(
                parent_intent_key, "stop_loss", stop_payload
            )
            stop_client_id = OrderIntentLedger.client_id_from_key(
                stop_key, self.run_id
            )

            # Place hard stop order
            stop_order = await self.place_order_directly(
                symbol=symbol,
                side="sell" if side == "buy" else "buy",
                order_type="stop_market",
                quantity=position_size,
                stop_price=hard_stop_price,
                reduce_only=True,
                client_id=stop_client_id,
                idempotency_key=stop_key,
            )

            if stop_order:
                logger.info(f"Set hard stop for {symbol} at {hard_stop_price:.2f}")

        except Exception as e:
            logger.error(f"Error setting stops for {symbol}: {e}")


def _is_ambiguous_submit_error(exc: Exception) -> bool:
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return True
    return "timeout" in str(exc).lower()


def _extract_order_id(order: Any) -> Optional[str]:
    if isinstance(order, dict):
        return (
            order.get("id")
            or order.get("order_id")
            or order.get("orderId")
            or order.get("orderID")
        )
    return getattr(order, "order_id", None) or getattr(order, "id", None)


def _extract_client_id(order: Any) -> Optional[str]:
    if isinstance(order, dict):
        return (
            order.get("clientOrderId")
            or order.get("client_order_id")
            or order.get("client_id")
            or order.get("orderLinkId")
        )
    return getattr(order, "client_id", None) or getattr(order, "clientOrderId", None)


def _index_open_orders(open_orders: List[Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    by_order_id: Dict[str, Any] = {}
    by_client_id: Dict[str, Any] = {}
    for order in open_orders or []:
        order_id = _extract_order_id(order)
        client_id = _extract_client_id(order)
        if order_id:
            by_order_id[order_id] = order
        if client_id:
            by_client_id[client_id] = order
    return by_order_id, by_client_id


def _match_trades(intent: OrderIntent, trades: List[Any]) -> List[Any]:
    matched: List[Any] = []
    for trade in trades:
        trade_order_id = _extract_trade_order_id(trade)
        trade_client_id = _extract_trade_client_id(trade)
        if intent.order_id and trade_order_id == intent.order_id:
            matched.append(trade)
        elif trade_client_id and trade_client_id == intent.client_id:
            matched.append(trade)
    return matched


def _aggregate_trades(trades: List[Any]) -> Tuple[float, Optional[float]]:
    total_qty = 0.0
    total_cost = 0.0
    for trade in trades:
        qty = _extract_trade_qty(trade)
        price = _extract_trade_price(trade)
        total_qty += qty
        total_cost += qty * price
    avg_price = (total_cost / total_qty) if total_qty else None
    return total_qty, avg_price


def _extract_trade_order_id(trade: Any) -> Optional[str]:
    if isinstance(trade, dict):
        return (
            trade.get("order")
            or trade.get("orderId")
            or trade.get("order_id")
            or trade.get("orderID")
        )
    return getattr(trade, "order_id", None) or getattr(trade, "order", None)


def _extract_trade_client_id(trade: Any) -> Optional[str]:
    if isinstance(trade, dict):
        return trade.get("clientOrderId") or trade.get("orderLinkId")
    return getattr(trade, "client_id", None)


def _extract_trade_id(trade: Any) -> Optional[str]:
    if isinstance(trade, dict):
        return trade.get("id") or trade.get("trade_id") or trade.get("tradeId")
    return getattr(trade, "trade_id", None) or getattr(trade, "id", None)


def _extract_trade_symbol(trade: Any, fallback: str) -> str:
    if isinstance(trade, dict):
        return trade.get("symbol") or fallback
    return getattr(trade, "symbol", fallback)


def _extract_trade_side(trade: Any, fallback: str) -> str:
    if isinstance(trade, dict):
        return trade.get("side") or fallback
    return getattr(trade, "side", fallback)


def _extract_trade_qty(trade: Any) -> float:
    if isinstance(trade, dict):
        return float(
            trade.get("amount")
            or trade.get("qty")
            or trade.get("quantity")
            or 0.0
        )
    return float(getattr(trade, "quantity", 0.0))


def _extract_trade_price(trade: Any) -> float:
    if isinstance(trade, dict):
        return float(trade.get("price") or 0.0)
    return float(getattr(trade, "price", 0.0))


def _extract_trade_fee(trade: Any) -> float:
    if isinstance(trade, dict):
        fee = trade.get("fee") or {}
        if isinstance(fee, dict):
            return float(fee.get("cost") or 0.0)
        return float(fee or 0.0)
    return float(getattr(trade, "commission", 0.0))


def _extract_trade_time(trade: Any) -> Optional[datetime]:
    if isinstance(trade, dict):
        ts = trade.get("timestamp")
        if ts:
            return datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
        return None
    return getattr(trade, "timestamp", None)
