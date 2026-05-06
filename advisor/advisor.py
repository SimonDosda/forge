from typing import Protocol

from models import Briefing, GardenAction
from skills.skill import Skill


class Advisor(Protocol):
    def briefing(
        self,
        skills: list[Skill],
        history: list[GardenAction],
        plants: list[str],
        location: dict[str, float],
    ) -> Briefing: ...

    def parse_message(self, text: str) -> list[GardenAction]: ...
