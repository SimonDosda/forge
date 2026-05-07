"""Wires Brain + Memory + Skills + Spirit + Voice into a running agent."""
import asyncio
import json
from typing import Any

from brain.brain import Brain
from core import Message, ToolCall, ToolSpec
from memory.memory import Memory
from skills.skill import Skill
from spirit.spirit import Schedule, Spirit
from voice.voice import Voice


_MAX_TOOL_ITERATIONS = 8

# Memory topic where conversation messages are persisted.
_CONVO_TOPIC = "conversation"


class Orchestrator:
    def __init__(
        self,
        brain: Brain,
        memory: Memory,
        skills: list[Skill],
        spirit: Spirit,
        voice: Voice,
        history_window: int = 40,
    ):
        self._brain = brain
        self._memory = memory
        self._skills = skills
        self._spirit = spirit
        self._voice = voice
        self._history_window = history_window

    # public entry points

    async def handle_user_message(self, text: str) -> str:
        self._memory.add(_CONVO_TOPIC, {"role": "user", "content": text})
        reply = await self._think(user_text=text)
        self._memory.add(_CONVO_TOPIC, {"role": "assistant", "content": reply})
        return reply

    async def fire_schedule(self, schedule: Schedule) -> None:
        reply = await self._think(user_text=schedule.prompt, schedule_id=schedule.id)
        self._memory.add(_CONVO_TOPIC, {
            "role": "assistant", "content": reply, "schedule": schedule.id,
        })
        if reply:
            await self._voice.send(reply)

    # core loop

    async def _think(self, user_text: str, schedule_id: str | None = None) -> str:
        tools, dispatch = self._collect_tools()

        messages: list[Message] = [Message(role="system", content=self._spirit.system_prompt)]
        messages.extend(self._recent_history())
        if schedule_id is None:
            messages.append(Message(role="user", content=user_text))
        else:
            messages.append(Message(
                role="user",
                content=f"[scheduled:{schedule_id}] {user_text}",
            ))

        for _ in range(_MAX_TOOL_ITERATIONS):
            response = await asyncio.to_thread(self._brain.chat, messages, tools)
            if not response.tool_calls:
                return response.content or ""

            messages.append(Message(
                role="assistant",
                content=response.content,
                tool_calls=response.tool_calls,
            ))
            for call in response.tool_calls:
                result = _invoke(dispatch, call)
                messages.append(Message(
                    role="tool",
                    tool_call_id=call.id,
                    content=result,
                ))

        return "(stopped: too many tool iterations)"

    # helpers

    def _collect_tools(self) -> tuple[list[ToolSpec], dict[str, Skill]]:
        tools: list[ToolSpec] = []
        dispatch: dict[str, Skill] = {}
        for skill in self._skills:
            for tool in skill.tools:
                if tool.name in dispatch:
                    raise ValueError(f"duplicate tool name across skills: {tool.name}")
                dispatch[tool.name] = skill
                tools.append(tool)
        return tools, dispatch

    def _recent_history(self) -> list[Message]:
        entries = self._memory.get(_CONVO_TOPIC)[-self._history_window:]
        out: list[Message] = []
        for e in entries:
            role = e.data.get("role")
            content = e.data.get("content", "")
            if role in ("user", "assistant") and content:
                out.append(Message(role=role, content=content))
        return out


def _invoke(dispatch: dict[str, Skill], call: ToolCall) -> str:
    skill = dispatch.get(call.name)
    if skill is None:
        return json.dumps({"error": f"unknown tool: {call.name}"})
    try:
        result = skill.call(call.name, call.arguments)
    except Exception as exc:  # noqa: BLE001 — feed errors back to the model
        return json.dumps({"error": str(exc)})
    return _to_json(result)


def _to_json(value: Any) -> str:
    try:
        return json.dumps(value, default=str, ensure_ascii=False)
    except TypeError:
        return json.dumps(str(value))
