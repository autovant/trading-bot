from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import aiohttp

from .base import AlertSink

logger = logging.getLogger(__name__)


class WebhookAlertSink(AlertSink):
    def __init__(self, url: str) -> None:
        self.url = url

    async def send_alert(
        self, category: str, message: str, context: Optional[Dict[str, Any]] = None
    ) -> None:
        payload = {
            "category": category,
            "message": message,
            "context": context or {},
        }
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(self.url, json=payload) as resp:
                    if resp.status >= 300:
                        body = await resp.text()
                        logger.warning(
                            "Webhook alert failed status=%s body=%s", resp.status, body
                        )
        except Exception as exc:
            logger.warning("Webhook alert delivery failed: %s", exc)
