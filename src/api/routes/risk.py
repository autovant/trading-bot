"""
Risk Management API routes — kill switch, limits, alarms.

- GET  /api/risk/status        — current risk status and limits
- PUT  /api/risk/limits        — update risk limits
- POST /api/risk/kill-switch   — emergency: cancel all, flatten, pause agents
- GET  /api/risk/alarms        — list active alarms
- POST /api/risk/alarms/{id}/ack — acknowledge an alarm
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.database import DatabaseManager
from src.notifications.escalation import AlertEscalator, Severity

logger = logging.getLogger(__name__)

risk_router = APIRouter(tags=["risk"])

# In-memory risk state (could be persisted if needed)
_risk_state: Dict[str, Any] = {
    "kill_switch_active": False,
    "kill_switch_activated_at": None,
    "limits": {
        "max_total_exposure_usd": 100_000,
        "max_per_agent_exposure_usd": 20_000,
        "max_symbol_concentration": 0.30,
        "max_daily_loss_usd": 5_000,
        "max_correlation": 0.70,
    },
}

# Shared escalator instance (initialized in app startup)
_escalator: Optional[AlertEscalator] = None


def set_escalator(esc: AlertEscalator) -> None:
    global _escalator
    _escalator = esc


# Dependencies — overridden at app startup
async def get_db() -> DatabaseManager:
    raise NotImplementedError


async def get_messaging():
    raise NotImplementedError


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class RiskLimitsUpdate(BaseModel):
    max_total_exposure_usd: Optional[float] = None
    max_per_agent_exposure_usd: Optional[float] = None
    max_symbol_concentration: Optional[float] = None
    max_daily_loss_usd: Optional[float] = None
    max_correlation: Optional[float] = None


class KillSwitchResponse(BaseModel):
    status: str
    activated_at: str
    actions: List[str]


class AlarmResponse(BaseModel):
    alarm_id: str
    title: str
    message: str
    severity: str
    source: str
    created_at: float
    acknowledged: bool
    acknowledged_by: Optional[str] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@risk_router.get("/api/risk/status")
async def risk_status():
    """Get current risk status including kill switch state and limits."""
    return {
        "kill_switch_active": _risk_state["kill_switch_active"],
        "kill_switch_activated_at": _risk_state["kill_switch_activated_at"],
        "limits": _risk_state["limits"],
        "active_alarms": len(_escalator.active_alarms) if _escalator else 0,
    }


@risk_router.put("/api/risk/limits")
async def update_risk_limits(update: RiskLimitsUpdate):
    """Update risk management limits."""
    limits = _risk_state["limits"]
    for key, value in update.model_dump(exclude_none=True).items():
        if key in limits:
            limits[key] = value
    return {"limits": limits}


@risk_router.post("/api/risk/kill-switch", response_model=KillSwitchResponse)
async def activate_kill_switch(
    db: DatabaseManager = Depends(get_db),
):
    """
    Emergency kill switch.

    Actions:
    1. Publish kill command to NATS (risk.management)
    2. Pause all active agents
    3. Mark kill switch as active
    """
    actions: List[str] = []

    # 1. Publish kill command via NATS (if messaging available)
    try:
        # Best-effort NATS publish — messaging may not be injected
        from src.messaging import MemoryMessagingClient
        messaging = MemoryMessagingClient()
        await messaging.publish("risk.management", {
            "command": "kill_switch",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        actions.append("Published kill command to risk.management")
    except Exception as e:
        logger.warning("Could not publish kill command: %s", e)
        actions.append(f"NATS publish failed: {e}")

    # 2. Pause all active agents
    paused_count = 0
    try:
        agents = await db.list_agents()
        for agent in agents:
            if agent.status in ("live", "paper", "backtesting"):
                await db.update_agent_status(
                    agent.id, "paused",
                    paused_at=datetime.now(timezone.utc),
                )
                paused_count += 1
        actions.append(f"Paused {paused_count} agents")
    except Exception as e:
        logger.error("Failed to pause agents: %s", e)
        actions.append(f"Agent pause failed: {e}")

    # 3. Mark kill switch active
    _risk_state["kill_switch_active"] = True
    _risk_state["kill_switch_activated_at"] = datetime.now(timezone.utc).isoformat()
    actions.append("Kill switch activated")

    logger.critical("KILL SWITCH ACTIVATED: %s", actions)

    # Audit log (fire-and-forget)
    try:
        await db.log_audit(
            action="kill_switch",
            resource_type="risk",
            details={"actions": actions, "paused_agents": paused_count},
            actor="api",
        )
    except Exception:
        logger.warning("Audit log write failed for kill_switch")

    # Raise alarm
    if _escalator:
        await _escalator.raise_alarm(
            "kill-switch",
            "Kill Switch Activated",
            "Emergency kill switch was manually triggered",
            severity=Severity.CRITICAL,
            source="api",
        )

    return KillSwitchResponse(
        status="activated",
        activated_at=_risk_state["kill_switch_activated_at"],
        actions=actions,
    )


@risk_router.get("/api/risk/alarms")
async def list_alarms(include_acknowledged: bool = False):
    """List active (or all) alarms."""
    if not _escalator:
        return {"alarms": []}
    alarms = _escalator.list_alarms(include_acknowledged=include_acknowledged)
    return {
        "alarms": [
            {
                "alarm_id": a.alarm_id,
                "title": a.title,
                "message": a.message,
                "severity": a.severity.name,
                "source": a.source,
                "created_at": a.created_at,
                "acknowledged": a.acknowledged,
                "acknowledged_by": a.acknowledged_by,
                "escalation_count": a.escalation_count,
            }
            for a in alarms
        ]
    }


@risk_router.post("/api/risk/alarms/{alarm_id}/ack")
async def acknowledge_alarm(alarm_id: str):
    """Acknowledge an alarm to stop its escalation timer."""
    if not _escalator:
        raise HTTPException(status_code=503, detail="Escalation engine not initialized")
    ok = await _escalator.acknowledge(alarm_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Alarm not found or already acknowledged")
    return {"status": "acknowledged", "alarm_id": alarm_id}
