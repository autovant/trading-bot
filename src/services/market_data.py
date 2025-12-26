import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from src.config import TradingBotConfig
from src.exchange import ExchangeClient
from src.messaging import MessagingClient

logger = logging.getLogger(__name__)


class MarketDataPublisher:
    def __init__(
        self,
        config: TradingBotConfig,
        exchange: ExchangeClient,
        messaging: MessagingClient,
    ):
        self.config = config
        self.exchange = exchange
        self.messaging = messaging
        self.running = False
        self.task: Optional[asyncio.Task] = None
        self.symbol = config.trading.symbols[0]

    async def start(self):
        if self.running:
            return
        self.running = True
        self.task = asyncio.create_task(self._run_loop())
        logger.info("Market data publisher started")

    async def stop(self):
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        logger.info("Market data publisher stopped")

    async def _run_loop(self):
        while self.running:
            try:
                # Fetch ticker
                ticker = await self.exchange.get_ticker(self.symbol)
                if ticker:
                    order_book_data = {
                        "symbol": self.symbol,
                        "best_bid": float(ticker.get("bid", 0.0) or 0.0),
                        "best_ask": float(ticker.get("ask", 0.0) or 0.0),
                        "bid_size": float(ticker.get("bidVolume", 0.0) or 0.0),
                        "ask_size": float(ticker.get("askVolume", 0.0) or 0.0),
                        "last_price": float(ticker.get("last", 0.0) or 0.0),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }

                    await self.messaging.publish("market.data", order_book_data)

                await asyncio.sleep(1.0)
            except Exception as e:
                logger.error(f"Error in market data publisher: {e}")
                await asyncio.sleep(5.0)
