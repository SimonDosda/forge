import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from apscheduler.triggers.cron import CronTrigger


@dataclass(frozen=True)
class Schedule:
    id: str
    cron: dict[str, Any]   # apscheduler cron kwargs (hour, minute, day_of_week, ...)
    prompt: str            # what to ask the Brain when this fires


@dataclass(frozen=True)
class SpiritConfig:
    system_prompt: str = ""
    schedules: tuple[Schedule, ...] = field(default_factory=tuple)


class InvalidCronError(ValueError):
    """Raised when a Schedule's cron kwargs aren't accepted by APScheduler."""


class Spirit:
    """Live, JSON-backed instructions + schedules. Editable at runtime.

    Auto-reloads from disk when the file's mtime advances, so edits made via
    the View are visible to the running bot without a restart.
    """

    def __init__(self, path: str | Path):
        self._path = Path(path)
        self._mtime: float = 0.0
        self._config = SpiritConfig()
        self._reload_if_changed(force=True)

    @property
    def system_prompt(self) -> str:
        self._reload_if_changed()
        return self._config.system_prompt

    @property
    def schedules(self) -> list[Schedule]:
        self._reload_if_changed()
        return list(self._config.schedules)

    @property
    def config(self) -> SpiritConfig:
        self._reload_if_changed()
        return self._config

    @property
    def mtime(self) -> float:
        """File mtime as last observed. Useful as a change-detection token."""
        self._reload_if_changed()
        return self._mtime

    def update(self, config: SpiritConfig) -> None:
        for sched in config.schedules:
            validate_cron(sched.cron, schedule_id=sched.id)
        self._config = config
        self._save()
        try:
            self._mtime = self._path.stat().st_mtime
        except FileNotFoundError:
            pass

    # internals

    def _reload_if_changed(self, force: bool = False) -> None:
        try:
            mtime = self._path.stat().st_mtime
        except FileNotFoundError:
            if force:
                raise FileNotFoundError(
                    f"Spirit config not found at {self._path}. "
                    f"Copy data/spirit.json from the repo or create one."
                )
            return
        if not force and mtime == self._mtime:
            return
        self._config = self._load()
        self._mtime = mtime

    def _load(self) -> SpiritConfig:
        with self._path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
        schedules: list[Schedule] = []
        for s in payload.get("schedules", []):
            sid = str(s["id"])
            cron = dict(s.get("cron", {}))
            try:
                validate_cron(cron, schedule_id=sid)
            except InvalidCronError as exc:
                print(f"[spirit] dropping invalid schedule: {exc}", file=sys.stderr, flush=True)
                continue
            schedules.append(Schedule(id=sid, cron=cron, prompt=str(s.get("prompt", ""))))
        return SpiritConfig(
            system_prompt=str(payload.get("system_prompt", "")),
            schedules=tuple(schedules),
        )

    def _save(self) -> None:
        payload = {
            "system_prompt": self._config.system_prompt,
            "schedules": [asdict(s) for s in self._config.schedules],
        }
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self._path)


def validate_cron(cron: dict[str, Any], schedule_id: str = "") -> None:
    """Raise InvalidCronError if `cron` isn't a valid APScheduler CronTrigger spec."""
    try:
        CronTrigger(**cron)
    except (TypeError, ValueError) as exc:
        prefix = f"schedule {schedule_id!r}: " if schedule_id else ""
        raise InvalidCronError(f"{prefix}invalid cron {cron!r} ({exc})") from exc
