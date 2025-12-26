import asyncio
import logging

import requests

logger = logging.getLogger(__name__)


def send_telegram_message(
    bot_token: str, chat_id: str, text: str, parse_mode: str = "Markdown"
) -> bool:
    """
    Fire-and-forget Telegram notification.
    Returns True on 200 OK, False otherwise.
    """
    if not bot_token or not chat_id:
        logger.warning("Missing Telegram credentials; skipping notification.")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode},
            timeout=10,
        )
        if resp.status_code != 200:
            logger.error("Telegram send failed: %s - %s", resp.status_code, resp.text)
            return False
        return True
    except Exception as exc:  # noqa: BLE001
        logger.exception("Telegram send failed: %s", exc)
        return False


async def send_telegram_message_async(
    bot_token: str, chat_id: str, text: str, parse_mode: str = "Markdown"
) -> bool:
    """Async wrapper to avoid blocking the event loop."""
    return await asyncio.to_thread(
        send_telegram_message, bot_token, chat_id, text, parse_mode
    )
