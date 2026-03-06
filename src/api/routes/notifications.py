"""Notification preferences and Telegram integration API routes."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, status
from pydantic import BaseModel, field_validator

from src.database import DatabaseManager

logger = logging.getLogger(__name__)

notifications_router = APIRouter(tags=["notifications"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class TelegramConfig(BaseModel):
    bot_token: str
    chat_id: str
    enabled: bool = True


class NotificationPreferences(BaseModel):
    """User notification preferences — which events trigger which channels."""

    trade_executed: bool = True
    order_filled: bool = True
    order_cancelled: bool = False
    risk_alert: bool = True
    circuit_breaker: bool = True
    agent_status: bool = True
    system_error: bool = True

    channels: List[str] = ["discord"]  # discord, telegram

    telegram: Optional[TelegramConfig] = None
    discord_webhook_url: Optional[str] = None


class NotificationPreferencesResponse(BaseModel):
    preferences: NotificationPreferences
    telegram_configured: bool
    discord_configured: bool


class TelegramTestRequest(BaseModel):
    bot_token: str
    chat_id: str

    @field_validator("bot_token")
    @classmethod
    def validate_token(cls, v: str) -> str:
        v = v.strip()
        if not v or ":" not in v:
            raise ValueError("Invalid bot token format. Expected format: 123456:ABC-DEF...")
        return v

    @field_validator("chat_id")
    @classmethod
    def validate_chat_id(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Chat ID is required")
        return v


class TelegramTestResponse(BaseModel):
    success: bool
    message: str


class SendNotificationRequest(BaseModel):
    title: str
    message: str
    severity: str = "info"

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, v: str) -> str:
        allowed = {"info", "success", "warning", "critical"}
        if v not in allowed:
            raise ValueError(f"Severity must be one of: {', '.join(sorted(allowed))}")
        return v


# ---------------------------------------------------------------------------
# Dependencies — overridden at app startup
# ---------------------------------------------------------------------------

async def get_db() -> DatabaseManager:
    raise NotImplementedError


# In-memory preferences store (persisted to DB when available)
_preferences = NotificationPreferences()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@notifications_router.get(
    "/api/notifications/preferences",
    response_model=NotificationPreferencesResponse,
)
async def get_preferences():
    """Get current notification preferences."""
    return NotificationPreferencesResponse(
        preferences=_preferences,
        telegram_configured=_preferences.telegram is not None and _preferences.telegram.enabled,
        discord_configured=bool(_preferences.discord_webhook_url),
    )


@notifications_router.put(
    "/api/notifications/preferences",
    response_model=NotificationPreferencesResponse,
)
async def update_preferences(prefs: NotificationPreferences):
    """Update notification preferences."""
    global _preferences
    _preferences = prefs

    logger.info(
        "Notification preferences updated: channels=%s",
        prefs.channels,
    )

    return NotificationPreferencesResponse(
        preferences=_preferences,
        telegram_configured=_preferences.telegram is not None and _preferences.telegram.enabled,
        discord_configured=bool(_preferences.discord_webhook_url),
    )


@notifications_router.post(
    "/api/notifications/telegram/test",
    response_model=TelegramTestResponse,
)
async def test_telegram(request: TelegramTestRequest):
    """Send a test message to verify Telegram configuration."""
    from src.notifications.telegram import TelegramNotifier

    notifier = TelegramNotifier(bot_token=request.bot_token, chat_id=request.chat_id)
    try:
        success = await notifier.send(
            title="Trading Bot Test",
            message="Telegram notifications are working!",
            severity="info",
        )
    except Exception as exc:
        logger.exception("Telegram test failed")
        return TelegramTestResponse(success=False, message=f"Failed: {exc}")
    finally:
        await notifier.close()

    if success:
        return TelegramTestResponse(
            success=True,
            message="Test message sent successfully. Check your Telegram.",
        )
    else:
        return TelegramTestResponse(
            success=False,
            message="Failed to send test message. Verify bot token and chat ID.",
        )


@notifications_router.post(
    "/api/notifications/send",
    status_code=status.HTTP_202_ACCEPTED,
)
async def send_notification(request: SendNotificationRequest):
    """Manually send a notification via all configured channels."""
    results: Dict[str, Any] = {}

    # Discord
    if "discord" in _preferences.channels and _preferences.discord_webhook_url:
        from src.notifications.discord import DiscordNotifier

        notifier = DiscordNotifier(webhook_url=_preferences.discord_webhook_url)
        try:
            ok = await notifier.send(
                title=request.title,
                description=request.message,
                severity=request.severity,
            )
            results["discord"] = "sent" if ok else "failed"
        except Exception as exc:
            logger.exception("Discord notification failed")
            results["discord"] = f"error: {exc}"
        finally:
            await notifier.close()

    # Telegram
    if (
        "telegram" in _preferences.channels
        and _preferences.telegram
        and _preferences.telegram.enabled
    ):
        from src.notifications.telegram import TelegramNotifier

        tg_notifier = TelegramNotifier(
            bot_token=_preferences.telegram.bot_token,
            chat_id=_preferences.telegram.chat_id,
        )
        try:
            ok = await tg_notifier.send(
                title=request.title,
                message=request.message,
                severity=request.severity,
            )
            results["telegram"] = "sent" if ok else "failed"
        except Exception as exc:
            logger.exception("Telegram notification failed")
            results["telegram"] = f"error: {exc}"
        finally:
            await tg_notifier.close()

    if not results:
        return {"status": "no_channels_configured", "detail": "No notification channels are configured or enabled."}

    return {"status": "accepted", "results": results}
