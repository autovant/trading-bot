from typing import Any, Dict, List, Optional, Protocol

from .models import OrderResponse, OrderType, PositionSnapshot, Side


class IExchange(Protocol):
    """
    Protocol defining the standard interface for any exchange implementation
    (Live, Paper, Backtest, etc).
    """

    async def initialize(self) -> None:
        """Initialize the exchange connection."""
        ...

    async def close(self) -> None:
        """Close the exchange connection and cleanup resources."""
        ...

    async def get_balance(self) -> Dict[str, float]:
        """Get account balance."""
        ...

    async def get_positions(
        self, symbols: Optional[List[str]] = None
    ) -> List[PositionSnapshot]:
        """Get current open positions."""
        ...

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
        ...

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        """Cancel a specific order."""
        ...

    async def cancel_all_orders(self, symbol: str) -> List[Dict[str, Any]]:
        """Cancel all open orders for a symbol."""
        ...

    async def close_position(self, symbol: str) -> bool:
        """Close an entire position for a symbol."""
        ...

    async def get_market_status(self) -> Dict[str, Any]:
        """Get general market status/health."""
        ...

    async def get_historical_data(
        self, symbol: str, timeframe: str, limit: int = 200
    ) -> Optional[Any]:
        """Fetch OHLCV data."""
        ...

    async def get_ticker(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch current ticker data."""
        ...

    async def get_order_book(
        self, symbol: str, limit: int = 20
    ) -> Optional[Dict[str, Any]]:
        """Fetch order book."""
        ...

    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch open orders."""
        ...

    async def get_recent_trades(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch recent trades/fills."""
        ...
