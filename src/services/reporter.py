"""
Reporter service implemented with FastAPI.

Consumes strategy performance metrics from NATS and periodically emits
summary reports for downstream monitoring dashboards.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Optional

from fastapi import FastAPI
from nats.aio.msg import Msg
from nats.aio.subscription import Subscription

from ..config import TradingBotConfig, load_config
from ..messaging import MessagingClient
from .base import BaseService, create_app


class ReporterService(BaseService):
    """Performance metrics aggregator."""

    def __init__(self) -> None:
        super().__init__("reporter")
        self.config: Optional[TradingBotConfig] = None
        self.messaging: Optional[MessagingClient] = None
        self._summary_task: Optional[asyncio.Task[None]] = None
        self._subscription: Optional[Subscription] = None
        self._latest_metrics: Optional[dict] = None

    async def on_startup(self) -> None:
        self.config = load_config()
        self.set_mode(self.config.app_mode)

        self.messaging = MessagingClient({"servers": self.config.messaging.servers})
        await self.messaging.connect()

        subject = self.config.messaging.subjects["performance"]
        self._subscription = await self.messaging.subscribe(
            subject, self._handle_metrics
        )
        self._summary_task = asyncio.create_task(self._publish_summary_loop())

    async def on_shutdown(self) -> None:
        if self._subscription:
            await self._subscription.unsubscribe()
            self._subscription = None

        if self._summary_task:
            self._summary_task.cancel()
            try:
                await self._summary_task
            except asyncio.CancelledError:
                pass
            self._summary_task = None

        if self.messaging:
            await self.messaging.close()
            self.messaging = None

        self._latest_metrics = None

    async def _handle_metrics(self, msg: Msg) -> None:
        try:
            self._latest_metrics = json.loads(msg.data.decode("utf-8"))
        except json.JSONDecodeError:
            self._latest_metrics = None

    async def _publish_summary_loop(self) -> None:
        assert self.config and self.messaging
        subject = self.config.messaging.subjects.get("reports", "reports.performance")

        while True:
            if self._latest_metrics:
                summary = dict(self._latest_metrics)
                summary.setdefault("timestamp", datetime.utcnow().isoformat())
                await self.messaging.publish(subject, summary)
            await asyncio.sleep(60.0)


service = ReporterService()
app: FastAPI = create_app(service)
