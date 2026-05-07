"""Golem: a single running golem.

Wires Brain + Memory + Skills + Spirit + Dialog into a thinking loop and owns
its own lifecycle: `awake()`, `sleep()`, and `reshape()` (sleep → re-read spec
from the forge store → awake) for applying config changes without a process
restart.
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from typing import TYPE_CHECKING, Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from golem.brain.brain import Brain, BrainConfig, build_brain
from golem.core import Message, ToolCall, ToolSpec
from golem.dialog.dialog import Dialog
from golem.dialog.telegram import TelegramDialog
from golem.memory.memory import Memory
from golem.memory.tinydb_store import TinyDbMemory
from golem.skills import build_skills
from golem.skills.skill import Skill
from golem.spirit.spirit import Schedule, Spirit

if TYPE_CHECKING:
    from forge.store import ForgeStore, GolemSpec


_MAX_TOOL_ITERATIONS = 8
_CONVO_TOPIC = "conversation"


class Golem:
    """A single golem instance.

    Components (brain, memory, dialog, …) are built lazily in `awake()` and torn
    down in `sleep()`. The instance holds a reference to the forge store so
    `reshape()` can re-read the spec and rebuild without losing the scheduler
    or the supervisor's tracking entry.
    """

    def __init__(self, spec: GolemSpec, store: ForgeStore, scheduler: AsyncIOScheduler):
        self._store = store
        self._scheduler = scheduler
        self._spec = spec
        self._awake = False
        self._brain: Brain | None = None
        self._memory: Memory | None = None
        self._dialog: Dialog | None = None
        self._spirit: Spirit | None = None
        self._skills: list[Skill] = []
        self._last_reconciled_version: int = -1
        self._history_window = 40

    @property
    def name(self) -> str:
        return self._spec.name

    @property
    def is_awake(self) -> bool:
        return self._awake

    # ---- Lifecycle ----

    async def awake(self) -> None:
        if self._awake:
            return
        self._build_components()
        self._reconcile_schedules()
        await self._dialog.run(self.handle_user_message)
        self._awake = True

    async def sleep(self) -> None:
        if not self._awake:
            return
        if self._dialog is not None:
            try:
                await self._dialog.stop()
            except Exception as exc:  # noqa: BLE001
                print(f"[golem:{self.name}] error stopping dialog: {exc}", file=sys.stderr)
        self._remove_schedule_jobs()
        self._brain = None
        self._memory = None
        self._dialog = None
        self._spirit = None
        self._skills = []
        self._last_reconciled_version = -1
        self._awake = False

    async def reshape(self) -> None:
        """Re-read the spec from the forge store and rebuild internals."""
        was_awake = self._awake
        if was_awake:
            await self.sleep()
        self._spec = self._store.get_golem(self.name)
        if was_awake:
            await self.awake()

    # ---- Build / teardown ----

    def _build_components(self) -> None:
        spec = self._spec
        self._brain = build_brain(BrainConfig(
            provider=spec.brain.provider,
            model=spec.brain.model,
            api_key=spec.brain.api_key,
            base_url=spec.brain.base_url,
        ))
        self._memory = TinyDbMemory(f"data/{spec.name}/memory.json")
        self._spirit = Spirit(self._store, spec.name)
        self._skills = build_skills(self._memory, list(spec.skills))
        self._dialog = self._build_dialog()

    def _build_dialog(self) -> Dialog:
        dlg = self._spec.dialog
        if dlg.kind != "telegram":
            raise ValueError(f"unsupported dialog kind: {dlg.kind!r}")
        tg = dlg.telegram
        if not tg.token or not tg.chat_id:
            raise ValueError("telegram dialog needs both token and chat_id")
        return TelegramDialog(tg.token, tg.chat_id)

    def _remove_schedule_jobs(self) -> None:
        ns = f"{self.name}:"
        for job in list(self._scheduler.get_jobs()):
            if job.id.startswith(ns):
                self._scheduler.remove_job(job.id)

    # ---- Schedules ----

    def reconcile_schedules(self) -> bool:
        """Pick up Spirit edits — re-reads `spirit.schedules` and updates jobs."""
        if not self._awake:
            return False
        return self._reconcile_schedules()

    def _reconcile_schedules(self) -> bool:
        assert self._spirit is not None
        version = self._spirit.version
        if version == self._last_reconciled_version:
            return False
        self._last_reconciled_version = version

        ns = f"{self.name}:"
        desired: dict[str, Schedule] = {ns + s.id: s for s in self._spirit.schedules}
        existing_ids = {j.id for j in self._scheduler.get_jobs() if j.id.startswith(ns)}

        for jid in existing_ids - desired.keys():
            self._scheduler.remove_job(jid)

        for jid, sched in desired.items():
            if jid in existing_ids:
                self._scheduler.remove_job(jid)
            self._scheduler.add_job(
                self.fire_schedule,
                "cron",
                kwargs={"schedule": sched},
                id=jid,
                **sched.cron,
            )
        return True

    # ---- Message dispatch ----

    async def handle_user_message(self, text: str) -> str:
        assert self._memory is not None
        self._memory.add(_CONVO_TOPIC, {"role": "user", "content": text})
        reply = await self._think(user_text=text)
        self._memory.add(_CONVO_TOPIC, {"role": "assistant", "content": reply})
        return reply

    async def fire_schedule(self, schedule: Schedule) -> None:
        assert self._memory is not None and self._dialog is not None
        reply = await self._think(user_text=schedule.prompt, schedule_id=schedule.id)
        self._memory.add(_CONVO_TOPIC, {
            "role": "assistant", "content": reply, "schedule": schedule.id,
        })
        if reply:
            await self._dialog.send(reply)

    # ---- Core loop ----

    async def _think(self, user_text: str, schedule_id: str | None = None) -> str:
        assert self._brain is not None and self._spirit is not None
        tools, dispatch = self._collect_tools()

        now = datetime.now().astimezone()
        system = (
            f"{self._spirit.system_prompt}\n\n"
            f"Today: {now.date().isoformat()} ({now.strftime('%A')}). "
            f"Current time: {now.strftime('%H:%M %Z')}."
        )
        messages: list[Message] = [Message(role="system", content=system)]
        messages.extend(self._recent_history())
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
        assert self._memory is not None
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
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"error": str(exc)})
    return _to_json(result)


def _to_json(value: Any) -> str:
    try:
        return json.dumps(value, default=str, ensure_ascii=False)
    except TypeError:
        return json.dumps(str(value))
