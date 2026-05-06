from dataclasses import dataclass, field
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from admin.server import build_app
from skills.skill import SkillAction


@dataclass
class _StubResponse:
    payload: dict
    status_code: int = 200

    def json(self):
        return self.payload


@dataclass
class _StubHttp:
    """Records every HTTP call and returns canned responses keyed by URL substring."""

    routes: dict[str, dict] = field(default_factory=dict)
    calls: list[dict] = field(default_factory=list)

    def get(self, url, params=None, timeout=None):
        return self._respond("GET", url, params=params)

    def post(self, url, json=None, timeout=None):
        return self._respond("POST", url, json=json)

    def _respond(self, method, url, **extra):
        self.calls.append({"method": method, "url": url, **extra})
        for needle, payload in self.routes.items():
            if needle in url:
                return _StubResponse(payload)
        return _StubResponse({"ok": False, "error": "no stub for url"}, status_code=404)


@dataclass
class _FakeSkill:
    name: str = "open_meteo"
    description: str = "weather"
    actions: list[SkillAction] = field(default_factory=list)


def _make_skill(handler=None):
    handler = handler or (lambda latitude, longitude: {"temp_c": 21.0, "condition": "clear"})
    skill = _FakeSkill()
    skill.actions = [
        SkillAction(
            name="get_forecast",
            description="forecast",
            parameters={
                "type": "object",
                "properties": {"latitude": {"type": "number"}, "longitude": {"type": "number"}},
                "required": ["latitude", "longitude"],
            },
            handler=handler,
        )
    ]
    return skill


def _seed_env(tmp_path: Path) -> Path:
    env = tmp_path / ".env"
    env.write_text(
        "TELEGRAM_TOKEN=tg-token\n"
        "TELEGRAM_CHAT_ID=42\n"
        "MISTRAL_API_KEY=mk\n"
        "NOTION_TOKEN=nt\n"
        "NOTION_DATABASE_ID=db-id\n"
        "LATITUDE=48.85\n"
        "LONGITUDE=2.35\n"
        "BRIEFING_HOUR=8\n"
    )
    return env


@pytest.fixture
def env_path(tmp_path):
    return _seed_env(tmp_path)


def _client(env_path, **overrides):
    app = build_app(env_path=str(env_path), **overrides)
    return TestClient(app)


def test_get_env_returns_loaded_values(env_path):
    with _client(env_path) as c:
        r = c.get("/api/env")
    assert r.status_code == 200
    body = r.json()
    assert body["TELEGRAM_TOKEN"] == "tg-token"
    assert body["LATITUDE"] == "48.85"


def test_put_env_persists_changes(env_path):
    with _client(env_path) as c:
        r = c.put("/api/env", json={"TELEGRAM_TOKEN": "new-tok", "BRIEFING_HOUR": "9"})
    assert r.status_code == 200
    text = env_path.read_text()
    assert "TELEGRAM_TOKEN=new-tok" in text
    assert "BRIEFING_HOUR=9" in text
    # Untouched keys preserved
    assert "LATITUDE=48.85" in text


def test_telegram_me_calls_telegram_api(env_path):
    http = _StubHttp(routes={"/getMe": {"ok": True, "result": {"username": "garden_bot"}}})
    with _client(env_path, http=http) as c:
        r = c.get("/api/checks/telegram/me")
    assert r.status_code == 200
    assert r.json()["result"]["username"] == "garden_bot"
    assert "/bottg-token/getMe" in http.calls[0]["url"]


def test_telegram_send_uses_chat_id_from_env(env_path):
    http = _StubHttp(routes={"/sendMessage": {"ok": True, "result": {"message_id": 1}}})
    with _client(env_path, http=http) as c:
        r = c.post("/api/checks/telegram/send", json={"text": "hi"})
    assert r.status_code == 200
    payload = http.calls[0]["json"]
    assert payload == {"chat_id": "42", "text": "hi"}


def test_telegram_send_rejects_when_token_missing(tmp_path):
    env = tmp_path / ".env"
    env.write_text("TELEGRAM_CHAT_ID=42\n")
    with _client(env) as c:
        r = c.post("/api/checks/telegram/send", json={"text": "hi"})
    assert r.status_code == 400
    assert "TELEGRAM_TOKEN" in r.json()["detail"]


def test_skills_list_returns_skill_definitions(env_path):
    skill = _make_skill()
    with _client(env_path, skills_factory=lambda env: [skill]) as c:
        r = c.get("/api/checks/skills")
    assert r.status_code == 200
    body = r.json()
    assert body[0]["name"] == "open_meteo"
    assert body[0]["actions"][0]["name"] == "get_forecast"


def test_run_skill_action_invokes_handler(env_path):
    received = {}

    def handler(latitude, longitude):
        received["lat"] = latitude
        received["lon"] = longitude
        return {"temp_c": 19.0}

    skill = _make_skill(handler=handler)
    with _client(env_path, skills_factory=lambda env: [skill]) as c:
        r = c.post(
            "/api/checks/skills/open_meteo/get_forecast",
            json={"latitude": 48.85, "longitude": 2.35},
        )
    assert r.status_code == 200
    assert r.json() == {"temp_c": 19.0}
    assert received == {"lat": 48.85, "lon": 2.35}


def test_run_skill_action_404_for_unknown(env_path):
    with _client(env_path, skills_factory=lambda env: [_make_skill()]) as c:
        r = c.post("/api/checks/skills/missing/foo", json={})
    assert r.status_code == 404


def test_notion_check_uses_injected_factory(env_path):
    class _FakeDatabases:
        def retrieve(self, database_id):
            assert database_id == "db-id"
            return {
                "title": [{"plain_text": "Garden Log"}],
                "properties": {
                    "Plants": {"multi_select": {"options": [{"name": "tomatoes"}]}}
                },
            }

        def query(self, database_id, page_size):
            return {"results": [{"id": "row1"}, {"id": "row2"}]}

    class _FakeNotion:
        databases = _FakeDatabases()

    with _client(env_path, notion_factory=lambda token: _FakeNotion()) as c:
        r = c.get("/api/checks/notion")

    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Garden Log"
    assert body["plants"] == ["tomatoes"]
    assert body["recent_rows"] == 2


def test_mistral_check_round_trips_a_chat(env_path):
    from types import SimpleNamespace

    captured = {}

    class _FakeChat:
        def complete(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="pong"))]
            )

    class _FakeMistral:
        def __init__(self, api_key):
            captured["api_key"] = api_key
            self.chat = _FakeChat()

    with _client(env_path, mistral_factory=lambda key: _FakeMistral(key)) as c:
        r = c.post("/api/checks/mistral", json={"text": "ping"})

    assert r.status_code == 200
    body = r.json()
    assert body == {"ok": True, "prompt": "ping", "reply": "pong"}
    assert captured["api_key"] == "mk"
    assert captured["messages"] == [{"role": "user", "content": "ping"}]


def test_mistral_check_rejects_when_api_key_missing(tmp_path):
    env = tmp_path / ".env"
    env.write_text("TELEGRAM_TOKEN=tg\n")
    with _client(env) as c:
        r = c.post("/api/checks/mistral", json={"text": "hi"})
    assert r.status_code == 400
    assert "MISTRAL_API_KEY" in r.json()["detail"]


def test_index_serves_html(env_path):
    with _client(env_path) as c:
        r = c.get("/")
    assert r.status_code == 200
    assert "Garden Bot Admin" in r.text
