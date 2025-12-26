import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..config import ExchangeConfig
from ..interfaces import IExchange
from ..models import OrderResponse, OrderType, PositionSnapshot, Side
from .ccxt_client import CCXTClient

logger = logging.getLogger(__name__)


class LiveExchange(IExchange):
    """
    Live trading exchange implementation using CCXT.
    """

    def __init__(self, config: ExchangeConfig):
        self.config = config
        self.ccxt_client = CCXTClient(config)

    async def initialize(self) -> None:
        """Initialize the exchange connection."""
        await self.ccxt_client.initialize()
        logger.info(f"LiveExchange initialized for {self.config.name}")

    async def close(self) -> None:
        """Close the exchange connection."""
        await self.ccxt_client.close()

    async def get_balance(self) -> Dict[str, float]:
        """Get account balance."""
        balance = await self.ccxt_client.get_balance()
        if not balance:
            return {}
        # Convert CCXT balance to simple dict if needed, or return as is depending on contract
        # Standardize to {currency: total} or similar if protocol demands,
        # but for now returning raw CCXT balance which usually has 'total', 'free', 'used'
        return balance

    async def get_positions(
        self, symbols: Optional[List[str]] = None
    ) -> List[PositionSnapshot]:
        """Get current open positions."""
        return await self.ccxt_client.get_positions(symbols)

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
        """Place a new order."""
        if is_shadow:
            logger.warning("Shadow orders not supported in LiveExchange (yet)")
            return None

        # Delegate to CCXT
        return await self.ccxt_client.place_order(
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            stop_price=stop_price,
            reduce_only=reduce_only,
            client_id=client_id,
        )

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        """Cancel a specific order."""
        res = await self.ccxt_client.cancel_order(order_id, symbol)
        return bool(res)

    async def cancel_all_orders(self, symbol: str) -> List[Dict[str, Any]]:
        """Cancel all open orders for a symbol."""
        return await self.ccxt_client.cancel_all_orders(symbol)

    async def close_position(self, symbol: str) -> bool:
        """Close an entire position for a symbol."""
        # Check current position first
        positions = await self.get_positions([symbol])
        if not positions:
            return False

        pos = positions[0]
        if pos.size == 0:
            return False

        # Place opposite order to close
        side: Side = "sell" if pos.side == "buy" else "buy"

        try:
            await self.place_order(
                symbol=symbol,
                side=side,
                order_type="market",
                quantity=abs(pos.size),
                reduce_only=True,
            )
            return True
        except Exception as e:
            logger.error(f"Error closing position for {symbol}: {e}")
            return False

    async def get_market_status(self) -> Dict[str, Any]:
        """Get general market status/health."""
        return {
            "status": "online",
            "mode": "live",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # Additional data methods that might be needed by Strategy but strictly aren't part of IExchange execution protocol?
    # Strategy currently calls exchange.get_historical_data.
    # We should probably expose that on IExchange or a separate IMarketData.
    # For now, LiveExchange can expose it.

    async def get_historical_data(self, symbol: str, timeframe: str, limit: int = 200):
        return await self.ccxt_client.get_historical_data(symbol, timeframe, limit)

    async def get_ticker(self, symbol: str) -> Optional[Dict[str, Any]]:
        return await self.ccxt_client.get_ticker(symbol)

    async def get_order_book(
        self, symbol: str, limit: int = 20
    ) -> Optional[Dict[str, Any]]:
        return await self.ccxt_client.get_order_book(symbol, limit)
