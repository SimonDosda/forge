from typing import Any, Awaitable, Callable

from bot import BotApp, HELP_TEXT, START_TEXT


def build_app(token: str) -> Any:
    """Construct the Telegram Application bound to the bot token."""
    from telegram.ext import Application

    return Application.builder().token(token).build()


def register_handlers(telegram_app: Any, app: BotApp) -> None:
    """Wire BotApp methods into the Telegram Application as command/message handlers."""
    from telegram.ext import CommandHandler, MessageHandler, filters

    async def cmd_start(update, _):
        await update.message.reply_text(START_TEXT)

    async def cmd_help(update, _):
        await update.message.reply_text(HELP_TEXT)

    async def cmd_today(update, _):
        await update.message.reply_text(await app.today())

    async def cmd_history(update, _):
        await update.message.reply_text(await app.history())

    async def cmd_plants(update, _):
        await update.message.reply_text(await app.plants_list())

    async def on_message(update, _):
        await update.message.reply_text(await app.handle_message(update.message.text))

    telegram_app.add_handler(CommandHandler("start", cmd_start))
    telegram_app.add_handler(CommandHandler("help", cmd_help))
    telegram_app.add_handler(CommandHandler("today", cmd_today))
    telegram_app.add_handler(CommandHandler("history", cmd_history))
    telegram_app.add_handler(CommandHandler("plants", cmd_plants))
    telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))


def make_briefing_callback(
    telegram_app: Any, app: BotApp, chat_id: int
) -> Callable[[], Awaitable[None]]:
    """Build the scheduler callback that pushes the daily briefing into the chat."""

    async def fire_daily_briefing() -> None:
        text = await app.today()
        await telegram_app.bot.send_message(chat_id=chat_id, text=text)

    return fire_daily_briefing
