from pathlib import Path

from admin.env_io import read_env, write_env


def test_read_env_parses_key_value_pairs(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text(
        "# a comment\n"
        "TELEGRAM_TOKEN=abc\n"
        "LATITUDE=48.85\n"
        "QUOTED=\"with spaces\"\n"
        "\n"
        "TRAILING=value # inline comment\n"
    )

    data = read_env(env)

    assert data == {
        "TELEGRAM_TOKEN": "abc",
        "LATITUDE": "48.85",
        "QUOTED": "with spaces",
        "TRAILING": "value",
    }


def test_read_env_returns_empty_dict_when_missing(tmp_path: Path):
    assert read_env(tmp_path / "missing.env") == {}


def test_write_env_updates_existing_keys_and_appends_new(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text(
        "# config\nTELEGRAM_TOKEN=old\nLATITUDE=0.0\n# trailing\n"
    )

    write_env(env, {"TELEGRAM_TOKEN": "new", "LATITUDE": "48.85", "BRIEFING_HOUR": "8"})

    text = env.read_text()
    assert "# config" in text
    assert "# trailing" in text
    assert "TELEGRAM_TOKEN=new" in text
    assert "LATITUDE=48.85" in text
    assert "BRIEFING_HOUR=8" in text
    assert "TELEGRAM_TOKEN=old" not in text


def test_write_env_creates_file_when_missing(tmp_path: Path):
    env = tmp_path / "fresh.env"

    write_env(env, {"A": "1", "B": "2"})

    assert env.read_text() == "A=1\nB=2\n"
