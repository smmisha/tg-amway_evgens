"""Telegram Bot Listener for handling /start and private messages."""

import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

from config.settings import TELEGRAM_BOT_TOKEN

logger = logging.getLogger(__name__)

START_RESPONSE_TEXT = """
Привет! 🌿 Добро пожаловать в Amway Daily!

Здесь я публикую свежие обзоры продуктов Amway — XS, Nutrilite, Artistry и Home Care: состав, польза и мой личный опыт. 💪

Для заказа, консультации или оформления персональной скидки пишите напрямую:
👉 @evgen_blago

📲 Подберу лучшее решение под ваши задачи!
""".strip()


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command in private chat."""
    if update.message:
        await update.message.reply_text(START_RESPONSE_TEXT)


def run_bot_listener():
    """Start polling listener for Telegram Bot commands and DMs."""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is not set in .env")
        return

    logger.info("Starting Telegram Bot listener for /start and DMs...")
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))

    logger.info("Bot listener is active and waiting for messages...")
    app.run_polling()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_bot_listener()
