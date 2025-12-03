from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

class ExchangeAdapter(ABC):
    """
    Abstract base class for exchange adapters.
    Defines the standard interface for connecting to and interacting with exchanges.
    """

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the exchange."""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection to the exchange."""
        pass

    @abstractmethod
    async def get_ticker(self, symbol: str) -> Dict[str, Any]:
        """Get current ticker information for a symbol."""
        pass

    @abstractmethod
    async def get_balance(self, asset: str) -> float:
        """Get the available balance of a specific asset."""
        pass

    @abstractmethod
    async def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        qty: float,
        price: Optional[float] = None,
        reduce_only: bool = False
    ) -> Dict[str, Any]:
        """Place a new order."""
        pass

    @abstractmethod
    async def cancel_order(self, symbol: str, order_id: str) -> Dict[str, Any]:
        """Cancel an existing order."""
        pass

    @abstractmethod
    async def get_positions(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get current open positions."""
        pass
