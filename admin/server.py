from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from admin import checks
from admin.env_io import read_env, write_env


_STATIC_DIR = Path(__file__).resolve().parent / "static"


def build_app(
    env_path: str = ".env",
    skills_factory=None,
    http=None,
    notion_factory=None,
    mistral_factory=None,
) -> FastAPI:
    """Build the admin FastAPI app.

    Dependencies are injectable so tests can swap them for stubs:
    - skills_factory(env: dict) -> list[Skill]
    - http: object with .get/.post (default: real requests)
    - notion_factory(token: str) -> notion-like client
    - mistral_factory(api_key: str) -> Mistral-like client
    """
    if skills_factory is None:
        skills_factory = _default_skills_factory

    app = FastAPI(title="Garden Bot Admin")

    @app.get("/api/env")
    def get_env():
        return read_env(env_path)

    @app.put("/api/env")
    def put_env(values: dict[str, str] = Body(...)):
        write_env(env_path, values)
        return {"ok": True}

    @app.get("/api/checks/telegram/me")
    def telegram_me():
        token = _require(env_path, "TELEGRAM_TOKEN")
        return checks.telegram_get_me(token, http=http)

    @app.post("/api/checks/telegram/send")
    def telegram_send(payload: dict = Body(...)):
        env = read_env(env_path)
        token = _require_value(env, "TELEGRAM_TOKEN")
        chat_id = payload.get("chat_id") or env.get("TELEGRAM_CHAT_ID")
        text = payload.get("text", "Hello from the garden bot 🌱")
        if not chat_id:
            raise HTTPException(400, "chat_id missing")
        return checks.telegram_send_message(token, chat_id, text, http=http)

    @app.get("/api/checks/telegram/updates")
    def telegram_updates():
        token = _require(env_path, "TELEGRAM_TOKEN")
        return checks.telegram_get_updates(token, http=http)

    @app.get("/api/checks/notion")
    def notion():
        env = read_env(env_path)
        token = _require_value(env, "NOTION_TOKEN")
        db_id = _require_value(env, "NOTION_DATABASE_ID")
        try:
            return checks.notion_check(token, db_id, client_factory=notion_factory)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"Notion check failed: {exc}") from exc

    @app.post("/api/checks/mistral")
    def mistral(payload: dict = Body(default_factory=dict)):
        env = read_env(env_path)
        api_key = _require_value(env, "MISTRAL_API_KEY")
        text = payload.get("text") or "Reply with the single word: pong"
        try:
            return checks.mistral_check(api_key, text, client_factory=mistral_factory)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"Mistral check failed: {exc}") from exc

    @app.get("/api/checks/skills")
    def skills():
        env = read_env(env_path)
        return checks.list_skills(skills_factory(env))

    @app.post("/api/checks/skills/{skill_name}/{action_name}")
    def run_action(
        skill_name: str, action_name: str, params: dict = Body(default_factory=dict)
    ):
        env = read_env(env_path)
        try:
            result = checks.run_skill_action(
                skills_factory(env), skill_name, action_name, params
            )
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"Skill action failed: {exc}") from exc
        return JSONResponse(_serialize(result))

    @app.get("/")
    def index():
        return FileResponse(_STATIC_DIR / "index.html")

    return app


def _require(env_path: str, key: str) -> str:
    return _require_value(read_env(env_path), key)


def _require_value(env: dict[str, str], key: str) -> str:
    value = env.get(key)
    if not value:
        raise HTTPException(400, f"{key} not set in .env")
    return value


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, (list, tuple)):
        return [_serialize(v) for v in value]
    if isinstance(value, dict):
        return {k: _serialize(v) for k, v in value.items()}
    return value


def _default_skills_factory(env: dict[str, str]) -> list:
    from skills.open_meteo import OpenMeteo

    return [OpenMeteo()]


def main() -> None:  # pragma: no cover
    import uvicorn

    uvicorn.run(
        "admin.server:build_app",
        factory=True,
        host="127.0.0.1",
        port=8765,
        reload=True,
        reload_dirs=["admin"],
    )


if __name__ == "__main__":  # pragma: no cover
    main()
