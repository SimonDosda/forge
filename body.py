"""Body: wires Brain + Memory + Skills + Spirit + Dialog into a thinking loop."""
import asyncio
import json
from datetime import date, datetime
from typing import Any

from brain.brain import Brain
from core import Message, ToolCall, ToolSpec
from memory.memory import Memory
from skills.skill import Skill
from spirit.spirit import Schedule, Spirit
from dialog.dialog import Dialog


_MAX_TOOL_ITERATIONS = 8

# Memory topic where conversation messages are persisted.
_CONVO_TOPIC = "conversation"


class Body:
    def __init__(
        self,
        brain: Brain,
        memory: Memory,
        skills: list[Skill],
        spirit: Spirit,
        dialog: Dialog,
        history_window: int = 40,
    ):
        self._brain = brain
        self._memory = memory
        self._skills = skills
        self._spirit = spirit
        self._dialog = dialog
        self._history_window = history_window
        self._last_reconciled_mtime: float = -1.0

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
            await self._dialog.send(reply)

    def reconcile_schedules(self, scheduler: Any, reserved_prefix: str = "_") -> bool:
        """Sync APScheduler jobs to current `spirit.schedules`.

        No-op if Spirit hasn't changed since the last reconcile. Jobs whose id
        starts with `reserved_prefix` are left alone (used for housekeeping
        jobs like the reconciler itself).
        Returns True if any change was applied.
        """
        mtime = self._spirit.mtime
        if mtime == self._last_reconciled_mtime:
            return False
        self._last_reconciled_mtime = mtime

        desired: dict[str, Schedule] = {s.id: s for s in self._spirit.schedules}
        existing_ids = {
            j.id for j in scheduler.get_jobs() if not j.id.startswith(reserved_prefix)
        }

        for jid in existing_ids - desired.keys():
            scheduler.remove_job(jid)

        for jid, sched in desired.items():
            if jid in existing_ids:
                scheduler.remove_job(jid)
            scheduler.add_job(
                self.fire_schedule,
                "cron",
                kwargs={"schedule": sched},
                id=jid,
                **sched.cron,
            )
        return True

    # core loop

    async def _think(self, user_text: str, schedule_id: str | None = None) -> str:
        tools, dispatch = self._collect_tools()

        now = datetime.now().astimezone()
        system = (
            f"{self._spirit.system_prompt}\n\n"
            f"Today: {now.date().isoformat()} ({now.strftime('%A')}). "
            f"Current time: {now.strftime('%H:%M %Z')}."
        )
        messages: list[Message] = [Message(role="system", content=system)]
        messages.extend(self._recent_history())
        # User messages are persisted by handle_user_message before _think runs,
        # so they're already in _recent_history. Schedule prompts are not
        # persisted, so we inject them here with a marker.
        if schedule_id is not None:
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
                result = await asyncio.to_thread(_invoke, dispatch, call)
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
