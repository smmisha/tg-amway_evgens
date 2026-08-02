"""Telegram publisher — sends posts to a Telegram group.

Supports: text-only, photo + caption, and media groups.
"""

import logging
import os

from telegram import Bot, InputMediaPhoto
from telegram.constants import ParseMode

from config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)


def escape_markdown_v2(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    special_chars = r"_*[]()~`>#+-=|{}.!"
    escaped = ""
    for char in text:
        if char in special_chars:
            escaped += f"\\{char}"
        else:
            escaped += char
    return escaped


async def publish_post(
    text: str,
    image_path: str | None = None,
    use_html: bool = True,
) -> str | None:
    """Publish a post to the Telegram group.

    Args:
        text: Post text to send
        image_path: Optional path to local image file
        use_html: Use HTML parse mode (default). If False, sends plain text.

    Returns:
        Message ID string on success, None on failure
    """
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is not set")
        return None
    if not TELEGRAM_CHAT_ID:
        logger.error("TELEGRAM_CHAT_ID is not set")
        return None

    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    parse_mode = ParseMode.HTML if use_html else None

    # For HTML mode, we don't need to escape text heavily — just avoid breaking tags
    # The posts are plain text with emojis, so no HTML entities needed
    post_text = text

    try:
        if image_path and os.path.exists(image_path):
            # Send photo with caption
            with open(image_path, "rb") as photo:
                message = await bot.send_photo(
                    chat_id=TELEGRAM_CHAT_ID,
                    photo=photo,
                    caption=post_text[:1024],  # Telegram caption limit
                    parse_mode=parse_mode,
                )
            logger.info(f"Published photo post. Message ID: {message.message_id}")
            return str(message.message_id)
        else:
            # Send text-only message
            message = await bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=post_text,
                parse_mode=parse_mode,
                disable_web_page_preview=True,
            )
            logger.info(f"Published text post. Message ID: {message.message_id}")
            return str(message.message_id)

    except Exception as e:
        logger.error(f"Failed to publish to Telegram: {e}")
        return None


async def publish_media_group(
    text: str,
    image_paths: list[str],
) -> str | None:
    """Publish a media group (multiple images) with caption.

    Args:
        text: Caption text for the first image
        image_paths: List of local image file paths

    Returns:
        First message ID string on success, None on failure
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("Telegram credentials not configured")
        return None

    if not image_paths:
        return await publish_post(text)

    bot = Bot(token=TELEGRAM_BOT_TOKEN)

    try:
        media = []
        for i, path in enumerate(image_paths[:10]):  # Telegram max 10 in group
            if not os.path.exists(path):
                continue
            with open(path, "rb") as f:
                photo_bytes = f.read()
            if i == 0:
                media.append(InputMediaPhoto(
                    media=photo_bytes,
                    caption=text[:1024],
                    parse_mode=ParseMode.HTML,
                ))
            else:
                media.append(InputMediaPhoto(media=photo_bytes))

        if not media:
            return await publish_post(text)

        messages = await bot.send_media_group(
            chat_id=TELEGRAM_CHAT_ID,
            media=media,
        )
        logger.info(f"Published media group ({len(messages)} items)")
        return str(messages[0].message_id) if messages else None

    except Exception as e:
        logger.error(f"Failed to publish media group: {e}")
        # Fallback to text-only
        return await publish_post(text)
