"""Main application — orchestrates all components of the copy trading bot."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from typing import Optional

from .client import PolymarketClient
from .config import AppConfig, load_config
from .copy_engine import CopyEngine
from .executor import Executor
from .models import CopiedTrade, CopySignal, SourceTrade, TradeStatus
from .monitor import TradeMonitor
from .persistence import TradeStore
from .risk_manager import RiskManager

logger = logging.getLogger(__name__)


class App:
    """Top-level application that wires together monitor → engine → risk → executor → store."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._client = PolymarketClient(config.polymarket)
        self._monitor = TradeMonitor(config, self._client)
        self._engine = CopyEngine(config)
        self._risk = RiskManager(config.risk)
        self._executor = Executor(self._client, dry_run=config.dry_run)
        self._store = TradeStore(config.database.url)
        self._trade_queue: asyncio.Queue[SourceTrade] = asyncio.Queue()
        self._running = False

    async def start(self) -> None:
        """Initialise all components and start the main loop."""
        self._setup_logging()
        logger.info("=" * 60)
        logger.info("Polymarket Copy Trading Bot starting")
        logger.info("  Dry run: %s", self._config.dry_run)
        logger.info("  Source wallets: %d", len(self._config.source_wallets))
        logger.info("  Sizing mode: %s", self._config.copy.sizing_mode)
        logger.info("  Poll interval: %ds", self._config.poll_interval_seconds)
        logger.info("=" * 60)

        if not self._config.source_wallets:
            logger.error("No source wallets configured — nothing to monitor")
            sys.exit(1)

        await self._client.start()
        await self._store.start()

        # Wire monitor callback to push into the async queue
        self._monitor.on_trade(lambda t: self._trade_queue.put_nowait(t))

        self._running = True
        await asyncio.gather(
            self._monitor.start(),
            self._process_loop(),
        )

    async def stop(self) -> None:
        """Gracefully shut down all components."""
        logger.info("Shutting down…")
        self._running = False
        self._monitor.stop()
        await self._client.stop()
        await self._store.stop()
        logger.info("Shutdown complete")

    async def _process_loop(self) -> None:
        """Consume trades from the queue and process them through the pipeline."""
        while self._running:
            try:
                trade = await asyncio.wait_for(self._trade_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            try:
                await self._process_trade(trade)
            except Exception:
                logger.exception("Failed to process trade %s", trade.trade_id)

    async def _process_trade(self, source: SourceTrade) -> None:
        """Run a single source trade through the copy pipeline."""
        # 1. Generate copy signal
        signal_obj: Optional[CopySignal] = self._engine.process(source)
        if signal_obj is None:
            logger.debug("Trade %s filtered out by copy engine", source.trade_id)
            return

        # 2. Risk check
        risk_result = self._risk.check(signal_obj)
        if not risk_result.allowed:
            logger.info("Trade %s rejected by risk manager: %s", source.trade_id, risk_result.reason)
            skipped = CopiedTrade(
                source_trade_id=source.trade_id,
                source_wallet=source.wallet,
                market_id=source.market_id,
                asset_id=source.asset_id,
                side=signal_obj.target_side,
                price=signal_obj.target_price,
                size=signal_obj.target_size,
                status=TradeStatus.SKIPPED,
                error=risk_result.reason,
            )
            await self._store.save_trade(skipped)
            return

        # 3. Execute
        result = await self._executor.execute(signal_obj, adjusted_size=risk_result.adjusted_size)

        # 4. Update risk state
        if result.status == TradeStatus.FILLED:
            self._risk.record_fill(
                asset_id=source.asset_id,
                side=result.side.value,
                size=result.fill_size or result.size,
                price=result.fill_price or result.price,
                market_id=source.market_id,
            )

        # 5. Persist
        await self._store.save_trade(result)

    def _setup_logging(self) -> None:
        """Configure logging based on app config."""
        logging.basicConfig(
            level=getattr(logging, self._config.logging.level.upper(), logging.INFO),
            format=self._config.logging.format,
        )


def run(config_path: Optional[str] = None) -> None:
    """Entry point — load config and run the bot."""
    config = load_config(config_path)
    app = App(config)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _shutdown(sig, frame):
        loop.create_task(app.stop())

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        loop.run_until_complete(app.start())
    except KeyboardInterrupt:
        loop.run_until_complete(app.stop())
    finally:
        loop.close()
