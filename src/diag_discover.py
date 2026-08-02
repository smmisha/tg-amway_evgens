"""Discover the numeric chat_id of a group by reading bot updates.

The bot must be a member of the target group. When it is added or when it
receives any message there, Telegram hands the bot an update that carries
the real `chat.id`. One-shot script: it does NOT advance the polling offset,
so it will not disturb `responder.py`/CI long-pollers.

Usage:
    python -m src.diag_discover [limit]

Steps:
    1. Make sure @amway_expertbot is in the target group.
    2. In that group post any message (visible to the bot) or re-add the bot,
       or have any member send something mentioning the bot.
    3. Run this script. It prints every chat it saw with id/type/title.
"""

import asyncio
import logging
import sys

from telegram import Update
from telegram import Bot
from telegram.constants import UpdateType

from config.settings import TELEGRAM_BOT_TOKEN

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def _chat_line(ch: Chat) -> str:
    return (
        f"chat.id={ch.id} type={ch.type} "
        f"title={(getattr(ch, 'title', None) or '')!r} "
        f"username={(getattr(ch, 'username', None) or '')!r}"
    )


def _extract(update: Update) -> None:
    if update.my_chat_member:
        ch = update.my_chat_member.chat
        logger.info(
            f"my_chat_member -> {_chat_line(ch)} "
            f"member_status={update.my_chat_member.new_chat_member.status}"
        )
        return
    found: list[Chat] = []
    if update.message:
        found.append(update.message.chat)
    if update.channel_post:
        found.append(update.channel_post.chat)
    if update.edited_message:
        found.append(update.edited_message.chat)
    if update.callback_query and update.callback_query.message:
        found.append(update.callback_query.message.chat)
    for ch in found:
        logger.info(f"message -> {_chat_line(ch)}")


async def main() -> int:
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set")
        return 1

    limit = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 100

    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    me = await bot.get_me()
    logger.info(f"Bot: @{me.username} name={me.first_name!r} — reading up to {limit} updates…")

    try:
        updates = await bot.get_updates(limit=10, allowed_updates=(
            UpdateType.MESSAGE,
            UpdateType.CHANNEL_POST,
            UpdateType.MY_CHAT_MEMBER,
            UpdateType.CALLBACK_QUERY,
        ))
    except Exception as e:
        logger.error(f"getUpdates failed: {e} (409 == another getUpdates is running)")
        return 1

    if not updates:
        logger.info("No pending updates. Send a message in the target group first, then re-run.")
        logger.info("If the bot was already added earlier, its update has expired — re-add it or post again.")
        return 0

    printed = set()
    for upd in updates:
        try:
            _extract(upd)
        except Exception as e:
            logger.warning(f"update {upd.update_id} skipped: {e}")

    seen = set()
    for upd in updates:
        chat = None
        if upd.message:
            chat = upd.message.chat
        elif upd.channel_post:
            chat = upd.channel_post.chat
        if chat and chat.id not in seen:
            seen.add(chat.id)
            print(chat.id)
    if seen:
        print("CANDIDATE_CHAT_IDS=" + ",".join(str(c) for c in sorted(seen, key=str)))

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))