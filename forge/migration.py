"""One-shot migration from the legacy single-bot layout (.env + data/spirit.json
+ data/memory.json) to the multi-golem forge store. Runs at startup; idempotent
once at least one golem exists in the store.
"""
import json
import sys
from pathlib import Path

from forge.store import (
    BrainSpec,
    DialogSpec,
    ForgeStore,
    GolemSpec,
    TelegramSpec,
)
from golem.spirit.spirit import Routine


_LEGACY_ENV = Path(".env")
_LEGACY_SPIRIT = Path("data/spirit.json")
_LEGACY_MEMORY = Path("data/memory.json")


def migrate_legacy_if_needed(store: ForgeStore) -> str | None:
    """Seed a `default` golem from legacy files if the forge has no golems yet.

    Returns the migrated golem's name, or None if migration was skipped.
    """
    if store.list_golems():
        return None
    if not (_LEGACY_ENV.exists() or _LEGACY_SPIRIT.exists()):
        return None

    env = _read_env(_LEGACY_ENV)
    brain = BrainSpec(
        provider=env.get("BRAIN_PROVIDER", "mistral") or "mistral",
        model=env.get("BRAIN_MODEL", ""),
        api_key=env.get("BRAIN_API_KEY", ""),
        base_url=env.get("BRAIN_BASE_URL", ""),
    )
    chat_id_raw = (env.get("TELEGRAM_CHAT_ID") or "").strip()
    try:
        chat_id = int(chat_id_raw) if chat_id_raw else 0
    except ValueError:
        chat_id = 0
    dialog = DialogSpec(
        kind="telegram",
        telegram=TelegramSpec(
            token=env.get("TELEGRAM_TOKEN", ""),
            chat_id=chat_id,
        ),
    )

    mission = ""
    routines: tuple[Routine, ...] = ()
    if _LEGACY_SPIRIT.exists():
        try:
            payload = json.loads(_LEGACY_SPIRIT.read_text(encoding="utf-8"))
            mission = str(payload.get("system_prompt", ""))
            routines = tuple(
                Routine(
                    id=str(s["id"]),
                    cron=dict(s.get("cron", {})),
                    prompt=str(s.get("prompt", "")),
                )
                for s in payload.get("schedules", [])
            )
        except (OSError, json.JSONDecodeError, KeyError) as exc:
            print(f"[forge] could not parse {_LEGACY_SPIRIT}: {exc}", file=sys.stderr)

    spec = GolemSpec(
        id="default",
        name="default",
        enabled=True,
        brain=brain,
        dialog=dialog,
        mission=mission,
        routines=routines,
        skills=("memory", "open_meteo"),
    )
    store.create_golem(spec)

    if _LEGACY_MEMORY.exists():
        target = Path("data/default/memory.json")
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            _LEGACY_MEMORY.rename(target)
            print(
                f"[forge] migrated memory: {_LEGACY_MEMORY} → {target}",
                file=sys.stderr,
            )

    print("[forge] migrated legacy configuration to golem 'default'", file=sys.stderr)
    return "default"


def _read_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        from dotenv import dotenv_values
    except ImportError:
        return {}
    return {k: (v or "") for k, v in dotenv_values(path).items()}
