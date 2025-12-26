import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..config import ExchangeConfig
from ..interfaces import IExchange
from ..models import OrderResponse, OrderType, PositionSnapshot, Side
from ..paper_trader import PaperBroker
from .ccxt_client import CCXTClient

logger = logging.getLogger(__name__)


class PaperExchange(IExchange):
    """
    Paper trading exchange implementation using PaperBroker for execution
    and CCXT for market data.
    """

    def __init__(self, config: ExchangeConfig, paper_broker: PaperBroker):
        self.config = config
        self.paper_broker = paper_broker
        # We still use CCXT for data fetching even in paper mode
        self.ccxt_client = CCXTClient(config)

    async def initialize(self) -> None:
        """Initialize the exchange connection."""
        # Initialize data source
        try:
            await self.ccxt_client.initialize()
        except Exception as e:
            logger.warning(f"Failed to initialize CCXT for paper data: {e}")

        logger.info(f"PaperExchange initialized for {self.config.name}")

    async def close(self) -> None:
        """Close the exchange connection."""
        if self.ccxt_client:
            await self.ccxt_client.close()

    async def get_balance(self) -> Dict[str, float]:
        """Get account balance from paper broker."""
        return await self.paper_broker.get_account_balance()

    async def get_positions(
        self, symbols: Optional[List[str]] = None
    ) -> List[PositionSnapshot]:
        """Get current open positions from paper broker."""
        return await self.paper_broker.get_positions(symbols)

    async def place_order(
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
        """Place a new order via paper broker."""
        return await self.paper_broker.place_order(
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

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        """Cancel a specific order."""
        try:
            res = await self.paper_broker.cancel_order(order_id, symbol)
            return bool(res)
        except Exception:
            return False

    async def cancel_all_orders(self, symbol: str) -> List[Dict[str, Any]]:
        """Cancel all open orders for a symbol."""
        return await self.paper_broker.cancel_all_orders(symbol)

    async def close_position(self, symbol: str) -> bool:
        """Close an entire position for a symbol."""
        return await self.paper_broker.close_position(symbol)

    async def get_market_status(self) -> Dict[str, Any]:
        """Get general market status/health."""
        return {
            "status": "active",
            "mode": "paper",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # Data delegation
    async def get_historical_data(self, symbol: str, timeframe: str, limit: int = 200):
        if not self.ccxt_client:
            return None
        return await self.ccxt_client.get_historical_data(symbol, timeframe, limit)

    async def get_ticker(self, symbol: str) -> Optional[Dict[str, Any]]:
        if not self.ccxt_client:
            return None
        return await self.ccxt_client.get_ticker(symbol)

    async def get_order_book(
        self, symbol: str, limit: int = 20
    ) -> Optional[Dict[str, Any]]:
        if not self.ccxt_client:
            return None
        return await self.ccxt_client.get_order_book(symbol, limit)
