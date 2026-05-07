"""Browser-based config viewer/editor.

Run with: uv run python -m view.server
"""
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from memory.json_store import JsonMemory
from spirit.spirit import Schedule, Spirit, SpiritConfig
from view import env_io


_HERE = Path(__file__).resolve().parent
_STATIC = _HERE / "static"


# Editable .env keys — surfaced in the UI. Order matters (drives display).
_ENV_KEYS = (
    "BRAIN_PROVIDER",
    "BRAIN_MODEL",
    "BRAIN_API_KEY",
    "BRAIN_BASE_URL",
    "TELEGRAM_TOKEN",
    "TELEGRAM_CHAT_ID",
    "MEMORY_ROOT",
    "SPIRIT_PATH",
)

_SECRET_KEYS = {"BRAIN_API_KEY", "TELEGRAM_TOKEN"}


# ---------- API models ----------

class EnvUpdate(BaseModel):
    values: dict[str, str]


class ScheduleModel(BaseModel):
    id: str
    cron: dict[str, Any]
    prompt: str


class SpiritUpdate(BaseModel):
    system_prompt: str
    schedules: list[ScheduleModel]


class EntryUpdate(BaseModel):
    data: dict[str, Any]


# ---------- App ----------

def build_app(env_path: str = ".env") -> FastAPI:
    load_dotenv(env_path, override=False)

    memory_root = os.getenv("MEMORY_ROOT", "data/memory")
    spirit_path = os.getenv("SPIRIT_PATH", "data/spirit.json")

    app = FastAPI(title="Garden Bot — Config")

    def _spirit() -> Spirit:
        return Spirit(spirit_path)

    def _memory() -> JsonMemory:
        return JsonMemory(memory_root)

    # ---- Env ----

    @app.get("/api/env")
    def get_env() -> dict[str, Any]:
        values = env_io.read(env_path)
        return {
            "keys": list(_ENV_KEYS),
            "values": {k: values.get(k, "") for k in _ENV_KEYS},
            "secret_keys": list(_SECRET_KEYS),
        }

    @app.put("/api/env")
    def put_env(update: EnvUpdate) -> dict[str, str]:
        unknown = [k for k in update.values if k not in _ENV_KEYS]
        if unknown:
            raise HTTPException(400, f"unknown keys: {unknown}")
        env_io.write(env_path, update.values)
        return {"status": "ok"}

    # ---- Spirit ----

    @app.get("/api/spirit")
    def get_spirit() -> dict[str, Any]:
        s = _spirit()
        return {
            "system_prompt": s.system_prompt,
            "schedules": [asdict(sc) for sc in s.schedules],
        }

    @app.put("/api/spirit")
    def put_spirit(update: SpiritUpdate) -> dict[str, str]:
        s = _spirit()
        s.update(SpiritConfig(
            system_prompt=update.system_prompt,
            schedules=tuple(
                Schedule(id=sc.id, cron=sc.cron, prompt=sc.prompt)
                for sc in update.schedules
            ),
        ))
        return {"status": "ok"}

    # ---- Memory ----

    @app.get("/api/memory/topics")
    def list_topics() -> list[str]:
        return _memory().topics()

    @app.get("/api/memory/{topic}")
    def list_entries(topic: str) -> list[dict]:
        return [
            {
                "id": e.id,
                "data": e.data,
                "created_at": e.created_at,
                "updated_at": e.updated_at,
            }
            for e in _memory().get(topic)
        ]

    @app.post("/api/memory/{topic}")
    def add_entry(topic: str, body: EntryUpdate) -> dict:
        e = _memory().add(topic, body.data)
        return {"id": e.id}

    @app.put("/api/memory/{topic}/{entry_id}")
    def update_entry(topic: str, entry_id: str, body: EntryUpdate) -> dict:
        try:
            _memory().update(topic, entry_id, body.data)
        except KeyError as exc:
            raise HTTPException(404, str(exc))
        return {"status": "ok"}

    @app.delete("/api/memory/{topic}/{entry_id}")
    def delete_entry(topic: str, entry_id: str) -> dict:
        try:
            _memory().delete(topic, entry_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc))
        return {"status": "ok"}

    # ---- Static ----

    if _STATIC.exists():
        app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(_STATIC / "index.html")

    return app


def main() -> None:
    import uvicorn

    host = os.getenv("VIEW_HOST", "127.0.0.1")
    port = int(os.getenv("VIEW_PORT", "8765"))
    uvicorn.run(build_app(), host=host, port=port)


if __name__ == "__main__":
    main()
