"""
CCXT-based exchange client for unified crypto trading.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import ccxt.async_support as ccxt
import pandas as pd

from ..config import ExchangeConfig
from ..models import OrderResponse, OrderType, PositionSnapshot, Side
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

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

    def __init__(self, config: ExchangeConfig):
        self.config = config
        self.exchange_id = config.name.lower()
        self.exchange: Optional[ccxt.Exchange] = None
        self._initialized = False

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
        await self.exchange.set_leverage(leverage, symbol)

    @retry_read
    async def cancel_order(
        self, order_id: str, symbol: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        if not self.exchange:
            return None
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
