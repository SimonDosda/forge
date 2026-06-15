import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tinydb import Query, TinyDB
from tinydb.storages import JSONStorage, touch

from golem.memory.memory import Entry


_TOPIC_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")


class _AtomicJSONStorage(JSONStorage):
    """JSONStorage variant that writes via tmp + os.replace for crash safety."""

    def __init__(self, path: str, create_dirs: bool = False, encoding: str | None = None, access_mode: str = "r+", **kwargs: Any):
        self._path = path
        self._encoding = encoding
        self._kwargs = kwargs
        touch(path, create_dirs=create_dirs)
        self._handle = open(path, mode=access_mode, encoding=encoding)

    def write(self, data: dict[str, dict[str, Any]]) -> None:
        serialized = json.dumps(data, **self._kwargs)
        tmp = f"{self._path}.tmp"
        with open(tmp, "w", encoding=self._encoding) as f:
            f.write(serialized)
        os.replace(tmp, self._path)
        self._handle.close()
        self._handle = open(self._path, mode="r+", encoding=self._encoding)


class TinyDbMemory:
    """Single-file TinyDB store. One table per topic."""

    def __init__(self, path: str | Path):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._db = TinyDB(
                str(self._path),
                storage=_AtomicJSONStorage,
                indent=2,
                ensure_ascii=False,
            )
        except PermissionError as exc:
            raise PermissionError(
                f"cannot open memory store at {self._path!s}: ensure the runtime user can write to {self._path.parent!s}"
            ) from exc

    def get(self, topic: str, entry_id: str | None = None) -> list[Entry]:
        table = self._table(topic)
        docs = table.all() if entry_id is None else table.search(Query().id == entry_id)
        return [_to_entry(topic, d) for d in docs]

    def add(self, topic: str, entry: dict[str, Any]) -> Entry:
        now = _now()
        new = Entry(
            id=uuid.uuid4().hex,
            topic=topic,
            data=dict(entry),
            created_at=now,
            updated_at=now,
        )
        self._table(topic).insert(_to_doc(new))
        return new

    def update(self, topic: str, entry_id: str, entry: dict[str, Any]) -> Entry:
        table = self._table(topic)
        existing = table.search(Query().id == entry_id)
        if not existing:
            raise KeyError(f"entry {entry_id!r} not found in topic {topic!r}")
        old = existing[0]
        updated = Entry(
            id=entry_id,
            topic=topic,
            data=dict(entry),
            created_at=old["created_at"],
            updated_at=_now(),
        )
        table.update(_to_doc(updated), Query().id == entry_id)
        return updated

    def delete(self, topic: str, entry_id: str) -> None:
        removed = self._table(topic).remove(Query().id == entry_id)
        if not removed:
            raise KeyError(f"entry {entry_id!r} not found in topic {topic!r}")

    def topics(self) -> list[str]:
        return sorted(name for name in self._db.tables() if name != "_default")

    def _table(self, topic: str):
        if not _TOPIC_RE.match(topic):
            raise ValueError(f"invalid topic name: {topic!r}")
        return self._db.table(topic)


def _to_doc(e: Entry) -> dict[str, Any]:
    return {
        "id": e.id,
        "data": e.data,
        "created_at": e.created_at,
        "updated_at": e.updated_at,
    }


def _to_entry(topic: str, doc: dict[str, Any]) -> Entry:
    return Entry(
        id=doc["id"],
        topic=topic,
        data=doc.get("data", {}),
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
