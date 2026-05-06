import json
from datetime import date
from typing import Any, Protocol

from models import ActionType, Briefing, GardenAction
from skills.skill import Skill, SkillAction


class _MistralLike(Protocol):
    chat: Any


_BRIEFING_SYSTEM = (
    "You are a helpful gardening assistant. The user provides their location, "
    "the plants they grow, and their recent garden actions. You have tools "
    "available — use them to gather any data you need (e.g., today's weather). "
    "Once you have enough information, respond with strict JSON in the shape "
    '{"weather_summary": str, "tasks": [str, ...]}. Do not include any other text.'
)

_PARSE_SYSTEM = (
    "Extract garden actions from the user's free-form message. Each action has "
    'fields: name (short summary), type (one of "watering", "pruning", "planting", '
    '"fertilizing", "other"), plants (list of plant names), notes (optional). '
    'Respond with strict JSON: {"actions": [{...}, ...]}. '
    "If the message contains no garden action, return an empty actions list."
)

_MAX_TOOL_ITERATIONS = 5


class MistralAdvisor:
    def __init__(
        self,
        api_key: str,
        model: str = "mistral-small-latest",
        client: _MistralLike | None = None,
    ):
        self._model = model
        if client is None:
            from mistralai.client.sdk import Mistral

            client = Mistral(api_key=api_key)
        self._client = client

    def briefing(
        self,
        skills: list[Skill],
        history: list[GardenAction],
        plants: list[str],
        location: dict[str, float],
    ) -> Briefing:
        actions_by_qualified_name: dict[str, SkillAction] = {}
        tools: list[dict] = []
        for skill in skills:
            for action in skill.actions:
                qualified = f"{skill.name}__{action.name}"
                actions_by_qualified_name[qualified] = action
                tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": qualified,
                            "description": action.description,
                            "parameters": action.parameters,
                        },
                    }
                )

        user_payload = {
            "location": location,
            "plants": plants,
            "recent_actions": [
                {
                    "name": a.name,
                    "type": a.type.value,
                    "plants": list(a.plants),
                    "when": a.when.isoformat(),
                    "notes": a.notes,
                }
                for a in history
            ],
        }
        messages: list[dict] = [
            {"role": "system", "content": _BRIEFING_SYSTEM},
            {"role": "user", "content": json.dumps(user_payload)},
        ]

        for _ in range(_MAX_TOOL_ITERATIONS):
            response = self._client.chat.complete(
                model=self._model,
                messages=messages,
                tools=tools or None,
                tool_choice="auto" if tools else None,
            )
            message = response.choices[0].message
            tool_calls = getattr(message, "tool_calls", None) or []

            if not tool_calls:
                return _parse_briefing(getattr(message, "content", "") or "")

            messages.append(
                {
                    "role": "assistant",
                    "content": getattr(message, "content", "") or "",
                    "tool_calls": [_serialize_tool_call(c) for c in tool_calls],
                }
            )
            for call in tool_calls:
                result = _invoke(actions_by_qualified_name, call)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "name": call.function.name,
                        "content": result,
                    }
                )

        return Briefing(weather_summary="", tasks=())

    def parse_message(self, text: str) -> list[GardenAction]:
        response = self._client.chat.complete(
            model=self._model,
            messages=[
                {"role": "system", "content": _PARSE_SYSTEM},
                {"role": "user", "content": text},
            ],
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        try:
            data = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return []
        return [_action_from_json(item) for item in data.get("actions", [])]


def _parse_briefing(content: str) -> Briefing:
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return Briefing(weather_summary="", tasks=())
    return Briefing(
        weather_summary=str(data.get("weather_summary", "")),
        tasks=tuple(str(t) for t in data.get("tasks", [])),
    )


def _serialize_tool_call(call: Any) -> dict:
    return {
        "id": call.id,
        "type": "function",
        "function": {
            "name": call.function.name,
            "arguments": call.function.arguments,
        },
    }


def _invoke(lookup: dict[str, SkillAction], call: Any) -> str:
    action = lookup.get(call.function.name)
    if action is None:
        return json.dumps({"error": f"unknown tool: {call.function.name}"})
    try:
        args = json.loads(call.function.arguments or "{}")
    except json.JSONDecodeError:
        return json.dumps({"error": "invalid JSON arguments"})
    try:
        result = action.handler(**args)
    except Exception as exc:  # noqa: BLE001 - feed the error back to the model
        return json.dumps({"error": str(exc)})
    return _serialize_result(result)


def _serialize_result(value: Any) -> str:
    if hasattr(value, "__dict__"):
        return json.dumps(vars(value), default=str)
    try:
        return json.dumps(value, default=str)
    except TypeError:
        return json.dumps(str(value))


def _action_from_json(item: dict) -> GardenAction:
    raw_type = (item.get("type") or "other").lower()
    try:
        action_type = ActionType(raw_type)
    except ValueError:
        action_type = ActionType.OTHER

    return GardenAction(
        name=str(item.get("name", "")).strip() or "Garden action",
        type=action_type,
        plants=tuple(str(p) for p in item.get("plants", [])),
        notes=str(item.get("notes", "")),
        when=date.today(),
    )
