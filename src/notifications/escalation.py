"""
Alert Escalation Engine.

Manages severity lifecycle for alarms:
  INFO → WARNING → CRITICAL → AUTO_SHUTDOWN

Unacknowledged WARNINGs escalate to CRITICAL after a configurable timer.
CRITICAL triggers agent pause + all-channel notification.
AUTO_SHUTDOWN triggers the kill switch.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Callable, Coroutine, Dict, List, Optional

logger = logging.getLogger(__name__)


class Severity(IntEnum):
    INFO = 0
    WARNING = 1
    CRITICAL = 2
    AUTO_SHUTDOWN = 3


@dataclass
class Alarm:
    """An individual alarm instance."""

    alarm_id: str
    title: str
    message: str
    severity: Severity
    source: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    acknowledged: bool = False
    acknowledged_at: Optional[float] = None
    acknowledged_by: Optional[str] = None
    escalation_count: int = 0


class AlertEscalator:
    """
    Manages alarm lifecycle with timer-based escalation.

    Parameters
    ----------
    escalation_delay_seconds : float
        Seconds before an unacknowledged WARNING escalates to CRITICAL (default 900 = 15min).
    on_critical : callable
        Async callback when an alarm reaches CRITICAL severity.
        Signature: ``async (alarm: Alarm) -> None``
    on_shutdown : callable
        Async callback when an alarm reaches AUTO_SHUTDOWN severity.
        Signature: ``async (alarm: Alarm) -> None``
    """

    def __init__(
        self,
        escalation_delay_seconds: float = 900.0,
        on_critical: Optional[Callable[[Alarm], Coroutine[Any, Any, None]]] = None,
        on_shutdown: Optional[Callable[[Alarm], Coroutine[Any, Any, None]]] = None,
    ):
        self.escalation_delay = escalation_delay_seconds
        self.on_critical = on_critical
        self.on_shutdown = on_shutdown
        self._alarms: Dict[str, Alarm] = {}
        self._escalation_tasks: Dict[str, asyncio.Task[None]] = {}
        self._running = False

    @property
    def active_alarms(self) -> List[Alarm]:
        return [a for a in self._alarms.values() if not a.acknowledged]

    def get_alarm(self, alarm_id: str) -> Optional[Alarm]:
        return self._alarms.get(alarm_id)

    def list_alarms(self, include_acknowledged: bool = False) -> List[Alarm]:
        if include_acknowledged:
            return list(self._alarms.values())
        return self.active_alarms

    async def raise_alarm(
        self,
        alarm_id: str,
        title: str,
        message: str,
        severity: Severity = Severity.WARNING,
        source: str = "",
    ) -> Alarm:
        """
        Raise or update an alarm.

        If the alarm already exists and is unacknowledged, its severity
        is updated to the higher of old / new.
        """
        existing = self._alarms.get(alarm_id)
        if existing and not existing.acknowledged:
            # Escalate to higher severity
            if severity > existing.severity:
                existing.severity = severity
                existing.message = message
                existing.updated_at = time.time()
                existing.escalation_count += 1
                logger.warning("Alarm %s escalated to %s", alarm_id, severity.name)
                await self._handle_severity(existing)
            return existing

        alarm = Alarm(
            alarm_id=alarm_id,
            title=title,
            message=message,
            severity=severity,
            source=source,
        )
        self._alarms[alarm_id] = alarm
        logger.info("Alarm raised: %s [%s] %s", alarm_id, severity.name, title)

        await self._handle_severity(alarm)

        # Start escalation timer for WARNING
        if severity == Severity.WARNING:
            self._start_escalation_timer(alarm_id)

        return alarm

    async def acknowledge(self, alarm_id: str, by: str = "user") -> bool:
        """Acknowledge an alarm, stopping its escalation timer."""
        alarm = self._alarms.get(alarm_id)
        if not alarm or alarm.acknowledged:
            return False

        alarm.acknowledged = True
        alarm.acknowledged_at = time.time()
        alarm.acknowledged_by = by
        alarm.updated_at = time.time()

        # Cancel escalation timer
        task = self._escalation_tasks.pop(alarm_id, None)
        if task and not task.done():
            task.cancel()

        logger.info("Alarm %s acknowledged by %s", alarm_id, by)
        return True

    async def _handle_severity(self, alarm: Alarm) -> None:
        """Invoke callbacks based on severity level."""
        if alarm.severity >= Severity.CRITICAL and self.on_critical:
            try:
                await self.on_critical(alarm)
            except Exception as e:
                logger.error("on_critical callback failed: %s", e)

        if alarm.severity >= Severity.AUTO_SHUTDOWN and self.on_shutdown:
            try:
                await self.on_shutdown(alarm)
            except Exception as e:
                logger.error("on_shutdown callback failed: %s", e)

    def _start_escalation_timer(self, alarm_id: str) -> None:
        """Schedule automatic escalation from WARNING → CRITICAL."""
        # Cancel existing timer if any
        existing = self._escalation_tasks.pop(alarm_id, None)
        if existing and not existing.done():
            existing.cancel()

        async def _escalate() -> None:
            await asyncio.sleep(self.escalation_delay)
            alarm = self._alarms.get(alarm_id)
            if alarm and not alarm.acknowledged and alarm.severity == Severity.WARNING:
                logger.warning(
                    "Alarm %s unacknowledged for %.0fs — escalating to CRITICAL",
                    alarm_id,
                    self.escalation_delay,
                )
                alarm.severity = Severity.CRITICAL
                alarm.updated_at = time.time()
                alarm.escalation_count += 1
                await self._handle_severity(alarm)

        self._escalation_tasks[alarm_id] = asyncio.create_task(_escalate())

    async def shutdown(self) -> None:
        """Cancel all escalation timers."""
        for task in self._escalation_tasks.values():
            if not task.done():
                task.cancel()
        self._escalation_tasks.clear()
