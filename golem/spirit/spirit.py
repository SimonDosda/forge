"""Spirit: per-golem mission prompt + recurring routines.

The data lives in the forge store (one row per golem). `Spirit` is a thin
view bound to a specific golem id; it re-reads from the store on every
property access so edits made via the forge UI are picked up by the running
body without a restart (the body uses `version` to detect changes).
"""
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

from apscheduler.triggers.cron import CronTrigger

if TYPE_CHECKING:
    from forge.store import ForgeStore


@dataclass(frozen=True)
class Routine:
    id: str
    cron: dict[str, Any]   # apscheduler cron kwargs (hour, minute, day_of_week, ...)
    prompt: str            # what to ask the Brain when this fires
    name: str = ""         # human-readable label; falls back to `id` in UI


class InvalidCronError(ValueError):
    """Raised when a Routine's cron kwargs aren't accepted by APScheduler."""


def validate_cron(cron: dict[str, Any], routine_id: str = "") -> None:
    """Raise InvalidCronError if `cron` isn't a valid APScheduler CronTrigger spec."""
    try:
        CronTrigger(**cron)
    except (TypeError, ValueError) as exc:
        prefix = f"routine {routine_id!r}: " if routine_id else ""
        raise InvalidCronError(f"{prefix}invalid cron {cron!r} ({exc})") from exc


class Spirit:
    """Live view of one golem's mission prompt + routines, backed by the forge store."""

    def __init__(self, store: "ForgeStore", id_: str):
        self._store = store
        self._id = id_

    @property
    def mission(self) -> str:
        return self._store.get_golem(self._id).mission

    @property
    def routines(self) -> list[Routine]:
        return list(self._store.get_golem(self._id).routines)

    @property
    def version(self) -> int:
        """Bumps on every store update; used to detect changes for hot-reload."""
        return self._store.get_golem(self._id).version
