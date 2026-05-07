"""Spirit: per-golem system prompt + scheduled actions.

The data lives in the forge store (one row per golem). `Spirit` is a thin
view bound to a specific golem name; it re-reads from the store on every
property access so edits made via the forge UI are picked up by the running
body without a restart (the body uses `version` to detect changes).
"""
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

from apscheduler.triggers.cron import CronTrigger

if TYPE_CHECKING:
    from forge.store import ForgeStore


@dataclass(frozen=True)
class Schedule:
    id: str
    cron: dict[str, Any]   # apscheduler cron kwargs (hour, minute, day_of_week, ...)
    prompt: str            # what to ask the Brain when this fires


class InvalidCronError(ValueError):
    """Raised when a Schedule's cron kwargs aren't accepted by APScheduler."""


def validate_cron(cron: dict[str, Any], schedule_id: str = "") -> None:
    """Raise InvalidCronError if `cron` isn't a valid APScheduler CronTrigger spec."""
    try:
        CronTrigger(**cron)
    except (TypeError, ValueError) as exc:
        prefix = f"schedule {schedule_id!r}: " if schedule_id else ""
        raise InvalidCronError(f"{prefix}invalid cron {cron!r} ({exc})") from exc


class Spirit:
    """Live view of one golem's system prompt + schedules, backed by the forge store."""

    def __init__(self, store: "ForgeStore", name: str):
        self._store = store
        self._name = name

    @property
    def system_prompt(self) -> str:
        return self._store.get_golem(self._name).system_prompt

    @property
    def schedules(self) -> list[Schedule]:
        return list(self._store.get_golem(self._name).schedules)

    @property
    def version(self) -> int:
        """Bumps on every store update; used to detect changes for hot-reload."""
        return self._store.get_golem(self._name).version
