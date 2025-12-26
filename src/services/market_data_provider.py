import logging
from typing import Any, Dict, Optional

import pandas as pd

from ..exchange import IExchange

logger = logging.getLogger(__name__)


class MarketDataProvider:
    """
    Service responsible for fetching and processing market data.
    Decouples strategy from direct exchange interaction for data.
    """

    def __init__(self, exchange: IExchange):
        self.exchange = exchange

    async def get_ohlcv(
        self, symbol: str, timeframe: str, limit: int = 200
    ) -> Optional[pd.DataFrame]:
        """
        Fetch OHLCV data.
        """
        # In a real scenario, this could check transparency/cache/tick database first
        return await self.exchange.get_historical_data(symbol, timeframe, limit)

    async def get_ticker(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Fetch current ticker information.
        """
        # If exchange interface doesn't strictly have get_ticker, we might need to cast or expand IExchange
        # For now, we assume the underlying exchange implementation supports it or we add it to IExchange
        # Inspecting CCXTClient/LiveExchange - they have get_ticker.
        # But IExchange protocol in src/interfaces.py might not have it.
        # Let's check if the concrete implementation has it, if not return None or raise.

        if hasattr(self.exchange, "ccxt_client"):
            return await self.exchange.ccxt_client.get_ticker(symbol)

        # If it's a pure IExchange without that attribute exposed or defined
        # We might need to rely on 'get_market_status' or similar, but for now let's assume direct usage
        # or that we will add get_ticker to IExchange in a moment.
        return None

    async def get_order_book(
        self, symbol: str, limit: int = 20
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch order book data.
        """
        if hasattr(self.exchange, "ccxt_client"):
            return await self.exchange.ccxt_client.get_order_book(symbol, limit)
        return None
