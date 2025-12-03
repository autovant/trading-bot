import asyncio
import logging
from typing import Awaitable, Callable, Dict, Optional

from src.domain.entities import MarketData, Order
from src.domain.interfaces import IDataFeed, IExecutionEngine, IStrategy

logger = logging.getLogger(__name__)

Publisher = Callable[[dict], Awaitable[None]]


class StrategyManager:
    def __init__(
        self,
        execution_engine: IExecutionEngine,
        data_feed: Optional[IDataFeed] = None,
        publisher: Optional[Publisher] = None,
    ):
        self.execution_engine = execution_engine
        self.data_feed = data_feed
        self.publisher = publisher
        self.strategies: Dict[str, IStrategy] = {}
        self.enabled: Dict[str, bool] = {}
        self.running = False

    def register_strategy(self, name: str, strategy: IStrategy):
        if name in self.strategies:
            raise ValueError(f"Strategy {name} already registered")
        self.strategies[name] = strategy
        self.enabled[name] = True
        logger.info("Registered strategy: %s", name)

    def set_enabled(self, name: str, enabled: bool):
        if name not in self.strategies:
            raise KeyError(f"Strategy {name} not found")
        self.enabled[name] = enabled
        logger.info("%s %s", name, "enabled" if enabled else "disabled")

    async def start(self):
        self.running = True
        logger.info("Strategy Manager started")
        if self.data_feed:
            await self.data_feed.subscribe(list(self.strategies.keys()))

    async def stop(self):
        self.running = False
        logger.info("Strategy Manager stopped")

    async def on_market_data(self, data: MarketData):
        if not self.running:
            return

        for name, strategy in self.strategies.items():
            if not self.enabled.get(name, True):
                continue
            try:
                orders = await strategy.on_tick(data) or []
                for order in orders:
                    order.metadata.setdefault("strategy", name)
                    order.metadata.setdefault("tick_price", data.close)
                    await self.execution_engine.submit_order(order)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Strategy %s failed on tick: %s", name, exc)

        if self.publisher:
            equity = None
            positions = []
            try:
                equity = self.execution_engine.mark_to_market(
                    {data.symbol: data.close}, data.timestamp
                )
                positions = [p.dict() for p in await self.execution_engine.get_positions()]
            except Exception:
                logger.exception("Failed to mark-to-market after tick")

            snapshot = {
                "type": "tick",
                "symbol": data.symbol,
                "price": data.close,
                "timestamp": data.timestamp.isoformat(),
                "equity": equity,
                "pnl": (equity - getattr(self.execution_engine, "initial_capital", 0))
                if equity is not None
                else None,
                "positions": positions,
                "strategies": self.status(),
            }
            await self.publisher(snapshot)

    async def execute_order(self, order: Order):
        await self.execution_engine.submit_order(order)

    def status(self) -> Dict[str, bool]:
        return dict(self.enabled)
