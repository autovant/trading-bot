from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class AlertSink(ABC):
    @abstractmethod
    async def send_alert(
        self, category: str, message: str, context: Optional[Dict[str, Any]] = None
    ) -> None: ...
