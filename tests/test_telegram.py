from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from bot import BotApp
from communication.telegram import make_briefing_callback, register_handlers
from config import Settings
from models import Briefing


@dataclass
class _StubTelegramApp:
    handlers: list = field(default_factory=list)

    def add_handler(self, handler):
        self.handlers.append(handler)


@dataclass
class _StubBot:
    sent: list[dict] = field(default_factory=list)

    async def send_message(self, chat_id: int, text: str):
        self.sent.append({"chat_id": chat_id, "text": text})


@dataclass
class _StubMessage:
    text: str = ""
    replies: list[str] = field(default_factory=list)

    async def reply_text(self, text: str):
        self.replies.append(text)


def _settings() -> Settings:
    return Settings(
        telegram_token="tg",
        telegram_chat_id=42,
        mistral_api_key="mk",
        notion_token="nt",
        notion_database_id="nd",
        latitude=0.0,
        longitude=0.0,
        briefing_hour=8,
    )


class _RecordingApp:
    """Minimal BotApp stand-in that records which method was called."""

    def __init__(self):
        self.calls: list[str] = []

    async def today(self):
        self.calls.append("today")
        return "TODAY"

    async def history(self):
        self.calls.append("history")
        return "HISTORY"

    async def plants_list(self):
        self.calls.append("plants_list")
        return "PLANTS"

    async def handle_message(self, text: str):
        self.calls.append(f"handle_message:{text}")
        return f"echo:{text}"


def test_register_handlers_registers_all_commands_plus_message():
    from telegram.ext import CommandHandler, MessageHandler

    stub = _StubTelegramApp()
    register_handlers(stub, _RecordingApp())

    command_handlers = [h for h in stub.handlers if isinstance(h, CommandHandler)]
    message_handlers = [h for h in stub.handlers if isinstance(h, MessageHandler)]

    registered_commands = {cmd for h in command_handlers for cmd in h.commands}
    assert registered_commands == {"start", "help", "today", "history", "plants"}
    assert len(message_handlers) == 1


@pytest.mark.asyncio
async def test_today_handler_delegates_to_app():
    from telegram.ext import CommandHandler

    stub = _StubTelegramApp()
    app = _RecordingApp()
    register_handlers(stub, app)

    today_handler = next(
        h for h in stub.handlers if isinstance(h, CommandHandler) and "today" in h.commands
    )
    message = _StubMessage()
    update = SimpleNamespace(message=message)

    await today_handler.callback(update, None)

    assert app.calls == ["today"]
    assert message.replies == ["TODAY"]


@pytest.mark.asyncio
async def test_message_handler_passes_text_to_app():
    from telegram.ext import MessageHandler

    stub = _StubTelegramApp()
    app = _RecordingApp()
    register_handlers(stub, app)

    msg_handler = next(h for h in stub.handlers if isinstance(h, MessageHandler))
    message = _StubMessage(text="I watered the basil")
    update = SimpleNamespace(message=message)

    await msg_handler.callback(update, None)

    assert app.calls == ["handle_message:I watered the basil"]
    assert message.replies == ["echo:I watered the basil"]


@pytest.mark.asyncio
async def test_briefing_callback_sends_today_to_configured_chat_id():
    bot = _StubBot()
    telegram_app = SimpleNamespace(bot=bot)
    app = _RecordingApp()

    callback = make_briefing_callback(telegram_app, app, chat_id=42)
    await callback()

    assert app.calls == ["today"]
    assert bot.sent == [{"chat_id": 42, "text": "TODAY"}]
