from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from .base import AlertSink
from .logging_sink import LoggingAlertSink
from .webhook_sink import WebhookAlertSink


class AlertManager(AlertSink):
    def __init__(self, sinks: Optional[List[AlertSink]] = None) -> None:
        self.sinks = sinks or self._default_sinks()

    @staticmethod
    def _default_sinks() -> List[AlertSink]:
        sinks: List[AlertSink] = [LoggingAlertSink()]
        webhook_url = os.getenv("ALERT_WEBHOOK_URL")
        if webhook_url:
            sinks.append(WebhookAlertSink(webhook_url))
        return sinks

    async def send_alert(
        self, category: str, message: str, context: Optional[Dict[str, Any]] = None
    ) -> None:
        for sink in self.sinks:
            await sink.send_alert(category, message, context)
