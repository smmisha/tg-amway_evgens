"""Diagnostic: verify the bot can see and post into a configured chat.

Usage:
    python -m src.diag_chat                            # check configured targets
    python -m src.diag_chat --send                     # + send a test post
    python -m src.diag_chat --chat-id <id> --confirm   # check an explicit chat id
    python -m src.diag_chat --chat-id <id> --confirm --send

SECURITY (TG-F-14): произвольный chat_id больше не принимается «молча».
По умолчанию проверяются только ``TELEGRAM_GROUP_CHAT_ID`` и
``TELEGRAM_ADMIN_CHAT_ID`` из ``config/settings.py``. Явный ``--chat-id``
требует ``--confirm``: одиночный запуск с опечаткой в id больше не может
отправить диагностическое сообщение в чужой/неизвестный чат. Позиционные
аргументы (прежний ``python -m src.diag_chat <chat_id>``) запрещены.
"""

import argparse
import asyncio
import logging
import sys

from telegram import Bot

from config.settings import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_GROUP_CHAT_ID,
    TELEGRAM_ADMIN_CHAT_ID,
)
from src.log_safety import configure_safe_logging

# SECURITY (TG-F-09): httpx/httpcore INFO-логи содержат URL с токеном бота.
configure_safe_logging(
    level=logging.INFO, log_format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

TEST_MESSAGE = "✅ Диагностика: бот работает, канал доступен."


def _configured_targets() -> list[str]:
    """Allowlisted chat ids из config/settings.py (порядок GROUP, ADMIN, без дублей)."""
    targets: list[str] = []
    for raw in (TELEGRAM_GROUP_CHAT_ID, TELEGRAM_ADMIN_CHAT_ID):
        value = str(raw).strip() if raw else ""
        if value and value not in targets:
            targets.append(value)
    return targets


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m src.diag_chat",
        description=(
            "Telegram chat diagnostics. Only TELEGRAM_GROUP_CHAT_ID/"
            "TELEGRAM_ADMIN_CHAT_ID are used by default (TG-F-14)."
        ),
    )
    parser.add_argument(
        "--chat-id",
        default=None,
        help=(
            "explicit chat id (requires --confirm); default: configured "
            "TELEGRAM_GROUP_CHAT_ID + TELEGRAM_ADMIN_CHAT_ID"
        ),
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="confirm an explicit --chat-id (mandatory for --chat-id)",
    )
    parser.add_argument(
        "--send",
        action="store_true",
        help="send a test message after the read-only check",
    )
    return parser.parse_args(argv)


def _resolve_targets(args: argparse.Namespace) -> list[str] | None:
    """Вернуть разрешённые цели или None (тогда main() завершится с кодом 2)."""
    configured = _configured_targets()
    explicit = (args.chat_id or "").strip()

    if not explicit:
        if not configured:
            logger.error(
                "Neither TELEGRAM_GROUP_CHAT_ID nor TELEGRAM_ADMIN_CHAT_ID is "
                "set — refusing to guess a chat id (TG-F-14)."
            )
            return None
        return configured

    if not args.confirm:
        logger.error(
            "Refusing explicit --chat-id %r without --confirm (TG-F-14). "
            "Use the configured targets or add --confirm deliberately.",
            explicit,
        )
        return None
    if explicit not in configured:
        logger.warning(
            "Explicit --chat-id %r is outside configured targets %r — "
            "continuing because --confirm was given.",
            explicit,
            configured,
        )
    return [explicit]


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


async def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(sys.argv[1:] if argv is None else argv))

    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set")
        return 1

    targets = _resolve_targets(args)
    if not targets:
        return 2

    logger.info("Targets: %r", targets)
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    me = await bot.get_me()
    logger.info(f"Bot: @{me.username} name={me.first_name!r}")

    for i, chat_id in enumerate(targets, 1):
        logger.info(f"--- target {i}/{len(targets)} ---")
        await check_chat(bot, chat_id)
        if args.send:
            try:
                sent = await bot.send_message(chat_id=chat_id, text=TEST_MESSAGE)
                logger.info(f"Sent test message -> message_id={sent.message_id}")
            except Exception as e:
                logger.error(f"Failed to send to {chat_id}: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
