from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class Entry:
    id: str
    topic: str
    data: dict[str, Any]
    created_at: str   # ISO-8601 UTC
    updated_at: str


class Memory(Protocol):
    def get(self, topic: str, entry_id: str | None = None) -> list[Entry]: ...
    def add(self, topic: str, entry: dict[str, Any]) -> Entry: ...
    def update(self, topic: str, entry_id: str, entry: dict[str, Any]) -> Entry: ...
    def delete(self, topic: str, entry_id: str) -> None: ...
    def topics(self) -> list[str]: ...
