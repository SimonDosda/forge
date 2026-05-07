from typing import Any

from brain.brain import BrainConfig
from core import BrainResponse, Message, ToolCall, ToolSpec


class AnthropicBrain:
    def __init__(self, config: BrainConfig, client: Any | None = None, max_tokens: int = 4096):
        self._model = config.model
        self._max_tokens = max_tokens
        if client is None:
            from anthropic import Anthropic
            kwargs: dict[str, Any] = {"api_key": config.api_key}
            if config.base_url:
                kwargs["base_url"] = config.base_url
            client = Anthropic(**kwargs)
        self._client = client

    def chat(self, messages: list[Message], tools: list[ToolSpec] = ()) -> BrainResponse:
        system, convo = _split_system(messages)
        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=system,
            messages=[_to_wire(m) for m in convo],
            tools=[_tool_to_wire(t) for t in tools] or None,
        )

        text_parts: list[str] = []
        calls: list[ToolCall] = []
        for block in response.content:
            block_type = getattr(block, "type", None)
            if block_type == "text":
                text_parts.append(getattr(block, "text", ""))
            elif block_type == "tool_use":
                calls.append(
                    ToolCall(
                        id=getattr(block, "id", ""),
                        name=getattr(block, "name", ""),
                        arguments=dict(getattr(block, "input", {}) or {}),
                    )
                )
        return BrainResponse(content="".join(text_parts), tool_calls=tuple(calls))


def _split_system(messages: list[Message]) -> tuple[str, list[Message]]:
    system_parts = [m.content for m in messages if m.role == "system"]
    convo = [m for m in messages if m.role != "system"]
    return "\n\n".join(p for p in system_parts if p), convo


def _to_wire(m: Message) -> dict:
    if m.role == "tool":
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": m.tool_call_id,
                    "content": m.content,
                }
            ],
        }
    if m.role == "assistant" and m.tool_calls:
        blocks: list[dict] = []
        if m.content:
            blocks.append({"type": "text", "text": m.content})
        for c in m.tool_calls:
            blocks.append({"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments})
        return {"role": "assistant", "content": blocks}
    return {"role": m.role, "content": m.content}


def _tool_to_wire(t: ToolSpec) -> dict:
    return {"name": t.name, "description": t.description, "input_schema": t.input_schema}
