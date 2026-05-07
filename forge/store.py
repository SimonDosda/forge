"""Forge data store: TinyDB-backed golem registry.

A `GolemSpec` is a complete bot definition: name + enabled flag + brain config
+ dialog config + system prompt + schedules + skill allowlist. The forge UI
edits these; the supervisor reads them at awake time to wire up Golem instances.

Storage: data/forge.json — one TinyDB table `golems`, with `name` as the
unique key. `version` bumps on every update, used by the running golem to
detect Spirit edits and hot-reload schedules.
"""
import re
import threading
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from tinydb import Query, TinyDB

from golem.spirit.spirit import Schedule, validate_cron


_NAME_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")


@dataclass(frozen=True)
class BrainSpec:
    provider: str = "mistral"
    model: str = ""
    api_key: str = ""
    base_url: str = ""


@dataclass(frozen=True)
class TelegramSpec:
    token: str = ""
    chat_id: int = 0


@dataclass(frozen=True)
class DialogSpec:
    kind: str = "telegram"
    telegram: TelegramSpec = field(default_factory=TelegramSpec)


@dataclass(frozen=True)
class GolemSpec:
    name: str
    enabled: bool = False
    brain: BrainSpec = field(default_factory=BrainSpec)
    dialog: DialogSpec = field(default_factory=DialogSpec)
    system_prompt: str = ""
    schedules: tuple[Schedule, ...] = ()
    skills: tuple[str, ...] = ()
    version: int = 0


class GolemNotFoundError(KeyError):
    pass


class GolemExistsError(ValueError):
    pass


def validate_name(name: str) -> None:
    if not _NAME_RE.match(name):
        raise ValueError(
            f"invalid golem name: {name!r} (allowed: letters, digits, '_', '-')"
        )


class ForgeStore:
    """Thin TinyDB wrapper for golem CRUD."""

    def __init__(self, path: str | Path = "data/forge.json"):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._db = TinyDB(str(self._path), indent=2, ensure_ascii=False)
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def list_golems(self) -> list[GolemSpec]:
        with self._lock:
            return [_to_spec(d) for d in self._db.table("golems").all()]

    def list_enabled(self) -> list[GolemSpec]:
        return [g for g in self.list_golems() if g.enabled]

    def get_golem(self, name: str) -> GolemSpec:
        with self._lock:
            docs = self._db.table("golems").search(Query().name == name)
        if not docs:
            raise GolemNotFoundError(name)
        return _to_spec(docs[0])

    def has_golem(self, name: str) -> bool:
        with self._lock:
            return bool(self._db.table("golems").search(Query().name == name))

    def create_golem(self, spec: GolemSpec) -> GolemSpec:
        validate_name(spec.name)
        for sc in spec.schedules:
            validate_cron(sc.cron, schedule_id=sc.id)
        with self._lock:
            t = self._db.table("golems")
            if t.search(Query().name == spec.name):
                raise GolemExistsError(spec.name)
            new = replace(spec, version=1)
            t.insert(_to_doc(new))
            return new

    def update_golem(self, name: str, spec: GolemSpec) -> GolemSpec:
        # Renaming via update: validate the new name; the row still keyed by `name`.
        if spec.name != name:
            validate_name(spec.name)
        for sc in spec.schedules:
            validate_cron(sc.cron, schedule_id=sc.id)
        with self._lock:
            t = self._db.table("golems")
            existing = t.search(Query().name == name)
            if not existing:
                raise GolemNotFoundError(name)
            if spec.name != name and t.search(Query().name == spec.name):
                raise GolemExistsError(spec.name)
            new = replace(spec, version=int(existing[0].get("version", 0)) + 1)
            t.update(_to_doc(new), Query().name == name)
            return new

    def delete_golem(self, name: str) -> None:
        with self._lock:
            removed = self._db.table("golems").remove(Query().name == name)
        if not removed:
            raise GolemNotFoundError(name)


def _to_doc(spec: GolemSpec) -> dict[str, Any]:
    return {
        "name": spec.name,
        "enabled": spec.enabled,
        "brain": asdict(spec.brain),
        "dialog": {
            "kind": spec.dialog.kind,
            "telegram": asdict(spec.dialog.telegram),
        },
        "system_prompt": spec.system_prompt,
        "schedules": [asdict(s) for s in spec.schedules],
        "skills": list(spec.skills),
        "version": spec.version,
    }


def _to_spec(doc: dict[str, Any]) -> GolemSpec:
    brain = doc.get("brain") or {}
    dialog_doc = doc.get("dialog") or {}
    tg = dialog_doc.get("telegram") or {}
    schedules = tuple(
        Schedule(
            id=str(s["id"]),
            cron=dict(s.get("cron", {})),
            prompt=str(s.get("prompt", "")),
        )
        for s in doc.get("schedules", [])
    )
    return GolemSpec(
        name=str(doc["name"]),
        enabled=bool(doc.get("enabled", False)),
        brain=BrainSpec(
            provider=str(brain.get("provider", "mistral")),
            model=str(brain.get("model", "")),
            api_key=str(brain.get("api_key", "")),
            base_url=str(brain.get("base_url", "")),
        ),
        dialog=DialogSpec(
            kind=str(dialog_doc.get("kind", "telegram")),
            telegram=TelegramSpec(
                token=str(tg.get("token", "")),
                chat_id=int(tg.get("chat_id", 0) or 0),
            ),
        ),
        system_prompt=str(doc.get("system_prompt", "")),
        schedules=schedules,
        skills=tuple(str(s) for s in doc.get("skills", [])),
        version=int(doc.get("version", 0)),
    )
