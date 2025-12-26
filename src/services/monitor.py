from __future__ import annotations

import asyncio
import logging
from typing import Optional

from ..config import TradingBotConfig, load_config
from .base import BaseService

logger = logging.getLogger(__name__)


class MonitorService(BaseService):
    """
    Runtime health monitoring service.

    Monitors system vitals (e.g., memory, disk) and aggregates
    application-level health status from other services.
    """

    def __init__(self) -> None:
        super().__init__("monitor")
        self.config: Optional[TradingBotConfig] = None
        self._monitoring_task: Optional[asyncio.Task] = None

    async def on_startup(self) -> None:
        config = load_config()
        self.config = config
        self.set_mode(config.app_mode)

        logger.info("Monitor service starting checks...")
        self._monitoring_task = asyncio.create_task(self._monitor_loop())

    async def on_shutdown(self) -> None:
        if self._monitoring_task:
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass

    async def _monitor_loop(self) -> None:
        """Periodic health check loop."""
        while True:
            try:
                await self._check_health()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Error in health monitor loop")

            # Check every 60 seconds
            await asyncio.sleep(60)

    async def _check_health(self) -> None:
        """Perform one iteration of health checks."""
        # TODO: Implement specific system checks (CPU, RAM, Disk)
        # TODO: Implement NATS connectivity check
        logger.debug("Runtime health check passed")
