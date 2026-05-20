import logging
from typing import Any

from golem.dialog.dialog import IncomingHandler


_log = logging.getLogger(__name__)


class TelegramDialog:
    def __init__(self, token: str, chat_id: int, app: Any | None = None):
        self._token = token
        self._chat_id = int(chat_id)
        if app is None:
            from telegram.ext import Application
            app = Application.builder().token(token).build()
        self._app = app

    async def send(self, text: str) -> None:
        await self._app.bot.send_message(chat_id=self._chat_id, text=text)

    async def run(self, on_message: IncomingHandler) -> None:
        from telegram.ext import MessageHandler, filters

        async def handler(update, _ctx):
            if not (update.message and update.message.text):
                return
            sender_chat_id = update.effective_chat.id if update.effective_chat else None
            if sender_chat_id != self._chat_id:
                user = update.effective_user
                user_label = f"{user.id} ({user.username or user.full_name})" if user else "unknown"
                _log.warning(
                    "ignored message from unauthorized chat_id=%s user=%s",
                    sender_chat_id, user_label,
                )
                return
            reply = await on_message(update.message.text)
            if reply:
                await update.message.reply_text(reply)

        self._app.add_handler(MessageHandler(filters.TEXT, handler))

        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling()

    async def stop(self) -> None:
        await self._app.updater.stop()
        await self._app.stop()
        await self._app.shutdown()
