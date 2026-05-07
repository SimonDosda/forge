"""Forge — browser UI for creating, configuring, waking, and managing golems.

Run with: uv run golem forge
"""
import os
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from forge.migration import migrate_legacy_if_needed
from forge.store import (
    BrainSpec,
    DialogSpec,
    ForgeStore,
    GolemExistsError,
    GolemNotFoundError,
    GolemSpec,
    TelegramSpec,
    TopicSpec,
)
from forge.supervisor import Supervisor
from golem.memory.tinydb_store import TinyDbMemory
from golem.skills import available_skill_names, describe_skills
from golem.spirit.spirit import InvalidCronError, Routine


_HERE = Path(__file__).resolve().parent
_STATIC = _HERE / "static"


# ---------- API models ----------

class BrainModel(BaseModel):
    provider: str = "mistral"
    model: str = ""
    api_key: str = ""
    base_url: str = ""


class TelegramModel(BaseModel):
    token: str = ""
    chat_id: int = 0


class DialogModel(BaseModel):
    kind: str = "telegram"
    telegram: TelegramModel = Field(default_factory=TelegramModel)


class RoutineModel(BaseModel):
    id: str
    cron: dict[str, Any]
    prompt: str
    name: str = ""


class TopicModel(BaseModel):
    id: str
    description: str = ""


class GolemModel(BaseModel):
    id: str = ""
    name: str
    description: str = ""
    enabled: bool = False
    brain: BrainModel = Field(default_factory=BrainModel)
    dialog: DialogModel = Field(default_factory=DialogModel)
    mission: str = ""
    routines: list[RoutineModel] = Field(default_factory=list)
    topics: list[TopicModel] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)


class EntryUpdate(BaseModel):
    data: dict[str, Any]


class DialogSend(BaseModel):
    text: str


# ---------- App ----------

def build_app(env_path: str = ".env") -> FastAPI:
    load_dotenv(env_path, override=False)

    store = ForgeStore()
    migrate_legacy_if_needed(store)
    supervisor = Supervisor(store)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await supervisor.autowake_enabled()
        try:
            yield
        finally:
            await supervisor.shutdown()

    app = FastAPI(title="Golem — Forge", lifespan=lifespan)

    def _memory_for(id_: str) -> TinyDbMemory:
        return TinyDbMemory(f"data/{id_}/memory.json")

    # ---- Skills (registry, read-only) ----

    @app.get("/api/skills")
    def list_skills() -> dict[str, Any]:
        # MemorySkill needs a Memory but doesn't query it during describe.
        sample = TinyDbMemory("data/_describe/memory.json")
        return {
            "available": available_skill_names(),
            "describe": describe_skills(sample),
        }

    # ---- Golems ----

    @app.get("/api/golems")
    def list_golems() -> list[dict[str, Any]]:
        return [_to_summary(g, supervisor) for g in store.list_golems()]

    @app.post("/api/golems")
    async def create_golem(payload: GolemModel) -> dict[str, Any]:
        spec = _from_payload(payload)
        try:
            new = store.create_golem(spec)
        except GolemExistsError as exc:
            raise HTTPException(409, str(exc))
        except (ValueError, InvalidCronError) as exc:
            raise HTTPException(400, str(exc))
        if new.enabled:
            try:
                await supervisor.awake(new.id)
            except Exception as exc:  # noqa: BLE001
                # Creation succeeded; surface the autowake failure as a soft warning.
                return _to_full(new, supervisor) | {"awake_error": str(exc)}
        return _to_full(new, supervisor)

    @app.get("/api/golems/{id_}")
    def get_golem(id_: str) -> dict[str, Any]:
        try:
            return _to_full(store.get_golem(id_), supervisor)
        except GolemNotFoundError:
            raise HTTPException(404, f"golem {id_!r} not found")

    @app.put("/api/golems/{id_}")
    async def update_golem(id_: str, payload: GolemModel) -> dict[str, Any]:
        spec = _from_payload(payload)
        was_running = supervisor.is_awake(id_)
        try:
            updated = store.update_golem(id_, spec)
        except GolemNotFoundError:
            raise HTTPException(404, f"golem {id_!r} not found")
        except GolemExistsError as exc:
            raise HTTPException(409, str(exc))
        except (ValueError, InvalidCronError) as exc:
            raise HTTPException(400, str(exc))
        # Auto-apply config changes to a running instance.
        if was_running:
            try:
                await supervisor.reshape(id_)
            except Exception as exc:  # noqa: BLE001
                return _to_full(updated, supervisor) | {"reshape_error": str(exc)}
        return _to_full(updated, supervisor)

    @app.delete("/api/golems/{id_}")
    async def delete_golem(id_: str) -> dict[str, str]:
        await supervisor.sleep(id_)
        try:
            store.delete_golem(id_)
        except GolemNotFoundError:
            raise HTTPException(404, f"golem {id_!r} not found")
        return {"status": "ok"}

    # ---- Per-golem lifecycle ----

    @app.post("/api/golems/{id_}/awake")
    async def awake_golem(id_: str) -> dict[str, Any]:
        if not store.has_golem(id_):
            raise HTTPException(404, f"golem {id_!r} not found")
        try:
            await supervisor.awake(id_)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, f"failed to awake: {exc}")
        return {"status": "ok", "running": True}

    @app.post("/api/golems/{id_}/sleep")
    async def sleep_golem(id_: str) -> dict[str, Any]:
        await supervisor.sleep(id_)
        return {"status": "ok", "running": False}

    @app.post("/api/golems/{id_}/reshape")
    async def reshape_golem(id_: str) -> dict[str, Any]:
        if not store.has_golem(id_):
            raise HTTPException(404, f"golem {id_!r} not found")
        try:
            await supervisor.reshape(id_)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, f"failed to reshape: {exc}")
        return {"status": "ok", "running": supervisor.is_awake(id_)}

    # ---- Per-golem dialog (Telegram one-shot send) ----

    @app.post("/api/golems/{id_}/dialog/send")
    async def dialog_send(id_: str, body: DialogSend) -> dict[str, str]:
        try:
            spec = store.get_golem(id_)
        except GolemNotFoundError:
            raise HTTPException(404, f"golem {id_!r} not found")
        if spec.dialog.kind != "telegram":
            raise HTTPException(400, f"unsupported dialog kind: {spec.dialog.kind!r}")
        tg = spec.dialog.telegram
        if not tg.token or not tg.chat_id:
            raise HTTPException(400, "telegram token and chat_id must be set")
        from telegram import Bot
        await Bot(token=tg.token).send_message(chat_id=tg.chat_id, text=body.text)
        return {"status": "ok"}

    # ---- Per-golem memory ----

    @app.get("/api/golems/{id_}/memory/topics")
    def list_topics(id_: str) -> list[str]:
        _require_golem(store, id_)
        return _memory_for(id_).topics()

    @app.get("/api/golems/{id_}/memory/{topic}")
    def list_entries(id_: str, topic: str) -> list[dict]:
        _require_golem(store, id_)
        return [
            {
                "id": e.id,
                "data": e.data,
                "created_at": e.created_at,
                "updated_at": e.updated_at,
            }
            for e in _memory_for(id_).get(topic)
        ]

    @app.post("/api/golems/{id_}/memory/{topic}")
    def add_entry(id_: str, topic: str, body: EntryUpdate) -> dict:
        _require_golem(store, id_)
        e = _memory_for(id_).add(topic, body.data)
        return {"id": e.id}

    @app.put("/api/golems/{id_}/memory/{topic}/{entry_id}")
    def update_entry(id_: str, topic: str, entry_id: str, body: EntryUpdate) -> dict:
        _require_golem(store, id_)
        try:
            _memory_for(id_).update(topic, entry_id, body.data)
        except KeyError as exc:
            raise HTTPException(404, str(exc))
        return {"status": "ok"}

    @app.delete("/api/golems/{id_}/memory/{topic}/{entry_id}")
    def delete_entry(id_: str, topic: str, entry_id: str) -> dict:
        _require_golem(store, id_)
        try:
            _memory_for(id_).delete(topic, entry_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc))
        return {"status": "ok"}

    # ---- Static ----

    if _STATIC.exists():
        app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(_STATIC / "index.html")

    @app.get("/{id_}")
    def golem_page(id_: str) -> FileResponse:
        return FileResponse(_STATIC / "index.html")

    @app.get("/{id_}/{tab}")
    def golem_page_tab(id_: str, tab: str) -> FileResponse:
        return FileResponse(_STATIC / "index.html")

    @app.get("/{id_}/{tab}/{topic}")
    def golem_page_topic(id_: str, tab: str, topic: str) -> FileResponse:
        return FileResponse(_STATIC / "index.html")

    return app


# ---------- Helpers ----------

def _require_golem(store: ForgeStore, id_: str) -> None:
    if not store.has_golem(id_):
        raise HTTPException(404, f"golem {id_!r} not found")


def _from_payload(p: GolemModel) -> GolemSpec:
    return GolemSpec(
        id=p.id,
        name=p.name,
        description=p.description,
        enabled=p.enabled,
        brain=BrainSpec(
            provider=p.brain.provider,
            model=p.brain.model,
            api_key=p.brain.api_key,
            base_url=p.brain.base_url,
        ),
        dialog=DialogSpec(
            kind=p.dialog.kind,
            telegram=TelegramSpec(
                token=p.dialog.telegram.token,
                chat_id=p.dialog.telegram.chat_id,
            ),
        ),
        mission=p.mission,
        routines=tuple(
            Routine(id=r.id, cron=r.cron, prompt=r.prompt, name=r.name) for r in p.routines
        ),
        topics=tuple(
            TopicSpec(id=t.id, description=t.description) for t in p.topics if t.id
        ),
        skills=tuple(p.skills),
    )


def _to_summary(spec: GolemSpec, supervisor: Supervisor) -> dict[str, Any]:
    return {
        "id": spec.id,
        "name": spec.name,
        "description": spec.description,
        "enabled": spec.enabled,
        "running": supervisor.is_awake(spec.id),
        "brain": {"provider": spec.brain.provider, "model": spec.brain.model},
        "dialog_kind": spec.dialog.kind,
        "skill_count": len(spec.skills),
    }


def _to_full(spec: GolemSpec, supervisor: Supervisor) -> dict[str, Any]:
    return {
        "id": spec.id,
        "name": spec.name,
        "description": spec.description,
        "enabled": spec.enabled,
        "running": supervisor.is_awake(spec.id),
        "brain": asdict(spec.brain),
        "dialog": {
            "kind": spec.dialog.kind,
            "telegram": asdict(spec.dialog.telegram),
        },
        "mission": spec.mission,
        "routines": [asdict(r) for r in spec.routines],
        "topics": [asdict(t) for t in spec.topics],
        "skills": list(spec.skills),
        "version": spec.version,
    }


def main() -> None:
    import uvicorn

    host = os.getenv("FORGE_HOST", "127.0.0.1")
    port = int(os.getenv("FORGE_PORT", "8765"))
    uvicorn.run(
        "forge.server:build_app",
        factory=True,
        host=host,
        port=port,
        reload=True,
        reload_dirs=[str(Path(__file__).resolve().parent.parent)],
    )


if __name__ == "__main__":
    main()
