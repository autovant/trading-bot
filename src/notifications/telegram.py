"""
Telegram Bot Notifications.

Sends formatted messages to a Telegram chat via the Bot API.
Env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Send formatted notifications to Telegram via Bot API."""

    SEVERITY_EMOJI = {
        "info": "ℹ️",
        "success": "✅",
        "warning": "⚠️",
        "critical": "🚨",
        "shutdown": "🛑",
    }

    BASE_URL = "https://api.telegram.org/bot{token}/sendMessage"

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
    ):
        self.bot_token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def send(
        self,
        title: str,
        message: str,
        severity: str = "info",
        fields: Optional[List[Dict[str, Any]]] = None,
        footer: Optional[str] = None,
    ) -> bool:
        """
        Send a formatted Telegram message.

        Parameters
        ----------
        title : str
            Message title (bold header line).
        message : str
            Message body text.
        severity : str
            One of info, success, warning, critical, shutdown.
        fields : list[dict]
            Optional key/value fields [{name, value}].
        footer : str
            Optional footer text (shown in italics).
        """
        if not self.bot_token or not self.chat_id:
            logger.debug("Telegram credentials not configured, skipping notification")
            return False

        emoji = self.SEVERITY_EMOJI.get(severity, self.SEVERITY_EMOJI["info"])
        parts: list[str] = [f"{emoji} <b>{_escape_html(title)}</b>"]

        if message:
            parts.append(_escape_html(message))

        if fields:
            field_lines = [
                f"<b>{_escape_html(f['name'])}:</b> {_escape_html(str(f['value']))}"
                for f in fields
            ]
            parts.append("\n".join(field_lines))

        if footer:
            parts.append(f"<i>{_escape_html(footer)}</i>")

        text = "\n\n".join(parts)

        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }

        try:
            url = self.BASE_URL.format(token=self.bot_token)
            client = await self._get_client()
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                logger.info("Telegram notification sent: %s", title)
                return True
            logger.warning("Telegram API returned %d: %s", resp.status_code, resp.text)
            return False
        except Exception as e:
            logger.error("Failed to send Telegram notification: %s", e)
            return False

    # -- Convenience methods --

    async def trade_report(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        pnl: Optional[float] = None,
    ) -> bool:
        fields = [
            {"name": "Symbol", "value": symbol},
            {"name": "Side", "value": side.upper()},
            {"name": "Qty", "value": f"{quantity:.6f}"},
            {"name": "Price", "value": f"${price:,.2f}"},
        ]
        if pnl is not None:
            fields.append({"name": "P&L", "value": f"${pnl:+,.2f}"})
        severity = "success" if (pnl is not None and pnl >= 0) else "warning"
        return await self.send(
            f"Trade: {side.upper()} {symbol}", "", severity=severity, fields=fields
        )

    async def daily_summary(self, stats: Dict[str, Any]) -> bool:
        fields = [
            {"name": "Total Trades", "value": str(stats.get("total_trades", 0))},
            {"name": "Win Rate", "value": f"{stats.get('win_rate', 0):.1%}"},
            {"name": "P&L", "value": f"${stats.get('realized_pnl', 0):+,.2f}"},
            {"name": "Equity", "value": f"${stats.get('equity', 0):,.2f}"},
            {"name": "Max DD", "value": f"{stats.get('max_drawdown', 0):.1%}"},
        ]
        return await self.send(
            "Daily Summary",
            "",
            severity="info",
            fields=fields,
            footer=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        )

    async def alarm(self, title: str, message: str, severity: str = "warning") -> bool:
        return await self.send(f"ALARM: {title}", message, severity=severity)


def _escape_html(text: str) -> str:
    """Escape HTML special characters for Telegram's HTML parse mode."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
