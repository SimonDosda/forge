import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Schedule:
    id: str
    cron: dict[str, Any]   # apscheduler cron kwargs (hour, minute, day_of_week, ...)
    prompt: str            # what to ask the Brain when this fires


@dataclass(frozen=True)
class SpiritConfig:
    system_prompt: str = ""
    schedules: tuple[Schedule, ...] = field(default_factory=tuple)


class Spirit:
    """Live, JSON-backed instructions + schedules. Editable at runtime."""

    def __init__(self, path: str | Path):
        self._path = Path(path)
        self._config = self._load()

    @property
    def system_prompt(self) -> str:
        return self._config.system_prompt

    @property
    def schedules(self) -> list[Schedule]:
        return list(self._config.schedules)

    @property
    def config(self) -> SpiritConfig:
        return self._config

    def update(self, config: SpiritConfig) -> None:
        self._config = config
        self._save()

    # internals

    def _load(self) -> SpiritConfig:
        if not self._path.exists():
            raise FileNotFoundError(
                f"Spirit config not found at {self._path}. "
                f"Copy data/spirit.json from the repo or create one."
            )
        with self._path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
        return SpiritConfig(
            system_prompt=str(payload.get("system_prompt", "")),
            schedules=tuple(
                Schedule(
                    id=str(s["id"]),
                    cron=dict(s.get("cron", {})),
                    prompt=str(s.get("prompt", "")),
                )
                for s in payload.get("schedules", [])
            ),
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
