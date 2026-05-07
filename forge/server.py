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
)
from forge.supervisor import Supervisor
from golem.memory.tinydb_store import TinyDbMemory
from golem.skills import available_skill_names, describe_skills
from golem.spirit.spirit import InvalidCronError, Schedule


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


class ScheduleModel(BaseModel):
    id: str
    cron: dict[str, Any]
    prompt: str


class GolemModel(BaseModel):
    name: str
    enabled: bool = False
    brain: BrainModel = Field(default_factory=BrainModel)
    dialog: DialogModel = Field(default_factory=DialogModel)
    system_prompt: str = ""
    schedules: list[ScheduleModel] = Field(default_factory=list)
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

    def _memory_for(name: str) -> TinyDbMemory:
        return TinyDbMemory(f"data/{name}/memory.json")

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
        except GolemExistsError:
            raise HTTPException(409, f"golem {spec.name!r} already exists")
        except (ValueError, InvalidCronError) as exc:
            raise HTTPException(400, str(exc))
        if new.enabled:
            try:
                await supervisor.awake(new.name)
            except Exception as exc:  # noqa: BLE001
                # Creation succeeded; surface the autowake failure as a soft warning.
                return _to_full(new, supervisor) | {"awake_error": str(exc)}
        return _to_full(new, supervisor)

    @app.get("/api/golems/{name}")
    def get_golem(name: str) -> dict[str, Any]:
        try:
            return _to_full(store.get_golem(name), supervisor)
        except GolemNotFoundError:
            raise HTTPException(404, f"golem {name!r} not found")

    @app.put("/api/golems/{name}")
    async def update_golem(name: str, payload: GolemModel) -> dict[str, Any]:
        spec = _from_payload(payload)
        was_running = supervisor.is_awake(name)
        try:
            updated = store.update_golem(name, spec)
        except GolemNotFoundError:
            raise HTTPException(404, f"golem {name!r} not found")
        except GolemExistsError:
            raise HTTPException(409, f"golem {spec.name!r} already exists")
        except (ValueError, InvalidCronError) as exc:
            raise HTTPException(400, str(exc))
        # Auto-apply config changes to a running instance.
        if was_running:
            try:
                await supervisor.reshape(name, updated.name)
            except Exception as exc:  # noqa: BLE001
                return _to_full(updated, supervisor) | {"reshape_error": str(exc)}
        return _to_full(updated, supervisor)

    @app.delete("/api/golems/{name}")
    async def delete_golem(name: str) -> dict[str, str]:
        await supervisor.sleep(name)
        try:
            store.delete_golem(name)
        except GolemNotFoundError:
            raise HTTPException(404, f"golem {name!r} not found")
        return {"status": "ok"}

    # ---- Per-golem lifecycle ----

    @app.post("/api/golems/{name}/awake")
    async def awake_golem(name: str) -> dict[str, Any]:
        if not store.has_golem(name):
            raise HTTPException(404, f"golem {name!r} not found")
        try:
            await supervisor.awake(name)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, f"failed to awake: {exc}")
        return {"status": "ok", "running": True}

    @app.post("/api/golems/{name}/sleep")
    async def sleep_golem(name: str) -> dict[str, Any]:
        await supervisor.sleep(name)
        return {"status": "ok", "running": False}

    @app.post("/api/golems/{name}/reshape")
    async def reshape_golem(name: str) -> dict[str, Any]:
        if not store.has_golem(name):
            raise HTTPException(404, f"golem {name!r} not found")
        try:
            await supervisor.reshape(name)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, f"failed to reshape: {exc}")
        return {"status": "ok", "running": supervisor.is_awake(name)}

    # ---- Per-golem dialog (Telegram one-shot send) ----

    @app.post("/api/golems/{name}/dialog/send")
    async def dialog_send(name: str, body: DialogSend) -> dict[str, str]:
        try:
            spec = store.get_golem(name)
        except GolemNotFoundError:
            raise HTTPException(404, f"golem {name!r} not found")
        if spec.dialog.kind != "telegram":
            raise HTTPException(400, f"unsupported dialog kind: {spec.dialog.kind!r}")
        tg = spec.dialog.telegram
        if not tg.token or not tg.chat_id:
            raise HTTPException(400, "telegram token and chat_id must be set")
        from telegram import Bot
        await Bot(token=tg.token).send_message(chat_id=tg.chat_id, text=body.text)
        return {"status": "ok"}

    # ---- Per-golem memory ----

    @app.get("/api/golems/{name}/memory/topics")
    def list_topics(name: str) -> list[str]:
        _require_golem(store, name)
        return _memory_for(name).topics()

    @app.get("/api/golems/{name}/memory/{topic}")
    def list_entries(name: str, topic: str) -> list[dict]:
        _require_golem(store, name)
        return [
            {
                "id": e.id,
                "data": e.data,
                "created_at": e.created_at,
                "updated_at": e.updated_at,
            }
            for e in _memory_for(name).get(topic)
        ]

    @app.post("/api/golems/{name}/memory/{topic}")
    def add_entry(name: str, topic: str, body: EntryUpdate) -> dict:
        _require_golem(store, name)
        e = _memory_for(name).add(topic, body.data)
        return {"id": e.id}

    @app.put("/api/golems/{name}/memory/{topic}/{entry_id}")
    def update_entry(name: str, topic: str, entry_id: str, body: EntryUpdate) -> dict:
        _require_golem(store, name)
        try:
            _memory_for(name).update(topic, entry_id, body.data)
        except KeyError as exc:
            raise HTTPException(404, str(exc))
        return {"status": "ok"}

    @app.delete("/api/golems/{name}/memory/{topic}/{entry_id}")
    def delete_entry(name: str, topic: str, entry_id: str) -> dict:
        _require_golem(store, name)
        try:
            _memory_for(name).delete(topic, entry_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc))
        return {"status": "ok"}

    # ---- Static ----

    if _STATIC.exists():
        app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(_STATIC / "index.html")

    @app.get("/golem/{name}")
    def golem_page(name: str) -> FileResponse:
        return FileResponse(_STATIC / "index.html")

    return app


# ---------- Helpers ----------

def _require_golem(store: ForgeStore, name: str) -> None:
    if not store.has_golem(name):
        raise HTTPException(404, f"golem {name!r} not found")


def _from_payload(p: GolemModel) -> GolemSpec:
    return GolemSpec(
        name=p.name,
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
        system_prompt=p.system_prompt,
        schedules=tuple(
            Schedule(id=s.id, cron=s.cron, prompt=s.prompt) for s in p.schedules
        ),
        skills=tuple(p.skills),
    )


def _to_summary(spec: GolemSpec, supervisor: Supervisor) -> dict[str, Any]:
    return {
        "name": spec.name,
        "enabled": spec.enabled,
        "running": supervisor.is_awake(spec.name),
        "brain": {"provider": spec.brain.provider, "model": spec.brain.model},
        "dialog_kind": spec.dialog.kind,
        "skill_count": len(spec.skills),
    }


def _to_full(spec: GolemSpec, supervisor: Supervisor) -> dict[str, Any]:
    return {
        "name": spec.name,
        "enabled": spec.enabled,
        "running": supervisor.is_awake(spec.name),
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
