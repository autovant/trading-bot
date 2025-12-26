"""
Real-time market data feed using CCXT.

This service fetches live ticker and order book data from the configured exchange
and publishes it to NATS for the strategy and execution services.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI

from ..config import TradingBotConfig, load_config
from ..exchanges.ccxt_client import CCXTClient
from ..messaging import MessagingClient
from .base import BaseService, create_app

logger = logging.getLogger(__name__)


class FeedService(BaseService):
    """Background market-data publisher using CCXT."""

    def __init__(self) -> None:
        super().__init__("feed")
        self.config: Optional[TradingBotConfig] = None
        self.messaging: Optional[MessagingClient] = None
        self.exchange_client: Optional[CCXTClient] = None
        self._task: Optional[asyncio.Task] = None

    async def on_startup(self) -> None:
        self.config = load_config()
        self.set_mode(self.config.app_mode)

        self.messaging = MessagingClient({"servers": self.config.messaging.servers})
        await self.messaging.connect()

        # Initialize CCXT client
        # For feed, we might want to use a public client (no keys) if possible,
        # but using the configured credentials ensures higher rate limits.
        self.exchange_client = CCXTClient(self.config.exchange)
        await self.exchange_client.initialize()

        self._task = asyncio.create_task(self._run())

    async def on_shutdown(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        if self.exchange_client:
            await self.exchange_client.close()
            self.exchange_client = None

        if self.messaging:
            await self.messaging.close()
            self.messaging = None

    async def _run(self) -> None:
        if (
            self.config is None
            or self.messaging is None
            or self.exchange_client is None
        ):
            raise RuntimeError("FeedService started before initialisation")

        symbols = self.config.trading.symbols
        subject = self.config.messaging.subjects["market_data"]

        logger.info(f"Starting feed for symbols: {symbols}")

        while True:
            try:
                # Fetch data for all symbols concurrently
                tasks = [self._fetch_and_publish(symbol, subject) for symbol in symbols]
                await asyncio.gather(*tasks, return_exceptions=True)

                # Rate limit compliance (simple sleep for now)
                await asyncio.sleep(1.0)

            except Exception as e:
                logger.error(f"Error in feed loop: {e}")
                await asyncio.sleep(5.0)

    async def _fetch_and_publish(self, symbol: str, subject: str) -> None:
        try:
            exchange_client = self.exchange_client
            messaging = self.messaging
            if exchange_client is None or messaging is None:
                raise RuntimeError("FeedService started before initialisation")

            ticker = await exchange_client.get_ticker(symbol)
            if not ticker:
                return

            # Construct snapshot compatible with existing consumers
            # Ticker structure from CCXT:
            # {'symbol': 'BTC/USDT', 'timestamp': 123, 'datetime': '...', 'high': ..., 'low': ...,
            #  'bid': ..., 'bidVolume': ..., 'ask': ..., 'askVolume': ..., ...}

            best_bid = ticker.get("bid")
            best_ask = ticker.get("ask")
            last_price = ticker.get("last")

            if best_bid is None or best_ask is None or last_price is None:
                return

            # Estimate spread
            spread = best_ask - best_bid

            snapshot = {
                "symbol": symbol,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "bid_size": ticker.get("bidVolume", 0.0),
                "ask_size": ticker.get("askVolume", 0.0),
                "spread": spread,
                "last_price": last_price,
                "last_side": "buy",  # inferred or unavailable in simple ticker
                "last_size": 0.0,  # unavailable in simple ticker
                "funding_rate": 0.0,  # would need separate call
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "order_flow_imbalance": 0.0,  # requires L2 book
            }

            await messaging.publish(subject, snapshot)

        except Exception as e:
            logger.warning(f"Failed to fetch/publish for {symbol}: {e}")


service = FeedService()
app: FastAPI = create_app(service)
