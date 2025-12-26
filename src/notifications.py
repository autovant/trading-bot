"""
Telegram notification system for live trading alerts.
"""

import logging
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """
    Sends notifications to a Telegram bot.
    """

    def __init__(self, bot_token: Optional[str] = None, chat_id: Optional[str] = None):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.enabled = bool(bot_token and chat_id)
        self.base_url = (
            f"https://api.telegram.org/bot{bot_token}" if bot_token else None
        )

    async def send_message(self, message: str) -> bool:
        """
        Send a text message to the configured Telegram chat.
        """
        if not self.enabled:
            logger.warning("Telegram notifier is not configured. Message not sent.")
            return False

        url = f"{self.base_url}/sendMessage"
        payload = {"chat_id": self.chat_id, "text": message, "parse_mode": "Markdown"}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as response:
                    if response.status == 200:
                        logger.info("Telegram message sent successfully")
                        return True
                    else:
                        logger.error(
                            f"Failed to send Telegram message: {response.status}"
                        )
                        return False
        except Exception as e:
            logger.error(f"Error sending Telegram message: {e}")
            return False

    async def send_trade_alert(self, trade_info: dict) -> bool:
        """
        Send a formatted trade alert.
        """
        symbol = trade_info.get("symbol", "UNKNOWN")
        side = trade_info.get("side", "UNKNOWN")
        price = trade_info.get("price", 0)
        quantity = trade_info.get("quantity", 0)
        strategy = trade_info.get("strategy", "UNKNOWN")

        message = f"""
🚨 *TRADE ALERT* 🚨

*Strategy:* {strategy}
*Symbol:* {symbol}
*Side:* {side.upper()}
*Price:* ${price:.2f}
*Quantity:* {quantity:.4f}
*Value:* ${price * quantity:.2f}
        """

        return await self.send_message(message.strip())

    async def send_pnl_update(self, pnl: float, equity: float) -> bool:
        """
        Send a PnL update.
        """
        pnl_emoji = "📈" if pnl >= 0 else "📉"
        message = f"""
{pnl_emoji} *PnL Update*

*Current PnL:* ${pnl:.2f}
*Total Equity:* ${equity:.2f}
        """

        return await self.send_message(message.strip())


# Global instance
_notifier: Optional[TelegramNotifier] = None


def init_notifier(bot_token: Optional[str] = None, chat_id: Optional[str] = None):
    """
    Initialize the global Telegram notifier.
    """
    global _notifier
    _notifier = TelegramNotifier(bot_token, chat_id)


def get_notifier() -> Optional[TelegramNotifier]:
    """
    Get the global Telegram notifier instance.
    """
    return _notifier
