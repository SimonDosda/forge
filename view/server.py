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
from skills import default_skills
from spirit.spirit import Schedule, Spirit, SpiritConfig
from view import env_io


_HERE = Path(__file__).resolve().parent
_STATIC = _HERE / "static"


# Editable .env keys — whitelist for writes.
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


class VoiceSend(BaseModel):
    text: str


# ---------- App ----------

def build_app(env_path: str = ".env") -> FastAPI:
    load_dotenv(env_path, override=False)

    app = FastAPI(title="Garden Bot — Config")

    def _values() -> dict[str, str]:
        return env_io.read(env_path)

    def _spirit() -> Spirit:
        path = _values().get("SPIRIT_PATH") or os.getenv("SPIRIT_PATH", "data/spirit.json")
        return Spirit(path)

    def _memory() -> JsonMemory:
        root = _values().get("MEMORY_ROOT") or os.getenv("MEMORY_ROOT", "data/memory")
        return JsonMemory(root)

    # ---- Env ----

    @app.get("/api/env")
    def get_env() -> dict[str, Any]:
        values = _values()
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

    # ---- Skills (read-only) ----

    @app.get("/api/skills")
    def list_skills() -> list[dict]:
        return [
            {
                "name": s.name,
                "tools": [
                    {"name": t.name, "description": t.description, "input_schema": t.input_schema}
                    for t in s.tools
                ],
            }
            for s in default_skills(_memory())
        ]

    # ---- Bot lifecycle ----

    @app.post("/api/restart")
    def restart_bot() -> dict[str, Any]:
        """Signal the running bot to exit. If supervised (systemd Restart=always),
        the bot comes back up with the new config. Otherwise the user must restart it manually."""
        import signal as _signal

        pid_file = Path("data/bot.pid")
        if not pid_file.exists():
            return {"status": "not_running", "detail": "No bot.pid found — bot is not running."}
        try:
            pid = int(pid_file.read_text().strip())
        except (ValueError, OSError) as exc:
            raise HTTPException(500, f"unreadable PID file: {exc}")
        try:
            os.kill(pid, _signal.SIGTERM)
        except ProcessLookupError:
            return {"status": "stale", "detail": f"PID {pid} not running (stale pid file)."}
        except PermissionError as exc:
            raise HTTPException(500, f"cannot signal PID {pid}: {exc}")
        return {"status": "signaled", "pid": pid}

    # ---- Voice (Telegram) ----

    @app.post("/api/voice/send")
    async def voice_send(body: VoiceSend) -> dict[str, str]:
        from telegram import Bot

        v = _values()
        token = v.get("TELEGRAM_TOKEN", "")
        chat_id_raw = v.get("TELEGRAM_CHAT_ID", "")
        if not token or not chat_id_raw:
            raise HTTPException(400, "TELEGRAM_TOKEN and TELEGRAM_CHAT_ID must be set")
        try:
            chat_id = int(chat_id_raw)
        except ValueError:
            raise HTTPException(400, f"TELEGRAM_CHAT_ID is not an integer: {chat_id_raw!r}")
        await Bot(token=token).send_message(chat_id=chat_id, text=body.text)
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
    uvicorn.run(
        "view.server:build_app",
        factory=True,
        host=host,
        port=port,
        reload=True,
        reload_dirs=[str(Path(__file__).resolve().parent.parent)],
    )


if __name__ == "__main__":
    main()
