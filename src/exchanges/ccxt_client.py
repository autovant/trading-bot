"""
CCXT-based exchange client for unified crypto trading.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import ccxt.async_support as ccxt
import pandas as pd
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..config import ExchangeConfig
from ..models import OrderResponse, OrderType, PositionSnapshot, Side

retry_read = retry(
    retry=retry_if_exception_type((ccxt.NetworkError, ccxt.RequestTimeout, ccxt.ExchangeNotAvailable, ccxt.RateLimitExceeded)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True
)

logger = logging.getLogger(__name__)


class CCXTClient:
    """
    Wrapper around CCXT for unified exchange interaction.
    """

    # Quote currencies to try when splitting concatenated symbols like SOLUSDT
    _QUOTE_CURRENCIES = ("USDT", "USDC", "USD", "BUSD", "BTC", "ETH")

    def __init__(self, config: ExchangeConfig):
        self.config = config
        self.exchange_id = config.name.lower()
        self.exchange: Optional[ccxt.Exchange] = None
        self._initialized = False
        self._time_offset_ms = 0
        self._last_time_sync = 0.0

    def _normalize_symbol(self, symbol: str) -> str:
        """Convert concatenated symbols (SOLUSDT) to CCXT format (SOL/USDT).

        If the symbol already contains '/', return as-is.
        Tries the loaded markets first, then splits by known quote currencies.
        For futures, also checks BASE/QUOTE:QUOTE format.
        """
        if "/" in symbol:
            return symbol

        # Check if the raw symbol exists in markets (e.g. some exchanges accept it)
        if self.exchange and symbol in self.exchange.markets:
            return symbol

        # Try to split into BASE/QUOTE
        upper = symbol.upper()
        for quote in self._QUOTE_CURRENCIES:
            if upper.endswith(quote) and len(upper) > len(quote):
                base = upper[: -len(quote)]
                candidate = f"{base}/{quote}"
                # Check spot first
                if self.exchange and candidate in self.exchange.markets:
                    return candidate
                # Check futures (BASE/QUOTE:QUOTE)
                futures_candidate = f"{candidate}:{quote}"
                if self.exchange and futures_candidate in self.exchange.markets:
                    return futures_candidate
                # If exchange not loaded yet, return spot format
                if not self.exchange:
                    return candidate

        # Fallback: return as-is and let CCXT raise if invalid
        return symbol

    @staticmethod
    def _normalize_timeframe(timeframe: str) -> str:
        """Convert bare numeric timeframes to CCXT format.

        '5' → '5m', '60' → '1h', '1440' → '1d', '1h' → '1h' (unchanged).
        """
        # Already contains a unit suffix
        if timeframe and timeframe[-1] in ("m", "h", "d", "w", "M"):
            return timeframe
        # Bare number → treat as minutes
        try:
            minutes = int(timeframe)
        except (ValueError, TypeError):
            return timeframe  # Can't parse, return as-is
        if minutes >= 1440 and minutes % 1440 == 0:
            return f"{minutes // 1440}d"
        if minutes >= 60 and minutes % 60 == 0:
            return f"{minutes // 60}h"
        return f"{minutes}m"

    @property
    def time_offset_ms(self) -> int:
        return self._time_offset_ms

    async def sync_time(self) -> int:
        """
        Synchronize time with the exchange and return the offset in ms.
        Positive offset means exchange time is ahead of local time.
        """
        if not self.exchange:
            return 0
        
        try:
            # fetchTime returns server time in ms
            server_time = await self.exchange.fetch_time()
            local_time = int(datetime.now(timezone.utc).timestamp() * 1000)
            self._time_offset_ms = server_time - local_time
            self._last_time_sync = datetime.now(timezone.utc).timestamp()
            return self._time_offset_ms
        except Exception as e:
            logger.warning(f"Failed to sync time with exchange: {e}")
            return self._time_offset_ms

    async def initialize(self) -> None:
        """Initialize the CCXT exchange instance."""
        if self._initialized:
            return

        exchange_class = getattr(ccxt, self.exchange_id, None)
        if not exchange_class:
            raise ValueError(f"Exchange '{self.exchange_id}' not supported by CCXT")

        exchange_config: Dict[str, Any] = {
            "apiKey": self.config.api_key,
            "secret": self.config.secret_key,
            "enableRateLimit": True,
            "options": {"defaultType": "future"},  # Default to derivatives
        }

        if self.config.testnet:
            exchange_config["options"]["sandbox"] = True
            # Some exchanges need explicit sandbox URL overrides, but CCXT handles most

        self.exchange = exchange_class(exchange_config)

        # Load markets to ensure we can trade
        try:
            await self.exchange.load_markets()
            self._initialized = True
            logger.info(f"Initialized CCXT client for {self.exchange_id}")
        except Exception as e:
            logger.error(f"Failed to initialize CCXT client: {e}")
            await self.close()
            raise

    async def close(self) -> None:
        """Close the exchange connection."""
        if self.exchange:
            await self.exchange.close()
            self.exchange = None
            self._initialized = False

    @retry_read
    async def get_historical_data(
        self, symbol: str, timeframe: str, limit: int = 200
    ) -> Optional[pd.DataFrame]:
        """Fetch OHLCV data."""
        if not self.exchange:
            return None

        symbol = self._normalize_symbol(symbol)
        timeframe = self._normalize_timeframe(timeframe)
        try:
            ohlcv = await self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)

            df = pd.DataFrame(
                ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"]
            )
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            return df
        except Exception as e:
            logger.error(f"Error fetching historical data for {symbol}: {e}")
            return None

    @retry_read
    async def get_ticker(self, symbol: str) -> Optional[Dict]:
        """Fetch current ticker data."""
        if not self.exchange:
            return None

        symbol = self._normalize_symbol(symbol)
        try:
            ticker = await self.exchange.fetch_ticker(symbol)
            return ticker
        except Exception as e:
            logger.error(f"Error fetching ticker for {symbol}: {e}")
            return None

    @retry_read
    async def get_order_book(self, symbol: str, limit: int = 20) -> Optional[Dict]:
        """Fetch order book."""
        if not self.exchange:
            return None

        symbol = self._normalize_symbol(symbol)
        try:
            order_book = await self.exchange.fetch_order_book(symbol, limit)
            return order_book
        except Exception as e:
            logger.error(f"Error fetching order book for {symbol}: {e}")
            return None

    @retry_read
    async def get_balance(self) -> Optional[Dict]:
        """Fetch account balance."""
        if not self.exchange:
            return None

        try:
            balance = await self.exchange.fetch_balance()
            return balance
        except Exception as e:
            logger.error(f"Error fetching balance: {e}")
            return None

    @retry_read
    async def get_positions(
        self, symbols: Optional[List[str]] = None
    ) -> List[PositionSnapshot]:
        """Fetch open positions."""
        if not self.exchange:
            return []

        try:
            # CCXT unified position fetching
            if symbols:
                symbols = [self._normalize_symbol(s) for s in symbols]
            positions = await self.exchange.fetch_positions(symbols)
            snapshots = []

            for pos in positions:
                if float(pos["contracts"]) <= 0:
                    continue

                snapshots.append(
                    PositionSnapshot(
                        symbol=pos["symbol"],
                        side=pos["side"],
                        size=float(pos["contracts"]),
                        entry_price=float(pos["entryPrice"]),
                        mark_price=float(pos["markPrice"] or pos["lastPrice"] or 0),
                        unrealized_pnl=float(pos["unrealizedPnl"] or 0),
                        percentage=float(pos["percentage"] or 0),
                        timestamp=datetime.now(timezone.utc),
                    )
                )
            return snapshots
        except Exception as e:
            logger.error(f"Error fetching positions: {e}")
            return []

    async def place_order(
        self,
        symbol: str,
        side: Side,
        order_type: OrderType,
        quantity: float,
        price: Optional[float] = None,
        stop_price: Optional[float] = None,
        reduce_only: bool = False,
        client_id: Optional[str] = None,
    ) -> Optional[OrderResponse]:
        """Place an order."""
        if not self.exchange:
            return None

        symbol = self._normalize_symbol(symbol)
        try:
            params: Dict[str, Any] = {}
            if reduce_only:
                params["reduceOnly"] = True
            if client_id:
                params["clientOrderId"] = client_id
            if stop_price:
                params["stopPrice"] = stop_price
                # CCXT unified trigger price
                params["triggerPrice"] = stop_price

            order = await self.exchange.create_order(
                symbol=symbol,
                type=order_type,
                side=side,
                amount=quantity,
                price=price,
                params=params,
            )

            return OrderResponse(
                order_id=order["id"],
                client_id=order.get("clientOrderId") or client_id or order["id"],
                symbol=order["symbol"],
                side=order["side"],
                order_type=order["type"],
                quantity=float(order["amount"]),
                price=float(order.get("price") or price or 0.0),
                status=order["status"],
                mode="live",
                timestamp=datetime.now(timezone.utc),
            )

        except Exception as e:
            logger.error(f"Error placing order for {symbol}: {e}")
            raise

    async def load_markets(self) -> Dict[str, Any]:
        if not self.exchange:
            return {}
        return await self.exchange.load_markets()

    async def set_leverage(self, symbol: str, leverage: int) -> None:
        if not self.exchange:
            raise RuntimeError("CCXT exchange not initialized")
        if not hasattr(self.exchange, "set_leverage"):
            logger.warning("Exchange does not support set_leverage via CCXT")
            return
        symbol = self._normalize_symbol(symbol)
        await self.exchange.set_leverage(leverage, symbol)

    @retry_read
    async def cancel_order(
        self, order_id: str, symbol: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        if not self.exchange:
            return None
        if symbol:
            symbol = self._normalize_symbol(symbol)
        try:
            if symbol:
                return await self.exchange.cancel_order(order_id, symbol)
            return await self.exchange.cancel_order(order_id)
        except Exception as e:
            logger.error(f"Error cancelling order {order_id}: {e}")
            raise

    @retry_read
    async def cancel_all_orders(self, symbol: str) -> List[Dict[str, Any]]:
        if not self.exchange:
            return []

        symbol = self._normalize_symbol(symbol)

        if hasattr(self.exchange, "cancel_all_orders"):
            try:
                result = await self.exchange.cancel_all_orders(symbol)
                return result if isinstance(result, list) else [result]
            except Exception as e:
                logger.error(f"Error cancelling all orders for {symbol}: {e}")
                raise

        # Fallback: fetch open orders and cancel individually
        try:
            open_orders = []
            if hasattr(self.exchange, "fetch_open_orders"):
                open_orders = await self.exchange.fetch_open_orders(symbol)
            results: List[Dict[str, Any]] = []
            for order in open_orders or []:
                order_id = order.get("id")
                if not order_id:
                    continue
                results.append(await self.exchange.cancel_order(order_id, symbol))
            return results
        except Exception as e:
            logger.error(f"Error cancelling orders for {symbol}: {e}")
            raise

    @retry_read
    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        if not self.exchange:
            return []
        if not hasattr(self.exchange, "fetch_open_orders"):
            return []
        try:
            if symbol:
                symbol = self._normalize_symbol(symbol)
                return await self.exchange.fetch_open_orders(symbol)
            return await self.exchange.fetch_open_orders()
        except Exception as e:
            logger.error("Error fetching open orders: %s", e)
            return []

    @retry_read
    async def get_my_trades(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        if not self.exchange:
            return []
        if not hasattr(self.exchange, "fetch_my_trades"):
            return []
        try:
            if symbol:
                symbol = self._normalize_symbol(symbol)
                return await self.exchange.fetch_my_trades(symbol)
            return await self.exchange.fetch_my_trades()
        except Exception as e:
            logger.error("Error fetching trades: %s", e)
            return []
