from datetime import date
from typing import Any, Protocol

from models import ActionType, GardenAction


class _NotionLike(Protocol):
    pages: Any
    databases: Any


class NotionMemory:
    def __init__(self, token: str, database_id: str, client: _NotionLike | None = None):
        self._database_id = database_id
        if client is None:
            from notion_client import Client

            client = Client(auth=token)
        self._client = client

    def log_action(self, action: GardenAction) -> None:
        self._client.pages.create(
            parent={"database_id": self._database_id},
            properties=_action_to_properties(action),
        )

    def recent_actions(self, limit: int = 30) -> list[GardenAction]:
        result = self._client.databases.query(
            database_id=self._database_id,
            sorts=[{"property": "Date", "direction": "descending"}],
            page_size=limit,
        )
        return [_page_to_action(page) for page in result.get("results", [])]

    def plants(self) -> list[str]:
        schema = self._client.databases.retrieve(database_id=self._database_id)
        options = schema["properties"]["Plants"]["multi_select"]["options"]
        return [opt["name"] for opt in options]


def _action_to_properties(action: GardenAction) -> dict:
    return {
        "Name": {"title": [{"text": {"content": action.name}}]},
        "Date": {"date": {"start": action.when.isoformat()}},
        "Type": {"select": {"name": action.type.value}},
        "Plants": {"multi_select": [{"name": p} for p in action.plants]},
        "Notes": {"rich_text": [{"text": {"content": action.notes}}]},
    }


def _page_to_action(page: dict) -> GardenAction:
    props = page["properties"]
    return GardenAction(
        name=_read_title(props.get("Name")),
        when=_read_date(props.get("Date")),
        type=_read_action_type(props.get("Type")),
        plants=tuple(_read_multi_select(props.get("Plants"))),
        notes=_read_rich_text(props.get("Notes")),
    )


def _read_title(prop: dict | None) -> str:
    if not prop:
        return ""
    parts = prop.get("title") or []
    return "".join(p.get("plain_text", p.get("text", {}).get("content", "")) for p in parts)


def _read_rich_text(prop: dict | None) -> str:
    if not prop:
        return ""
    parts = prop.get("rich_text") or []
    return "".join(p.get("plain_text", p.get("text", {}).get("content", "")) for p in parts)


def _read_date(prop: dict | None) -> date:
    if not prop or not prop.get("date"):
        return date.today()
    return date.fromisoformat(prop["date"]["start"])


def _read_action_type(prop: dict | None) -> ActionType:
    if not prop or not prop.get("select"):
        return ActionType.OTHER
    name = prop["select"].get("name", "other")
    try:
        return ActionType(name)
    except ValueError:
        return ActionType.OTHER


def _read_multi_select(prop: dict | None) -> list[str]:
    if not prop:
        return []
    return [opt["name"] for opt in prop.get("multi_select", [])]
