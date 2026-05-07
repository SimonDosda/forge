"""Loads secrets and runtime selectors from .env."""
import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    # Brain
    brain_provider: str
    brain_model: str
    brain_api_key: str
    brain_base_url: str

    # Voice (telegram for now)
    telegram_token: str
    telegram_chat_id: int

    # Filesystem roots
    memory_root: str
    spirit_path: str


class MissingEnvError(RuntimeError):
    def __init__(self, missing: list[str]):
        super().__init__(f"Missing required env vars: {', '.join(missing)}")
        self.missing = missing


_REQUIRED = ("BRAIN_PROVIDER", "BRAIN_MODEL", "TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID")


def load(env_path: str | None = ".env") -> Settings:
    if env_path:
        load_dotenv(env_path, override=False)

    missing = [k for k in _REQUIRED if not os.getenv(k)]
    if missing:
        raise MissingEnvError(missing)

    return Settings(
        brain_provider=os.environ["BRAIN_PROVIDER"],
        brain_model=os.environ["BRAIN_MODEL"],
        brain_api_key=os.getenv("BRAIN_API_KEY", ""),
        brain_base_url=os.getenv("BRAIN_BASE_URL", ""),
        telegram_token=os.environ["TELEGRAM_TOKEN"],
        telegram_chat_id=int(os.environ["TELEGRAM_CHAT_ID"]),
        memory_root=os.getenv("MEMORY_ROOT", "data/memory"),
        spirit_path=os.getenv("SPIRIT_PATH", "data/spirit.json"),
    )
