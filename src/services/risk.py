"""
Risk state publisher implemented with FastAPI.

Emits synthetic risk metrics at a fixed cadence to keep downstream
consumers (strategy, dashboard) informed even in paper environments.
"""

from __future__ import annotations

import asyncio
import logging
import math
import random
from datetime import datetime
from typing import Optional

from fastapi import FastAPI

from ..config import TradingBotConfig, load_config
from ..database import DatabaseManager
from ..metrics import CIRCUIT_BREAKERS
from ..messaging import MessagingClient
from .base import BaseService, create_app

logger = logging.getLogger(__name__)


class RiskService(BaseService):
    """Synthetic risk-state publisher."""

    def __init__(self) -> None:
        super().__init__("risk")
        self.config: Optional[TradingBotConfig] = None
        self.messaging: Optional[MessagingClient] = None
        self._task: Optional[asyncio.Task] = None
        self.database: Optional[DatabaseManager] = None
        self._run_id: Optional[str] = None
        random.seed()

    async def on_startup(self) -> None:
        self.config = load_config()
        self.set_mode(self.config.app_mode)

        self.database = DatabaseManager(self.config.database.path)
        await self.database.initialize()
        self._run_id = f"{self.name}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"

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

        if self.database:
            await self.database.close()
            self.database = None

    async def _run(self) -> None:
        assert self.config and self.messaging
        subject = self.config.messaging.subjects["risk"]

        consecutive_losses = 0
        crisis = False

        while True:
            drawdown = abs(math.sin(datetime.utcnow().timestamp())) * 0.2
            volatility = random.random()
            position_factor = 1 - random.random() * 0.3

            previous_crisis = crisis
            if random.random() < 0.05:
                crisis = not crisis
                if crisis:
                    consecutive_losses += 1
            if crisis and not previous_crisis and self.config:
                CIRCUIT_BREAKERS.labels(mode=self.config.app_mode).inc()
            payload = {
                "crisis_mode": crisis,
                "consecutive_losses": consecutive_losses,
                "drawdown": drawdown,
                "volatility": volatility,
                "position_size_factor": position_factor,
                "timestamp": datetime.utcnow().isoformat(),
            }

            await self.messaging.publish(subject, payload)

            if self.database and self._run_id:
                try:
                    await self.database.record_risk_snapshot(
                        payload, mode=self.config.app_mode, run_id=self._run_id
                    )
                except Exception as exc:  # pragma: no cover - defensive logging
                    logger.error("Failed to persist risk snapshot: %s", exc)

            await asyncio.sleep(5.0)


service = RiskService()
app: FastAPI = create_app(service)
