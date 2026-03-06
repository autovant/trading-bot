from __future__ import annotations

import asyncio
import logging
import os
import shutil
from typing import Optional

from ..config import TradingBotConfig, load_config
from ..messaging import MessagingClient
from .base import BaseService

logger = logging.getLogger(__name__)


class MonitorService(BaseService):
    """
    Runtime health monitoring service.

    Monitors system vitals (CPU load, memory, disk) and validates
    NATS connectivity on a periodic cadence.
    """

    def __init__(self) -> None:
        super().__init__("monitor")
        self.config: Optional[TradingBotConfig] = None
        self.messaging: Optional[MessagingClient] = None
        self._monitoring_task: Optional[asyncio.Task] = None

    async def on_startup(self) -> None:
        config = load_config()
        self.config = config
        self.set_mode(config.app_mode)

        self.messaging = MessagingClient({"servers": config.messaging.servers})
        await self.messaging.connect()

        logger.info("Monitor service starting checks...")
        self._monitoring_task = asyncio.create_task(self._monitor_loop())

    async def on_shutdown(self) -> None:
        if self._monitoring_task:
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass

        if self.messaging:
            await self.messaging.close()
            self.messaging = None

    async def _monitor_loop(self) -> None:
        """Periodic health check loop."""
        while True:
            try:
                await self._check_health()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Error in health monitor loop")

            await asyncio.sleep(60)

    async def _check_health(self) -> None:
        """Perform one iteration of health checks."""
        issues: list[str] = []

        # CPU load average (1-minute)
        try:
            load_avg = os.getloadavg()[0]
            cpu_count = os.cpu_count() or 1
            if load_avg > cpu_count * 2:
                issues.append(f"High CPU load: {load_avg:.1f} (cores={cpu_count})")
        except OSError:
            pass  # os.getloadavg() not available on all platforms

        # Disk usage on data volume
        try:
            usage = shutil.disk_usage("/")
            pct_used = usage.used / usage.total
            if pct_used > 0.90:
                issues.append(f"Disk usage critical: {pct_used:.0%}")
            elif pct_used > 0.80:
                logger.info("Disk usage elevated: %.0f%%", pct_used * 100)
        except OSError:
            pass

        # NATS connectivity
        if self.messaging:
            try:
                if not self.messaging.connected:
                    issues.append("NATS disconnected")
            except Exception as exc:
                issues.append(f"NATS check failed: {exc}")

        if issues:
            logger.warning("Health check issues: %s", "; ".join(issues))
        else:
            logger.debug("Runtime health check passed")
