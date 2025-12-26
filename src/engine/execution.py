import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.config import TradingBotConfig
from src.database import DatabaseManager, Order
from src.exchange import IExchange
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
    ) -> Optional[OrderResponse]:
        try:
            response = await self.exchange.place_order(
                symbol=symbol,
                side=side,
                order_type=order_type,
                quantity=quantity,
                price=price,
                stop_price=stop_price,
                reduce_only=reduce_only,
                client_id=client_id,
                is_shadow=is_shadow,
            )
            if response:
                await self._record_order_ack(response)
                self.pending_orders.append(response)
            return response
        except Exception as exc:
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

            client_id = self._generate_client_id(symbol)
            side = self._direction_to_side(signal.direction)

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
                    symbol, side, signal, position_size, current_equity
                )

                # We can't update positions here directly as that's state management.
                # Strategy should call update_position after execution.

        except Exception as e:
            logger.error(f"Error executing signal for {symbol}: {e}")

    async def set_stop_losses(
        self,
        symbol: str,
        side: Side,
        signal: TradingSignal,
        position_size: float,
        current_equity: float,
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

            # Place hard stop order
            stop_order = await self.place_order_directly(
                symbol=symbol,
                side="sell" if side == "buy" else "buy",
                order_type="stop_market",
                quantity=position_size,
                stop_price=hard_stop_price,
                reduce_only=True,
                client_id=self._generate_client_id(symbol),
            )

            if stop_order:
                logger.info(f"Set hard stop for {symbol} at {hard_stop_price:.2f}")

        except Exception as e:
            logger.error(f"Error setting stops for {symbol}: {e}")
