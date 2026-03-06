"""
Discord Webhook Notifications.

Sends rich embed messages to a Discord channel via webhook.
Env: DISCORD_WEBHOOK_URL
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


class DiscordNotifier:
    """Send formatted notifications to Discord via webhook."""

    COLORS = {
        "info": 0x3498DB,       # blue
        "success": 0x2ECC71,    # green
        "warning": 0xF1C40F,    # yellow
        "critical": 0xE74C3C,   # red
        "shutdown": 0x8E44AD,   # purple
    }

    def __init__(self, webhook_url: Optional[str] = None):
        self.webhook_url = webhook_url or os.environ.get("DISCORD_WEBHOOK_URL", "")
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
        description: str,
        severity: str = "info",
        fields: Optional[List[Dict[str, Any]]] = None,
        footer: Optional[str] = None,
    ) -> bool:
        """
        Send a Discord embed message.

        Parameters
        ----------
        title : str
            Embed title.
        description : str
            Embed body text.
        severity : str
            One of info, success, warning, critical, shutdown.
        fields : list[dict]
            Optional embed fields [{name, value, inline}].
        footer : str
            Optional footer text.
        """
        if not self.webhook_url:
            logger.debug("Discord webhook URL not configured, skipping notification")
            return False

        embed: Dict[str, Any] = {
            "title": title,
            "description": description,
            "color": self.COLORS.get(severity, self.COLORS["info"]),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if fields:
            embed["fields"] = [
                {"name": f["name"], "value": str(f["value"]), "inline": f.get("inline", True)}
                for f in fields
            ]
        if footer:
            embed["footer"] = {"text": footer}

        payload = {"embeds": [embed]}

        try:
            client = await self._get_client()
            resp = await client.post(self.webhook_url, json=payload)
            if resp.status_code in (200, 204):
                logger.info("Discord notification sent: %s", title)
                return True
            logger.warning("Discord webhook returned %d: %s", resp.status_code, resp.text)
            return False
        except Exception as e:
            logger.error("Failed to send Discord notification: %s", e)
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
        return await self.send(f"Trade: {side.upper()} {symbol}", "", severity=severity, fields=fields)

    async def daily_summary(self, stats: Dict[str, Any]) -> bool:
        fields = [
            {"name": "Total Trades", "value": str(stats.get("total_trades", 0))},
            {"name": "Win Rate", "value": f"{stats.get('win_rate', 0):.1%}"},
            {"name": "P&L", "value": f"${stats.get('realized_pnl', 0):+,.2f}"},
            {"name": "Equity", "value": f"${stats.get('equity', 0):,.2f}"},
            {"name": "Max DD", "value": f"{stats.get('max_drawdown', 0):.1%}"},
        ]
        return await self.send("Daily Summary", "", severity="info", fields=fields, footer=datetime.now(timezone.utc).strftime("%Y-%m-%d"))

    async def alarm(self, title: str, message: str, severity: str = "warning") -> bool:
        return await self.send(f"ALARM: {title}", message, severity=severity)
