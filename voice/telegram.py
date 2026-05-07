from typing import Any

from voice.voice import IncomingHandler


class TelegramVoice:
    def __init__(self, token: str, chat_id: int, app: Any | None = None):
        self._token = token
        self._chat_id = chat_id
        if app is None:
            from telegram.ext import Application
            app = Application.builder().token(token).build()
        self._app = app

    async def send(self, text: str) -> None:
        await self._app.bot.send_message(chat_id=self._chat_id, text=text)

    async def run(self, on_message: IncomingHandler) -> None:
        from telegram.ext import MessageHandler, filters

        async def handler(update, _ctx):
            if update.message and update.message.text:
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
