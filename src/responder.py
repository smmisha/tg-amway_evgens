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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

LAST_UPDATE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "last_update_id.txt",
)

START_RESPONSE = (
    "Привет! 🌿 Добро пожаловать в Amway Daily!\n\n"
    "Здесь я публикую свежие обзоры продуктов Amway — XS, Nutrilite, "
    "Artistry и Home Care: состав, польза и мой личный опыт. 💪\n\n"
    "Для заказа, консультации или оформления персональной скидки пишите напрямую:\n"
    "👉 @evgen_blago\n\n"
    "📲 Подберу лучшее решение под ваши задачи!"
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
            logger.error(f"getUpdates failed: {data}")
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
                    logger.info(f"Replying to chat {chat_id}: /start")
                    await client.post(
                        f"{base_url}/sendMessage",
                        json={"chat_id": chat_id, "text": START_RESPONSE},
                    )
                else:
                    logger.info(f"Ignoring non-/start message from chat {chat_id}")

            # Track last processed update
            if update_id > last_id:
                last_id = update_id

        save_last_update_id(last_id)
        logger.info(f"Done. Last update ID: {last_id}")


if __name__ == "__main__":
    asyncio.run(process_updates())
