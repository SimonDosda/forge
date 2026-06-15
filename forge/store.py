"""Forge data store: TinyDB-backed golem registry.

A `GolemSpec` is a complete bot definition: id + name + enabled flag + brain
config + dialog config + spirit prompt + routines + skill allowlist. The
forge UI edits these; the supervisor reads them at awake time to wire up
Golem instances.

Storage: data/forge.json — one TinyDB table `golems`, with `id` as the
stable primary key (it is never modified after creation; renames only change
`name`). `version` bumps on every update, used by the running golem to
detect Spirit edits and hot-reload routines.
"""
import re
import threading
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from tinydb import Query, TinyDB
from tinydb.operations import delete

from golem.spirit.spirit import Routine, validate_cron


_ID_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")
_ID_UNSAFE_RE = re.compile(r"[^a-zA-Z0-9_\-]+")


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
class TopicSpec:
    """Per-topic configuration. The description is injected into the mission
    prompt so the brain knows the topic's purpose and conventions without
    repeating them in the main mission text.
    """
    id: str
    description: str = ""


@dataclass(frozen=True)
class GolemSpec:
    id: str = ""           # stable primary key; immutable after creation
    name: str = ""
    description: str = ""  # short human description, shown in the forge list
    enabled: bool = False
    brain: BrainSpec = field(default_factory=BrainSpec)
    dialog: DialogSpec = field(default_factory=DialogSpec)
    mission: str = ""
    routines: tuple[Routine, ...] = ()
    topics: tuple[TopicSpec, ...] = ()
    skills: tuple[str, ...] = ()
    # Per-skill configuration (e.g. {"notion": {"api_key": "..."}}).
    skill_configs: dict[str, dict[str, str]] = field(default_factory=dict)
    version: int = 0


class GolemNotFoundError(KeyError):
    pass


class GolemExistsError(ValueError):
    pass


def validate_name(name: str) -> None:
    """Display name: any non-empty string (trimmed)."""
    if not name or not name.strip():
        raise ValueError("golem name cannot be empty")


def slugify_id(name: str) -> str:
    """Derive a filesystem-safe id from a free-form name.

    Spaces and unsafe characters become '_'; runs are collapsed; leading/trailing
    underscores are stripped. Falls back to 'golem' if nothing is left.
    """
    slug = _ID_UNSAFE_RE.sub("_", name.strip())
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug or "golem"


class ForgeStore:
    """Thin TinyDB wrapper for golem CRUD, keyed by stable `id`."""

    def __init__(self, path: str | Path = "data/forge.json"):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._db = TinyDB(str(self._path), indent=2, ensure_ascii=False)
        except PermissionError as exc:
            raise PermissionError(
                f"cannot open forge database at {self._path!s}: ensure the runtime user can write to {self._path.parent!s}"
            ) from exc
        self._lock = threading.Lock()
        self._backfill_ids()

    @property
    def path(self) -> Path:
        return self._path

    def _backfill_ids(self) -> None:
        """Migrate legacy storage layout:
        - older rows were keyed by `name` only — backfill `id = name`;
        - older rows used `system_prompt` / `spirit` for the mission prompt and
          `schedules` for routines — rename to `mission` / `routines` so existing
          data keeps resolving after the field renames.
        """
        with self._lock:
            t = self._db.table("golems")
            for doc in t.all():
                doc_id = doc.doc_id
                updates: dict[str, Any] = {}
                if not doc.get("id"):
                    updates["id"] = doc.get("name", "")
                if "mission" not in doc:
                    if "spirit" in doc:
                        updates["mission"] = doc["spirit"]
                    elif "system_prompt" in doc:
                        updates["mission"] = doc["system_prompt"]
                if "schedules" in doc and "routines" not in doc:
                    updates["routines"] = doc["schedules"]
                if updates:
                    t.update(updates, doc_ids=[doc_id])
                # Drop the now-stale legacy keys.
                for legacy in ("system_prompt", "spirit", "schedules"):
                    if legacy in doc:
                        t.update(delete(legacy), doc_ids=[doc_id])

    def list_golems(self) -> list[GolemSpec]:
        with self._lock:
            return [_to_spec(d) for d in self._db.table("golems").all()]

    def list_enabled(self) -> list[GolemSpec]:
        return [g for g in self.list_golems() if g.enabled]

    def get_golem(self, id_: str) -> GolemSpec:
        with self._lock:
            docs = self._db.table("golems").search(Query().id == id_)
        if not docs:
            raise GolemNotFoundError(id_)
        return _to_spec(docs[0])

    def has_golem(self, id_: str) -> bool:
        with self._lock:
            return bool(self._db.table("golems").search(Query().id == id_))

    def create_golem(self, spec: GolemSpec) -> GolemSpec:
        validate_name(spec.name)
        for r in spec.routines:
            validate_cron(r.cron, routine_id=r.id)
        with self._lock:
            t = self._db.table("golems")
            if t.search(Query().name == spec.name):
                raise GolemExistsError(spec.name)
            if spec.id:
                if not _ID_RE.match(spec.id):
                    raise ValueError(
                        f"invalid golem id: {spec.id!r} (allowed: letters, digits, '_', '-')"
                    )
                new_id = spec.id
            else:
                new_id = _make_unique_id(spec.name, t)
            if t.search(Query().id == new_id):
                raise GolemExistsError(f"id {new_id!r} already exists")
            new = replace(spec, id=new_id, version=1)
            t.insert(_to_doc(new))
            return new

    def update_golem(self, id_: str, spec: GolemSpec) -> GolemSpec:
        # The id is the stable key — force it onto the spec to prevent accidental change.
        for r in spec.routines:
            validate_cron(r.cron, routine_id=r.id)
        validate_name(spec.name)
        with self._lock:
            t = self._db.table("golems")
            existing = t.search(Query().id == id_)
            if not existing:
                raise GolemNotFoundError(id_)
            if spec.name != existing[0].get("name") and t.search(
                (Query().name == spec.name) & (Query().id != id_)
            ):
                raise GolemExistsError(spec.name)
            new = replace(
                spec,
                id=id_,
                version=int(existing[0].get("version", 0)) + 1,
            )
            t.update(_to_doc(new), Query().id == id_)
            return new

    def delete_golem(self, id_: str) -> None:
        with self._lock:
            removed = self._db.table("golems").remove(Query().id == id_)
        if not removed:
            raise GolemNotFoundError(id_)


def _make_unique_id(name: str, table) -> str:
    """Derive a stable, filesystem-safe id from `name`, falling back to a
    numeric suffix on collision."""
    base = slugify_id(name)
    candidate = base
    n = 2
    while table.search(Query().id == candidate):
        candidate = f"{base}_{n}"
        n += 1
    return candidate


def _to_doc(spec: GolemSpec) -> dict[str, Any]:
    return {
        "id": spec.id,
        "name": spec.name,
        "description": spec.description,
        "enabled": spec.enabled,
        "brain": asdict(spec.brain),
        "dialog": {
            "kind": spec.dialog.kind,
            "telegram": asdict(spec.dialog.telegram),
        },
        "mission": spec.mission,
        "routines": [asdict(r) for r in spec.routines],
        "topics": [asdict(t) for t in spec.topics],
        "skills": list(spec.skills),
        "skill_configs": {k: dict(v) for k, v in spec.skill_configs.items()},
        "version": spec.version,
    }


def _to_spec(doc: dict[str, Any]) -> GolemSpec:
    brain = doc.get("brain") or {}
    dialog_doc = doc.get("dialog") or {}
    tg = dialog_doc.get("telegram") or {}
    routines = tuple(
        Routine(
            id=str(r["id"]),
            cron=dict(r.get("cron", {})),
            prompt=str(r.get("prompt", "")),
            name=str(r.get("name", "")),
        )
        for r in doc.get("routines", [])
    )
    return GolemSpec(
        id=str(doc.get("id") or doc.get("name", "")),
        name=str(doc.get("name", "")),
        description=str(doc.get("description", "")),
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
        mission=str(doc.get("mission", "")),
        routines=routines,
        topics=tuple(
            TopicSpec(
                id=str(t["id"]),
                description=str(t.get("description", "")),
            )
            for t in doc.get("topics", [])
            if t.get("id")
        ),
        skills=tuple(str(s) for s in doc.get("skills", [])),
        skill_configs={
            str(k): {str(kk): str(vv) for kk, vv in (v or {}).items()}
            for k, v in (doc.get("skill_configs") or {}).items()
        },
        version=int(doc.get("version", 0)),
    )
