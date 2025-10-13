"""
Synthetic market data feed implemented with FastAPI.

This service generates plausible best bid/ask snapshots and publishes
them to NATS so that the execution service (PaperBroker) receives a
steady stream of updates even when no live exchange connection is
available.
"""

from __future__ import annotations

import asyncio
import math
import random
from datetime import datetime, timezone
from typing import Dict, Optional

from fastapi import FastAPI

from ..config import TradingBotConfig, load_config
from ..metrics import SPREAD_ATR_PCT
from ..messaging import MessagingClient
from .base import BaseService, create_app


class FeedService(BaseService):
    """Background mock market-data publisher."""

    def __init__(self) -> None:
        super().__init__("feed")
        self.config: Optional[TradingBotConfig] = None
        self.messaging: Optional[MessagingClient] = None
        self._task: Optional[asyncio.Task] = None
        self._last_price: Dict[str, float] = {}
        self._atr: Dict[str, float] = {}
        random.seed()

    async def on_startup(self) -> None:
        self.config = load_config()
        self.set_mode(self.config.app_mode)

        self.messaging = MessagingClient({"servers": self.config.messaging.servers})
        await self.messaging.connect()

        self._task = asyncio.create_task(self._run())

    async def on_shutdown(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        if self.messaging:
            await self.messaging.close()
            self.messaging = None

    async def _run(self) -> None:
        assert self.config and self.messaging

        symbols = self.config.trading.symbols
        subject = self.config.messaging.subjects["market_data"]

        while True:
            for symbol in symbols:
                snapshot = self._generate_snapshot(symbol)
                await self.messaging.publish(subject, snapshot)
            await asyncio.sleep(1.0)

    def _generate_snapshot(self, symbol: str) -> Dict[str, float | str]:
        last_price = self._last_price.get(symbol, 50_000.0)
        drift = random.gauss(0, 25)
        price = max(1_000.0, last_price + drift)

        spread = max(price * 0.0004, 2.0)
        atr = self._atr.get(symbol, spread)
        atr = atr * 0.85 + spread * 0.15

        best_bid = price - spread / 2
        best_ask = price + spread / 2

        bid_size = 50 + random.random() * 50
        ask_size = 50 + random.random() * 50
        last_side = "buy" if price >= last_price else "sell"
        last_size = (bid_size + ask_size) * 0.25
        funding = 0.0001 * math.sin(datetime.now(timezone.utc).timestamp())
        ofi = (bid_size - ask_size) * spread

        mode = self.config.app_mode if self.config else "paper"
        SPREAD_ATR_PCT.labels(mode=mode, symbol=symbol).set(
            (spread / max(atr, 1.0)) * 100
        )
        self._last_price[symbol] = price
        self._atr[symbol] = atr

        return {
            "symbol": symbol,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "bid_size": bid_size,
            "ask_size": ask_size,
            "last_price": price,
            "last_side": last_side,
            "last_size": last_size,
            "funding_rate": funding,
            "timestamp": datetime.utcnow().isoformat(),
            "order_flow_imbalance": ofi,
        }


service = FeedService()
app: FastAPI = create_app(service)
