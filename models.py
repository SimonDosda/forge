from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum


class ActionType(StrEnum):
    WATERING = "watering"
    PRUNING = "pruning"
    PLANTING = "planting"
    FERTILIZING = "fertilizing"
    OTHER = "other"


@dataclass(frozen=True)
class GardenAction:
    name: str
    type: ActionType
    plants: tuple[str, ...] = field(default_factory=tuple)
    notes: str = ""
    when: date = field(default_factory=date.today)


@dataclass(frozen=True)
class Forecast:
    temp_c: float
    condition: str
    rain_mm_next_3d: float
    uv_index: float


@dataclass(frozen=True)
class Briefing:
    weather_summary: str
    tasks: tuple[str, ...]
