from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from .base import AlertSink

logger = logging.getLogger(__name__)


class LoggingAlertSink(AlertSink):
    async def send_alert(
        self, category: str, message: str, context: Optional[Dict[str, Any]] = None
    ) -> None:
        logger.error("ALERT[%s]: %s | context=%s", category, message, context or {})
