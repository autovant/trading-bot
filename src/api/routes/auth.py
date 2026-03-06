"""API key rotation endpoint with 24-hour grace period."""

import hmac
import json
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from pydantic import BaseModel

logger = logging.getLogger(__name__)

auth_router = APIRouter(tags=["auth"])

API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

GRACE_PERIOD_HOURS = 24
_STATE_FILE = Path("data/api_key_rotation.json")


# ---------------------------------------------------------------------------
# Rotation State
# ---------------------------------------------------------------------------


class _RotationState:
    """Holds the active key and optional grace-period key."""

    def __init__(self) -> None:
        self.active_key: Optional[str] = None
        self.grace_key: Optional[str] = None
        self.grace_expires: Optional[datetime] = None
        self._load()

    # -- persistence --

    def _load(self) -> None:
        if not _STATE_FILE.exists():
            return
        try:
            raw = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
            self.active_key = raw.get("active_key")
            self.grace_key = raw.get("grace_key")
            exp = raw.get("grace_expires")
            self.grace_expires = datetime.fromisoformat(exp) if exp else None
        except Exception:
            logger.warning("Could not load API key rotation state", exc_info=True)

    def _save(self) -> None:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "active_key": self.active_key,
            "grace_key": self.grace_key,
            "grace_expires": self.grace_expires.isoformat() if self.grace_expires else None,
        }
        _STATE_FILE.write_text(json.dumps(payload), encoding="utf-8")

    # -- public API --

    def rotate(self, new_key: str) -> None:
        old_key = self.get_active_key()
        self.grace_key = old_key
        self.grace_expires = datetime.now(timezone.utc) + timedelta(hours=GRACE_PERIOD_HOURS)
        self.active_key = new_key
        self._save()
        logger.info("API key rotated. Old key valid until %s", self.grace_expires.isoformat())

    def get_active_key(self) -> Optional[str]:
        return self.active_key or os.getenv("API_KEY") or os.getenv("VAULT_MASTER_KEY")

    def is_valid(self, provided: str) -> bool:
        active = self.get_active_key()
        if active and hmac.compare_digest(provided, active):
            return True
        # Check grace-period key
        if (
            self.grace_key
            and self.grace_expires
            and datetime.now(timezone.utc) < self.grace_expires
            and hmac.compare_digest(provided, self.grace_key)
        ):
            return True
        return False


rotation_state = _RotationState()


# ---------------------------------------------------------------------------
# Auth dependency (reusable)
# ---------------------------------------------------------------------------


async def require_api_key(key: str = Security(api_key_header)) -> str:
    if not key or not rotation_state.is_valid(key):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid API key")
    return key


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class RotateKeyRequest(BaseModel):
    new_key: Optional[str] = None  # If omitted, a secure key is generated


class RotateKeyResponse(BaseModel):
    new_key: str
    grace_period_hours: int
    grace_expires: str
    message: str


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@auth_router.post(
    "/api/auth/rotate-key",
    response_model=RotateKeyResponse,
    dependencies=[Depends(require_api_key)],
)
async def rotate_api_key(request: RotateKeyRequest) -> RotateKeyResponse:
    """Rotate the API authentication key.

    The previous key remains valid for a 24-hour grace period so that
    running clients can update without downtime.
    """
    new_key = request.new_key or secrets.token_urlsafe(32)

    rotation_state.rotate(new_key)

    return RotateKeyResponse(
        new_key=new_key,
        grace_period_hours=GRACE_PERIOD_HOURS,
        grace_expires=rotation_state.grace_expires.isoformat(),
        message=f"Key rotated. Old key valid for {GRACE_PERIOD_HOURS}h.",
    )
