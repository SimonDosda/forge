import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from memory.memory import Entry


_TOPIC_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")


class JsonMemory:
    """One JSON file per topic under `root/`. Each file: {"entries": [...]}."""

    def __init__(self, root: str | Path):
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def get(self, topic: str, entry_id: str | None = None) -> list[Entry]:
        entries = self._load(topic)
        if entry_id is None:
            return entries
        return [e for e in entries if e.id == entry_id]

    def add(self, topic: str, entry: dict[str, Any]) -> Entry:
        now = _now()
        new = Entry(
            id=uuid.uuid4().hex,
            topic=topic,
            data=dict(entry),
            created_at=now,
            updated_at=now,
        )
        entries = self._load(topic)
        entries.append(new)
        self._save(topic, entries)
        return new

    def update(self, topic: str, entry_id: str, entry: dict[str, Any]) -> Entry:
        entries = self._load(topic)
        for i, e in enumerate(entries):
            if e.id == entry_id:
                updated = Entry(
                    id=e.id,
                    topic=e.topic,
                    data=dict(entry),
                    created_at=e.created_at,
                    updated_at=_now(),
                )
                entries[i] = updated
                self._save(topic, entries)
                return updated
        raise KeyError(f"entry {entry_id!r} not found in topic {topic!r}")

    def delete(self, topic: str, entry_id: str) -> None:
        entries = self._load(topic)
        kept = [e for e in entries if e.id != entry_id]
        if len(kept) == len(entries):
            raise KeyError(f"entry {entry_id!r} not found in topic {topic!r}")
        self._save(topic, kept)

    def topics(self) -> list[str]:
        return sorted(p.stem for p in self._root.glob("*.json"))

    # internals

    def _path(self, topic: str) -> Path:
        if not _TOPIC_RE.match(topic):
            raise ValueError(f"invalid topic name: {topic!r}")
        return self._root / f"{topic}.json"

    def _load(self, topic: str) -> list[Entry]:
        path = self._path(topic)
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
        return [
            Entry(
                id=e["id"],
                topic=topic,
                data=e.get("data", {}),
                created_at=e["created_at"],
                updated_at=e["updated_at"],
            )
            for e in payload.get("entries", [])
        ]

    def _save(self, topic: str, entries: list[Entry]) -> None:
        path = self._path(topic)
        payload = {
            "entries": [
                {
                    "id": e.id,
                    "data": e.data,
                    "created_at": e.created_at,
                    "updated_at": e.updated_at,
                }
                for e in entries
            ]
        }
        tmp = path.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
