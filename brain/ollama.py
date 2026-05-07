import json
import uuid
from typing import Any

import requests

from brain.brain import BrainConfig
from core import BrainResponse, Message, ToolCall, ToolSpec


class OllamaBrain:
    def __init__(self, config: BrainConfig, http: requests.Session | None = None, timeout_s: float = 120.0):
        self._model = config.model
        self._base_url = (config.base_url or "http://localhost:11434").rstrip("/")
        self._http = http or requests.Session()
        self._timeout = timeout_s

    def chat(self, messages: list[Message], tools: list[ToolSpec] = ()) -> BrainResponse:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [_to_wire(m) for m in messages],
            "stream": False,
        }
        if tools:
            payload["tools"] = [_tool_to_wire(t) for t in tools]

        response = self._http.post(
            f"{self._base_url}/api/chat", json=payload, timeout=self._timeout,
        )
        response.raise_for_status()
        data = response.json()
        msg = data.get("message", {}) or {}

        calls = tuple(
            ToolCall(
                id=str(uuid.uuid4()),
                name=c["function"]["name"],
                arguments=c["function"].get("arguments", {}) or {},
            )
            for c in (msg.get("tool_calls") or [])
        )
        return BrainResponse(content=msg.get("content", "") or "", tool_calls=calls)


def _to_wire(m: Message) -> dict:
    if m.role == "tool":
        return {"role": "tool", "content": m.content}
    if m.role == "assistant" and m.tool_calls:
        return {
            "role": "assistant",
            "content": m.content,
            "tool_calls": [
                {"function": {"name": c.name, "arguments": c.arguments}}
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
