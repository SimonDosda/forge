import os
from dataclasses import dataclass

from dotenv import load_dotenv


REQUIRED_KEYS = (
    "TELEGRAM_TOKEN",
    "TELEGRAM_CHAT_ID",
    "MISTRAL_API_KEY",
    "NOTION_TOKEN",
    "NOTION_DATABASE_ID",
    "LATITUDE",
    "LONGITUDE",
    "BRIEFING_HOUR",
)


@dataclass(frozen=True)
class Settings:
    telegram_token: str
    telegram_chat_id: int
    mistral_api_key: str
    notion_token: str
    notion_database_id: str
    latitude: float
    longitude: float
    briefing_hour: int


class MissingEnvError(RuntimeError):
    def __init__(self, missing: list[str]):
        super().__init__(f"Missing required env vars: {', '.join(missing)}")
        self.missing = missing


def load(env_path: str | None = ".env") -> Settings:
    if env_path:
        load_dotenv(env_path, override=False)

    missing = [k for k in REQUIRED_KEYS if not os.getenv(k)]
    if missing:
        raise MissingEnvError(missing)

    return Settings(
        telegram_token=os.environ["TELEGRAM_TOKEN"],
        telegram_chat_id=int(os.environ["TELEGRAM_CHAT_ID"]),
        mistral_api_key=os.environ["MISTRAL_API_KEY"],
        notion_token=os.environ["NOTION_TOKEN"],
        notion_database_id=os.environ["NOTION_DATABASE_ID"],
        latitude=float(os.environ["LATITUDE"]),
        longitude=float(os.environ["LONGITUDE"]),
        briefing_hour=int(os.environ["BRIEFING_HOUR"]),
    )
