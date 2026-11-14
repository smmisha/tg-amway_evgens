"""Respond to /start and DMs using Telegram getUpdates (polling via cron).

This script is designed to be run periodically (e.g., every 5 minutes via
GitHub Actions) to check for new messages and respond to them.
No long-running server needed.
"""

import asyncio
import json
import logging
import os

import httpx

from config.settings import TELEGRAM_BOT_TOKEN
from config.prompts import START_RESPONSE
from src.log_safety import configure_safe_logging, mask_identifier

# SECURITY (TG-F-09): токен бота передаётся в пути URL Bot API; INFO-логи httpx
# писали его целиком. Гасим HTTP-логи и вырезаем секреты из сообщений.
configure_safe_logging(level=logging.INFO)
logger = logging.getLogger(__name__)

LAST_UPDATE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "last_update_id.txt",
)


def load_last_update_id() -> int:
    """Load the last processed update ID."""
    try:
        with open(LAST_UPDATE_FILE, "r") as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError):
        return 0


def save_last_update_id(update_id: int):
    """Save the last processed update ID."""
    os.makedirs(os.path.dirname(LAST_UPDATE_FILE), exist_ok=True)
    with open(LAST_UPDATE_FILE, "w") as f:
        f.write(str(update_id))


async def process_updates():
    """Fetch new updates from Telegram and respond to /start or DMs."""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is not set")
        return

    base_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
    last_id = load_last_update_id()

    async with httpx.AsyncClient(timeout=30) as client:
        # Get updates
        params = {"offset": last_id + 1, "timeout": 5, "allowed_updates": '["message"]'}
        resp = await client.get(f"{base_url}/getUpdates", params=params)
        data = resp.json()

        if resp.status_code == 409 or data.get("error_code") == 409:
            logger.warning(
                "Telegram getUpdates conflict (409): another bot instance is active. Skipping."
            )
            return

        if not data.get("ok"):
            # SECURITY (TG-F-09): описание ошибки не содержит токен, но логируем
            # только error_code/description, а не весь ответ (URL с токеном
            # может попасть в поле/исключение).
            logger.error(
                "getUpdates failed: error_code=%s description=%r parameters=%r",
                data.get("error_code"),
                data.get("description"),
                data.get("parameters"),
            )
            return

        updates = data.get("result", [])
        if not updates:
            logger.info("No new messages")
            return

        logger.info(f"Processing {len(updates)} new message(s)")

        for update in updates:
            update_id = update["update_id"]
            message = update.get("message", {})
            chat = message.get("chat", {})
            chat_id = chat.get("id")
            chat_type = chat.get("type", "")
            text = message.get("text", "")

            # Only respond to the /start command in private chats.
            # All other user messages are ignored (no auto-replies).
            if chat_type == "private" and chat_id:
                if text.strip() == "/start":
                    # TG-F-13: chat_id пользователя в логах не раскрываем.
                    logger.info("Replying to chat %s: /start", mask_identifier(chat_id))
                    await client.post(
                        f"{base_url}/sendMessage",
                        json={"chat_id": chat_id, "text": START_RESPONSE},
                    )
                else:
                    logger.info(
                        "Ignoring non-/start message from chat %s",
                        mask_identifier(chat_id),
                    )

            # Track last processed update
            if update_id > last_id:
                last_id = update_id

        save_last_update_id(last_id)
        logger.info(f"Done. Last update ID: {last_id}")


if __name__ == "__main__":
    asyncio.run(process_updates())
