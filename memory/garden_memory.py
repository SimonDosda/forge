from typing import Protocol

from models import GardenAction


class GardenMemory(Protocol):
    def log_action(self, action: GardenAction) -> None: ...

    def recent_actions(self, limit: int = 30) -> list[GardenAction]: ...

    def plants(self) -> list[str]: ...
