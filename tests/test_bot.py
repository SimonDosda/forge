from dataclasses import dataclass, field
from datetime import date

import pytest

from bot import BotApp
from config import Settings
from models import ActionType, Briefing, GardenAction
from skills.skill import SkillAction


@dataclass
class FakeSkill:
    name: str = "fake"
    description: str = "fake skill"
    actions: list[SkillAction] = field(default_factory=list)


@dataclass
class FakeMemory:
    logged: list[GardenAction] = field(default_factory=list)
    history: list[GardenAction] = field(default_factory=list)
    known_plants: list[str] = field(default_factory=list)

    def log_action(self, action: GardenAction) -> None:
        self.logged.append(action)

    def recent_actions(self, limit: int = 30) -> list[GardenAction]:
        return list(self.history[:limit])

    def plants(self) -> list[str]:
        return list(self.known_plants)


@dataclass
class FakeAdvisor:
    next_briefing: Briefing = field(
        default_factory=lambda: Briefing(
            weather_summary="warm and sunny", tasks=("Water the tomatoes",)
        )
    )
    parsed_actions: list[GardenAction] = field(default_factory=list)
    briefing_calls: list[dict] = field(default_factory=list)
    parse_calls: list[str] = field(default_factory=list)

    def briefing(self, skills, history, plants, location):
        self.briefing_calls.append(
            {
                "skills": list(skills),
                "history": list(history),
                "plants": list(plants),
                "location": dict(location),
            }
        )
        return self.next_briefing

    def parse_message(self, text):
        self.parse_calls.append(text)
        return list(self.parsed_actions)


def _settings() -> Settings:
    return Settings(
        telegram_token="tg",
        telegram_chat_id=1,
        mistral_api_key="mk",
        notion_token="nt",
        notion_database_id="nd",
        latitude=48.85,
        longitude=2.35,
        briefing_hour=8,
    )


def _build_app(skills=None, memory=None, advisor=None):
    skills = skills if skills is not None else [FakeSkill()]
    memory = memory or FakeMemory()
    advisor = advisor or FakeAdvisor()
    return (
        BotApp(skills=skills, memory=memory, advisor=advisor, settings=_settings()),
        skills,
        memory,
        advisor,
    )


@pytest.mark.asyncio
async def test_today_passes_skills_history_plants_and_location_to_advisor():
    advisor = FakeAdvisor(
        next_briefing=Briefing(
            weather_summary="21C clear", tasks=("Water tomatoes", "Check basil")
        )
    )
    memory = FakeMemory(
        history=[GardenAction(name="Watered roses", type=ActionType.WATERING)],
        known_plants=["tomatoes", "basil"],
    )
    skill = FakeSkill(name="open_meteo")
    app, _, _, _ = _build_app(skills=[skill], memory=memory, advisor=advisor)

    text = await app.today()

    assert "21C clear" in text
    assert "Water tomatoes" in text
    assert "Check basil" in text

    call = advisor.briefing_calls[0]
    assert call["skills"] == [skill]
    assert call["plants"] == ["tomatoes", "basil"]
    assert call["history"][0].name == "Watered roses"
    assert call["location"] == {"latitude": 48.85, "longitude": 2.35}


@pytest.mark.asyncio
async def test_handle_message_logs_each_parsed_action():
    parsed = [
        GardenAction(name="Watered tomatoes", type=ActionType.WATERING, plants=("tomatoes",), when=date(2026, 5, 6)),
        GardenAction(name="Planted basil", type=ActionType.PLANTING, plants=("basil",), when=date(2026, 5, 6)),
    ]
    advisor = FakeAdvisor(parsed_actions=parsed)
    app, _, memory, _ = _build_app(advisor=advisor)

    reply = await app.handle_message("I watered tomatoes and planted basil")

    assert advisor.parse_calls == ["I watered tomatoes and planted basil"]
    assert [a.name for a in memory.logged] == ["Watered tomatoes", "Planted basil"]
    assert "Watered tomatoes" in reply
    assert "Planted basil" in reply


@pytest.mark.asyncio
async def test_handle_message_when_no_actions_returns_friendly_hint():
    app, _, memory, _ = _build_app(advisor=FakeAdvisor(parsed_actions=[]))

    reply = await app.handle_message("hello")

    assert memory.logged == []
    assert "didn't catch" in reply


@pytest.mark.asyncio
async def test_history_formats_recent_actions():
    memory = FakeMemory(
        history=[
            GardenAction(name="Watered tomatoes", type=ActionType.WATERING, plants=("tomatoes",), when=date(2026, 5, 6)),
            GardenAction(name="Pruned roses", type=ActionType.PRUNING, plants=("roses",), when=date(2026, 5, 5)),
        ]
    )
    app, _, _, _ = _build_app(memory=memory)

    reply = await app.history()

    assert "Watered tomatoes" in reply
    assert "Pruned roses" in reply
    assert "2026-05-06" in reply


@pytest.mark.asyncio
async def test_plants_list_when_empty():
    app, _, _, _ = _build_app(memory=FakeMemory(known_plants=[]))

    reply = await app.plants_list()

    assert "No plants tracked yet" in reply


@pytest.mark.asyncio
async def test_plants_list_with_plants():
    app, _, _, _ = _build_app(memory=FakeMemory(known_plants=["tomatoes", "roses"]))

    reply = await app.plants_list()

    assert "tomatoes" in reply
    assert "roses" in reply


@dataclass
class _StubTelegramApp:
    handlers: list = field(default_factory=list)
    polled: bool = False

    def add_handler(self, handler):
        self.handlers.append(handler)

    def run_polling(self):
        self.polled = True


@dataclass
class _StubScheduler:
    jobs: list[tuple[int, object]] = field(default_factory=list)
    started: bool = False

    def daily(self, hour: int, callback) -> None:
        self.jobs.append((hour, callback))

    def start(self) -> None:
        self.started = True


def test_run_registers_handlers_schedules_briefing_and_starts_polling():
    app, _, _, _ = _build_app()
    telegram = _StubTelegramApp()
    scheduler = _StubScheduler()

    app.run(telegram_app=telegram, scheduler=scheduler)

    assert len(telegram.handlers) >= 6
    assert len(scheduler.jobs) == 1
    assert scheduler.jobs[0][0] == 8
    assert scheduler.started
    assert telegram.polled
