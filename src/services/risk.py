"""
Risk state publisher implemented with FastAPI.

Emits synthetic risk metrics at a fixed cadence to keep downstream
consumers (strategy, dashboard) informed even in paper environments.
"""

from __future__ import annotations

import asyncio
import math
import random
from datetime import datetime
from typing import Optional

from fastapi import FastAPI

from ..config import TradingBotConfig, load_config
from ..messaging import MessagingClient
from .base import BaseService, create_app


class RiskService(BaseService):
    """Synthetic risk-state publisher."""

    def __init__(self) -> None:
        super().__init__("risk")
        self.config: Optional[TradingBotConfig] = None
        self.messaging: Optional[MessagingClient] = None
        self._task: Optional[asyncio.Task] = None
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
        subject = self.config.messaging.subjects["risk"]

        consecutive_losses = 0
        crisis = False

        while True:
            drawdown = abs(math.sin(datetime.utcnow().timestamp())) * 0.2
            volatility = random.random()
            position_factor = 1 - random.random() * 0.3

            if random.random() < 0.05:
                crisis = not crisis
                if crisis:
                    consecutive_losses += 1

            payload = {
                "crisis_mode": crisis,
                "consecutive_losses": consecutive_losses,
                "drawdown": drawdown,
                "volatility": volatility,
                "position_size_factor": position_factor,
                "timestamp": datetime.utcnow().isoformat(),
            }

            await self.messaging.publish(subject, payload)
            await asyncio.sleep(5.0)


service = RiskService()
app: FastAPI = create_app(service)
