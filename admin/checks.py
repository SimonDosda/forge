"""Diagnostic helpers used by the admin server.

Each function takes the dependency it needs (HTTP client, Notion client) so
the server endpoints can be tested without hitting real services.
"""
from typing import Any

import requests


_TELEGRAM_BASE = "https://api.telegram.org"


def telegram_get_me(token: str, http: Any | None = None) -> dict:
    response = (http or requests).get(f"{_TELEGRAM_BASE}/bot{token}/getMe", timeout=10)
    return response.json()


def telegram_send_message(
    token: str, chat_id: int | str, text: str, http: Any | None = None
) -> dict:
    response = (http or requests).post(
        f"{_TELEGRAM_BASE}/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text},
        timeout=10,
    )
    return response.json()


def telegram_get_updates(token: str, http: Any | None = None) -> dict:
    response = (http or requests).get(
        f"{_TELEGRAM_BASE}/bot{token}/getUpdates", timeout=10
    )
    return response.json()


def notion_check(token: str, database_id: str, client_factory: Any | None = None) -> dict:
    """Verify Notion access by retrieving the database schema and recent rows."""
    if client_factory is None:
        from notion_client import Client

        client = Client(auth=token)
    else:
        client = client_factory(token)

    schema = client.databases.retrieve(database_id=database_id)
    plants_options = (
        schema.get("properties", {}).get("Plants", {}).get("multi_select", {}).get("options", [])
    )
    sample = client.databases.query(database_id=database_id, page_size=5)
    return {
        "ok": True,
        "title": _join_title(schema.get("title", [])),
        "plants": [opt.get("name") for opt in plants_options],
        "recent_rows": len(sample.get("results", [])),
    }


def mistral_check(
    api_key: str,
    text: str = "Reply with the single word: pong",
    model: str = "mistral-small-latest",
    client_factory: Any | None = None,
) -> dict:
    """Verify Mistral access by sending one chat message and returning the reply."""
    if client_factory is None:
        from mistralai.client.sdk import Mistral

        client = Mistral(api_key=api_key)
    else:
        client = client_factory(api_key)

    response = client.chat.complete(
        model=model,
        messages=[{"role": "user", "content": text}],
    )
    reply = response.choices[0].message.content
    return {"ok": True, "prompt": text, "reply": reply}


def list_skills(skills: list) -> list[dict]:
    return [
        {
            "name": skill.name,
            "description": skill.description,
            "actions": [
                {
                    "name": action.name,
                    "description": action.description,
                    "parameters": action.parameters,
                }
                for action in skill.actions
            ],
        }
        for skill in skills
    ]


def run_skill_action(skills: list, skill_name: str, action_name: str, params: dict) -> Any:
    for skill in skills:
        if skill.name != skill_name:
            continue
        for action in skill.actions:
            if action.name == action_name:
                return action.handler(**params)
    raise KeyError(f"unknown skill action: {skill_name}.{action_name}")


def _join_title(parts: list) -> str:
    return "".join(p.get("plain_text", "") for p in parts) if parts else ""
