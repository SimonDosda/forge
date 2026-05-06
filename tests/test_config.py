import os
from pathlib import Path

import pytest

import config


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in config.REQUIRED_KEYS:
        monkeypatch.delenv(k, raising=False)
    yield


def _write_env(tmp_path: Path, **values: str) -> Path:
    path = tmp_path / ".env"
    path.write_text("\n".join(f"{k}={v}" for k, v in values.items()))
    return path


def test_load_returns_typed_settings(tmp_path):
    env = _write_env(
        tmp_path,
        TELEGRAM_TOKEN="tg",
        TELEGRAM_CHAT_ID="42",
        MISTRAL_API_KEY="mk",
        NOTION_TOKEN="nt",
        NOTION_DATABASE_ID="nd",
        LATITUDE="48.85",
        LONGITUDE="2.35",
        BRIEFING_HOUR="8",
    )

    settings = config.load(str(env))

    assert settings.telegram_token == "tg"
    assert settings.telegram_chat_id == 42
    assert settings.latitude == pytest.approx(48.85)
    assert settings.briefing_hour == 8


def test_load_raises_for_missing_keys(tmp_path):
    env = _write_env(tmp_path, TELEGRAM_TOKEN="tg")

    with pytest.raises(config.MissingEnvError) as excinfo:
        config.load(str(env))

    assert "MISTRAL_API_KEY" in excinfo.value.missing
    assert "TELEGRAM_TOKEN" not in excinfo.value.missing
