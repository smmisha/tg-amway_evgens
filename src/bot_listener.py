"""Telegram Bot Listener for handling /start in private chats only.

SECURITY (TG-F-14): бот в первую очередь публикует посты в группу. Ранее
``/start`` отвечал в любом чате, где бот получил команду, — любой участник
группы мог заставить бота писать в неё. Сценария «/start в группе» у проекта
нет, поэтому хендлер отвечает только в private-чатах: двойная защита —
фильтр ``ChatType.PRIVATE`` при регистрации и проверка типа чата в хендлере.
"""

import logging

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, filters

from config.settings import TELEGRAM_BOT_TOKEN
from config.prompts import START_RESPONSE
from src.log_safety import configure_safe_logging

logger = logging.getLogger(__name__)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command in private chat only (TG-F-14)."""
    chat = update.effective_chat
    if chat is None or chat.type != "private":
        # Второй слой защиты: даже если фильтр когда-нибудь снимут/изменят,
        # в группах и каналах бот не отвечает.
        logger.info(
            "Ignoring /start outside private chat (chat_id=%s type=%s)",
            getattr(chat, "id", None),
            getattr(chat, "type", None),
        )
        return
    if update.message:
        await update.message.reply_text(START_RESPONSE)


def run_bot_listener():
    """Start polling listener for Telegram Bot commands and DMs."""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is not set in .env")
        return

    logger.info("Starting Telegram Bot listener for /start and DMs...")
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # SECURITY (TG-F-14): только private-чаты.
    app.add_handler(
        CommandHandler("start", start_command, filters=filters.ChatType.PRIVATE)
    )

    logger.info("Bot listener is active and waiting for messages...")
    app.run_polling()


if __name__ == "__main__":
    # SECURITY (TG-F-09): httpx/httpcore INFO-логи содержат URL с токеном бота.
    configure_safe_logging(level=logging.INFO)
    run_bot_listener()
