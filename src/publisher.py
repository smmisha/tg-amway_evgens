"""Telegram publisher — sends posts to a Telegram group.

Supports: text-only, photo + caption, and media groups.
"""

import logging
import os

from telegram import Bot, InputMediaPhoto
from telegram.constants import ParseMode

from config.settings import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_GROUP_CHAT_ID,
    TELEGRAM_ADMIN_CHAT_ID,
    TELEGRAM_CHAT_ID,
)

logger = logging.getLogger(__name__)


def resolve_target_chat(chat_id: str | None) -> str:
    """Return the effective publish target chat id.
    Resolution order (config/settings.py): explicit arg -> GROUP -> ADMIN -> CHAT.
    """
    if chat_id:
        return chat_id
    return TELEGRAM_GROUP_CHAT_ID or TELEGRAM_ADMIN_CHAT_ID or TELEGRAM_CHAT_ID or ""


def _log_target(chat_id: str | None):
    target = resolve_target_chat(chat_id)
    source = "arg"
    if not chat_id:
        if TELEGRAM_GROUP_CHAT_ID:
            source = "TELEGRAM_GROUP_CHAT_ID"
        elif TELEGRAM_ADMIN_CHAT_ID:
            source = "TELEGRAM_ADMIN_CHAT_ID (FALLBACK! GROUP not set)"
        elif TELEGRAM_CHAT_ID:
            source = "TELEGRAM_CHAT_ID (FALLBACK! GROUP/ADMIN not set)"
        else:
            source = "NOT SET"
    logger.warning(f"Publish target chat_id={target!r} sourced from {source}")


def escape_markdown_v2(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2 (utility for MarkdownV2 formatting)."""
    special_chars = r"_*[]()~`>#+-=|{}.!"
    escaped = ""
    for char in text:
        if char in special_chars:
            escaped += f"\\{char}"
        else:
            escaped += char
    return escaped


def _truncate_preserving_tail(text: str, max_len: int = 1000) -> str:
    """Truncate text to max_len while keeping the CTA and hashtag tail intact."""
    if len(text) <= max_len:
        return text

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    tail_paragraphs = []
    
    # Identify tail paragraphs (hashtags and/or @evgen_blago CTA)
    while paragraphs:
        last = paragraphs[-1]
        if "@evgen_blago" in last or "#" in last:
            tail_paragraphs.insert(0, paragraphs.pop())
        else:
            break

    tail = "\n\n".join(tail_paragraphs) if tail_paragraphs else ""
    body = "\n\n".join(paragraphs) if paragraphs else text

    # Reserve space for tail and separator/ellipsis
    reserved_space = len(tail) + (4 if tail else 0) + 3
    max_body_len = max_len - reserved_space

    if max_body_len > 100 and len(body) > max_body_len:
        trimmed_body = body[:max_body_len]
        last_end = max(
            trimmed_body.rfind("."),
            trimmed_body.rfind("!"),
            trimmed_body.rfind("?"),
            trimmed_body.rfind("\n"),
        )
        if last_end > 100:
            body = trimmed_body[: last_end + 1]
        else:
            last_space = trimmed_body.rfind(" ")
            if last_space > 100:
                body = trimmed_body[:last_space] + "..."
            else:
                body = trimmed_body + "..."

    if tail:
        return f"{body}\n\n{tail}"
    return body


async def publish_post(
    text: str,
    image_path: str | None = None,
    use_html: bool = True,
    chat_id: str | None = None,
) -> str | None:
    """Publish a post to a Telegram chat (group by default, or admin chat).

    Args:
        text: Post text to send
        image_path: Optional path to local image file
        use_html: Use HTML parse mode (default). If False, sends plain text.
        chat_id: Target chat. Defaults to the publish group.

    Returns:
        Message ID string on success, None on failure
    """
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is not set")
        return None
    target_chat = resolve_target_chat(chat_id)
    if not target_chat:
        logger.error("Telegram chat id is not set (TELEGRAM_GROUP_CHAT_ID)")
        return None
    _log_target(chat_id)

    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    parse_mode = ParseMode.HTML if use_html else None

    # For HTML mode, we don't need to escape text heavily — just avoid breaking tags
    # The posts are plain text with emojis, so no HTML entities needed
    post_text = text

    try:
        final_text = post_text.strip()
        if len(final_text) > 4096:
            final_text = final_text[:4096]

        if image_path and os.path.exists(image_path):
            with open(image_path, "rb") as photo:
                if len(final_text) <= 1000:
                    message = await bot.send_photo(
                        chat_id=target_chat,
                        photo=photo,
                        caption=final_text,
                        parse_mode=parse_mode,
                    )
                    logger.info(f"Published photo post. Message ID: {message.message_id}")
                    return str(message.message_id)
                else:
                    # Extract the CTA/hashtag tail so it survives truncation
                    caption_text = _truncate_preserving_tail(final_text, max_len=1000)

                    message = await bot.send_photo(
                        chat_id=target_chat,
                        photo=photo,
                        caption=caption_text,
                        parse_mode=parse_mode,
                    )
                    logger.info(f"Published clean photo post ({len(caption_text)} chars). Message ID: {message.message_id}")
                    return str(message.message_id)
        else:
            # Send text-only message (Telegram limit 4096)
            message = await bot.send_message(
                chat_id=target_chat,
                text=final_text,
                parse_mode=parse_mode,
                disable_web_page_preview=True,
            )
            logger.info(f"Published text post. Message ID: {message.message_id}")
            return str(message.message_id)

    except Exception as e:
        logger.error(f"Failed to publish to Telegram: {e}")
        raise


async def publish_media_group(
    text: str,
    image_paths: list[str],
    chat_id: str | None = None,
) -> str | None:
    """Publish a media group (multiple images) with caption.

    Args:
        text: Caption text for the first image
        image_paths: List of local image file paths
        chat_id: Target chat. Defaults to the publish group.

    Returns:
        First message ID string on success, None on failure
    """
    if not TELEGRAM_BOT_TOKEN:
        logger.error("Telegram credentials not configured")
        return None
    target_chat = resolve_target_chat(chat_id)
    if not target_chat:
        logger.error("Telegram chat id is not set (TELEGRAM_GROUP_CHAT_ID)")
        return None
    _log_target(chat_id)

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
            chat_id=target_chat,
            media=media,
        )
        logger.info(f"Published media group ({len(messages)} items)")
        return str(messages[0].message_id) if messages else None

    except Exception as e:
        logger.error(f"Failed to publish media group: {e}")
        # Fallback to text-only
        return await publish_post(text)
