"""Diagnostic: verify the bot can see and post into a chat.

Usage:
    python -m src.diag_chat                 # check configured targets
    python -m src.diag_chat <chat_id>       # check a specific chat id
    python -m src.diag_chat <chat_id> --send "hello"   # send a test post
"""

import asyncio
import logging
import sys

from telegram import Bot

from config.settings import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_GROUP_CHAT_ID,
    TELEGRAM_ADMIN_CHAT_ID,
    TELEGRAM_CHAT_ID,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


async def check_chat(bot: Bot, chat_id: str) -> None:
    chat_id = str(chat_id).strip()
    try:
        chat = await bot.get_chat(chat_id)
        logger.info(
            f"OK chat={chat_id!r} -> numeric_id={chat.id} type={chat.type} "
            f"title={(getattr(chat, 'title', None) or '')!r} "
            f"username={(getattr(chat, 'username', None) or '')!r}"
        )
    except Exception as e:
        logger.error(f"FAIL chat={chat_id!r}: {e}")


async def main() -> int:
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set")
        return 1

    targets = [t for t in [TELEGRAM_GROUP_CHAT_ID, TELEGRAM_ADMIN_CHAT_ID, TELEGRAM_CHAT_ID] if t]
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args:
        targets = args

    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    me = await bot.get_me()
    logger.info(f"Bot: @{me.username} name={me.first_name!r}")

    send_flag = "--send" in sys.argv
    for i, chat_id in enumerate(targets, 1):
        logger.info(f"--- target {i}/{len(targets)} ---")
        await check_chat(bot, chat_id)
        if send_flag:
            try:
                sent = await bot.send_message(
                    chat_id=chat_id,
                    text="✅ Диагностика: бот работает, канал доступен.",
                )
                logger.info(f"Sent test message -> message_id={sent.message_id}")
            except Exception as e:
                logger.error(f"Failed to send to {chat_id}: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))