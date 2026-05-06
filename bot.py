from advisor.advisor import Advisor
from config import Settings
from memory.garden_memory import GardenMemory
from models import Briefing, GardenAction
from skills.skill import Skill


HELP_TEXT = (
    "Available commands:\n"
    "/today — Today's task list\n"
    "/history — Last 10 logged actions\n"
    "/plants — Plants in your garden\n"
    "/help — Show this help\n\n"
    "Or just send a free-form message to log an action."
)

START_TEXT = (
    "🌱 Welcome to your Garden Assistant!\n\n"
    "I send a daily briefing every morning. You can also tell me "
    "what you did in the garden and I'll log it to Notion.\n\n" + HELP_TEXT
)


class BotApp:
    """Pure-logic application — depends only on Protocols, never on telegram/notion/etc."""

    def __init__(
        self,
        skills: list[Skill],
        memory: GardenMemory,
        advisor: Advisor,
        settings: Settings,
    ):
        self._skills = skills
        self._memory = memory
        self._advisor = advisor
        self._settings = settings

    async def today(self) -> str:
        history = self._memory.recent_actions(limit=30)
        plants = self._memory.plants()
        briefing = self._advisor.briefing(
            skills=self._skills,
            history=history,
            plants=plants,
            location={
                "latitude": self._settings.latitude,
                "longitude": self._settings.longitude,
            },
        )
        return _format_briefing(briefing)

    async def history(self) -> str:
        actions = self._memory.recent_actions(limit=10)
        return _format_history(actions)

    async def plants_list(self) -> str:
        return _format_plants(self._memory.plants())

    async def handle_message(self, text: str) -> str:
        actions = self._advisor.parse_message(text)
        for action in actions:
            self._memory.log_action(action)
        return _format_log_confirmation(actions)

    def run(self, telegram_app=None, scheduler=None) -> None:
        """Wire the bot to Telegram + scheduler and start the polling loop."""
        from communication.scheduler import Scheduler
        from communication.telegram import (
            build_app,
            make_briefing_callback,
            register_handlers,
        )

        self._telegram_app = telegram_app or build_app(self._settings.telegram_token)
        self._scheduler = scheduler or Scheduler()

        register_handlers(self._telegram_app, self)
        self._scheduler.daily(
            hour=self._settings.briefing_hour,
            callback=make_briefing_callback(
                self._telegram_app, self, self._settings.telegram_chat_id
            ),
        )
        self._scheduler.start()
        self._telegram_app.run_polling()


def _format_briefing(briefing: Briefing) -> str:
    lines = ["🌱 Good morning! Here are your garden tasks for today", ""]
    if briefing.weather_summary:
        lines.append(f"🌤️ Weather: {briefing.weather_summary}")
        lines.append("")
    if briefing.tasks:
        lines.append("✅ Things to do today:")
        lines.extend(f"- {t}" for t in briefing.tasks)
    else:
        lines.append("Nothing urgent today — enjoy the garden 🌿")
    return "\n".join(lines)


def _format_history(actions: list[GardenAction]) -> str:
    if not actions:
        return "No actions logged yet."
    lines = ["Last actions:"]
    for a in actions:
        plants = f" ({', '.join(a.plants)})" if a.plants else ""
        lines.append(f"- {a.when.isoformat()} — {a.name}{plants}")
    return "\n".join(lines)


def _format_plants(plants: list[str]) -> str:
    if not plants:
        return "No plants tracked yet. Log an action mentioning a plant to add it."
    return "🌿 Plants in your garden:\n" + "\n".join(f"- {p}" for p in plants)


def _format_log_confirmation(actions: list[GardenAction]) -> str:
    if not actions:
        return "I didn't catch any garden action there. Try something like \"watered the tomatoes\"."
    lines = ["✅ Logged! I've saved:"]
    for a in actions:
        plants = f" ({', '.join(a.plants)})" if a.plants else ""
        lines.append(f"- {a.name}{plants} on {a.when.strftime('%b %-d')}")
    return "\n".join(lines)


def main() -> None:  # pragma: no cover - exercised end-to-end, not in unit tests
    import config
    from advisor.mistral import MistralAdvisor
    from memory.notion import NotionMemory
    from skills.open_meteo import OpenMeteo

    settings = config.load()
    app = BotApp(
        skills=[OpenMeteo()],
        memory=NotionMemory(settings.notion_token, settings.notion_database_id),
        advisor=MistralAdvisor(settings.mistral_api_key),
        settings=settings,
    )
    app.run()


if __name__ == "__main__":
    main()
