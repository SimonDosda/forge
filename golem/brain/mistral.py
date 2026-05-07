import json
from typing import Any

from golem.brain.brain import BrainConfig
from golem.core import BrainResponse, Message, ToolCall, ToolSpec


class MistralBrain:
    def __init__(self, config: BrainConfig, client: Any | None = None):
        self._model = config.model
        if client is None:
            from mistralai.client.sdk import Mistral
            client = Mistral(api_key=config.api_key)
        self._client = client

    def chat(self, messages: list[Message], tools: list[ToolSpec] = ()) -> BrainResponse:
        response = self._client.chat.complete(
            model=self._model,
            messages=[_to_wire(m) for m in messages],
            tools=[_tool_to_wire(t) for t in tools] or None,
            tool_choice="auto" if tools else None,
        )
        msg = response.choices[0].message
        calls = tuple(
            ToolCall(
                id=c.id,
                name=c.function.name,
                arguments=_safe_json(c.function.arguments),
            )
            for c in (getattr(msg, "tool_calls", None) or [])
        )
        return BrainResponse(content=getattr(msg, "content", "") or "", tool_calls=calls)


def _to_wire(m: Message) -> dict:
    if m.role == "tool":
        return {"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content}
    if m.role == "assistant" and m.tool_calls:
        return {
            "role": "assistant",
            "content": m.content,
            "tool_calls": [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
                }
                for c in m.tool_calls
            ],
        }
    return {"role": m.role, "content": m.content}


def _tool_to_wire(t: ToolSpec) -> dict:
    return {
        "type": "function",
        "function": {
            "name": t.name,
            "description": t.description,
            "parameters": t.input_schema,
        },
    }


def _safe_json(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}
