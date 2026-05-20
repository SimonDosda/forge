"""Golem: a single running golem.

Wires Brain + Memory + Skills + Spirit + Dialog into a thinking loop and owns
its own lifecycle: `awake()`, `sleep()`, and `reshape()` (sleep → re-read spec
from the forge store → awake) for applying config changes without a process
restart.
"""
from __future__ import annotations

import asyncio
import json
import logging
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
from golem.spirit.spirit import Routine, Spirit

if TYPE_CHECKING:
    from forge.store import ForgeStore, GolemSpec


_MAX_TOOL_ITERATIONS = 8
_CONVO_TOPIC = "conversation"
_ERROR_TOPIC = "errors"
_log = logging.getLogger(__name__)


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
    def id(self) -> str:
        return self._spec.id

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
        self._reconcile_routines()
        await self._dialog.run(self.handle_user_message)
        self._awake = True

    async def sleep(self) -> None:
        if not self._awake:
            return
        if self._dialog is not None:
            try:
                await self._dialog.stop()
            except Exception:  # noqa: BLE001
                _log.exception("[%s] error stopping dialog", self.id)
        self._remove_routine_jobs()
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
        self._spec = self._store.get_golem(self.id)
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
        self._memory = TinyDbMemory(f"data/{spec.id}/memory.json")
        self._spirit = Spirit(self._store, spec.id)
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

    def _remove_routine_jobs(self) -> None:
        ns = f"{self.id}:"
        for job in list(self._scheduler.get_jobs()):
            if job.id.startswith(ns):
                self._scheduler.remove_job(job.id)

    # ---- Routines ----

    def reconcile_routines(self) -> bool:
        """Pick up Spirit edits — re-reads `spirit.routines` and updates jobs."""
        if not self._awake:
            return False
        return self._reconcile_routines()

    def _reconcile_routines(self) -> bool:
        assert self._spirit is not None
        version = self._spirit.version
        if version == self._last_reconciled_version:
            return False
        self._last_reconciled_version = version

        ns = f"{self.id}:"
        desired: dict[str, Routine] = {ns + r.id: r for r in self._spirit.routines}
        existing_ids = {j.id for j in self._scheduler.get_jobs() if j.id.startswith(ns)}

        for jid in existing_ids - desired.keys():
            self._scheduler.remove_job(jid)

        for jid, routine in desired.items():
            if jid in existing_ids:
                self._scheduler.remove_job(jid)
            self._scheduler.add_job(
                self.fire_routine,
                "cron",
                kwargs={"routine": routine},
                id=jid,
                **routine.cron,
            )
        return True

    # ---- Message dispatch ----

    async def handle_user_message(self, text: str) -> str:
        assert self._memory is not None
        stripped = (text or "").strip()
        if stripped.lower() == "/status":
            _log.info("[%s] /status command", self.id)
            return self._status_report()
        self._memory.add(_CONVO_TOPIC, {"role": "user", "content": text})
        _log.info("[%s] user message: %s", self.id, _truncate(text))
        try:
            reply = await self._think(user_text=text)
        except Exception as exc:
            return await self._handle_error(exc, source="user_message", input_text=text)
        self._memory.add(_CONVO_TOPIC, {"role": "assistant", "content": reply})
        _log.info("[%s] reply: %s", self.id, _truncate(reply))
        return reply

    async def fire_routine(self, routine: Routine) -> None:
        assert self._memory is not None and self._dialog is not None
        _log.info("[%s] firing routine %r", self.id, routine.id)
        try:
            reply = await self._think(user_text=routine.prompt, routine_id=routine.id)
        except Exception as exc:
            await self._handle_error(exc, source=f"routine:{routine.id}", input_text=routine.prompt)
            return
        self._memory.add(_CONVO_TOPIC, {
            "role": "assistant", "content": reply, "routine": routine.id,
        })
        if reply:
            await self._dialog.send(reply)

    def _status_report(self) -> str:
        """Build a human-readable health report covering each body component."""
        lines: list[str] = [f"🤖 {self._spec.name} — status", ""]

        # Brain
        b = self._spec.brain
        brain_label = f"{b.provider}/{b.model or '(no model)'}"
        if not b.model:
            lines.append(f"⚠️ Brain: {brain_label} — model missing")
        elif b.provider in ("mistral", "anthropic", "openai") and not b.api_key:
            lines.append(f"⚠️ Brain: {brain_label} — no API key")
        else:
            lines.append(f"✅ Brain: {brain_label}")

        # Memory
        if self._memory is None:
            lines.append("❌ Memory: not initialized")
        else:
            topics = self._memory.topics()
            counts = [(t, len(self._memory.get(t))) for t in topics]
            total = sum(n for _, n in counts)
            lines.append(f"✅ Memory: {len(topics)} topics, {total} entries (data/{self._spec.id}/memory.json)")
            for t, n in counts:
                lines.append(f"   • {t}: {n}")

        # Dialog
        dlg = self._spec.dialog
        if dlg.kind == "telegram":
            tg = dlg.telegram
            if not tg.token or not tg.chat_id:
                lines.append("⚠️ Dialog: telegram — token or chat_id missing")
            else:
                lines.append(f"✅ Dialog: telegram (chat {tg.chat_id})")
        else:
            lines.append(f"✅ Dialog: {dlg.kind}")

        # Skills
        if not self._skills:
            lines.append("⚠️ Skills: none enabled")
        else:
            tools_total = sum(len(s.tools) for s in self._skills)
            lines.append(f"✅ Skills: {len(self._skills)} ({tools_total} tools) — {', '.join(self._spec.skills)}")

        # Mission
        mission_len = len(self._spec.mission or "")
        if mission_len == 0:
            lines.append("⚠️ Mission: empty")
        else:
            lines.append(f"✅ Mission: {mission_len} chars")

        # Topic descriptions
        described = [t.id for t in self._spec.topics if t.description.strip()]
        if described:
            lines.append(f"✅ Topic prompts: {len(described)} described — {', '.join(described)}")

        # Routines + scheduler jobs
        ns = f"{self.id}:"
        jobs = [j for j in self._scheduler.get_jobs() if j.id.startswith(ns) and not j.id.endswith("_reconcile_routines")]
        routine_names = {r.id: (r.name or r.id) for r in self._spec.routines}
        if not self._spec.routines:
            lines.append("○ Routines: none configured")
        else:
            lines.append(f"✅ Routines: {len(self._spec.routines)} configured, {len(jobs)} scheduled")
            for j in jobs:
                nxt = j.next_run_time.strftime("%Y-%m-%d %H:%M %Z") if j.next_run_time else "—"
                rid = j.id[len(ns):]
                label = routine_names.get(rid, rid)
                lines.append(f"   • {label} — next: {nxt}")

        # Recent errors
        if self._memory is not None:
            recent_errors = self._memory.get(_ERROR_TOPIC)[-3:]
            if recent_errors:
                lines.append("")
                lines.append(f"⚠️ Last {len(recent_errors)} error(s):")
                for e in recent_errors:
                    when = (e.created_at or "").split("T")[0]
                    src = e.data.get("source", "?")
                    msg = _truncate(e.data.get("error", ""), 80)
                    lines.append(f"   • {when} [{src}] {msg}")

        return "\n".join(lines)

    async def _handle_error(self, exc: BaseException, *, source: str, input_text: str) -> str:
        """Persist error context, log full traceback, notify the dialog channel."""
        _log.exception("[%s] error in %s", self.id, source)
        message = f"{type(exc).__name__}: {exc}"
        if self._memory is not None:
            self._memory.add(_ERROR_TOPIC, {
                "source": source,
                "input": input_text,
                "error": message,
            })
            self._memory.add(_CONVO_TOPIC, {
                "role": "system",
                "content": f"[error in {source}] {message}",
            })
        notice = f"⚠️ I hit an error while handling that ({source}): {message}"
        if self._dialog is not None:
            try:
                await self._dialog.send(notice)
            except Exception:
                _log.exception("[%s] failed to send error notification", self.id)
        return notice

    # ---- Core loop ----

    async def _think(self, user_text: str, routine_id: str | None = None) -> str:
        assert self._brain is not None and self._spirit is not None
        tools, dispatch = self._collect_tools()

        now = datetime.now().astimezone()
        topics_block = _format_topics(self._spirit.topics)
        system = (
            f"{self._spirit.mission}"
            f"{topics_block}"
            f"\n\nToday: {now.date().isoformat()} ({now.strftime('%A')}). "
            f"Current time: {now.strftime('%H:%M %Z')}."
        )
        messages: list[Message] = [Message(role="system", content=system)]
        messages.extend(self._recent_history())
        if routine_id is not None:
            messages.append(Message(
                role="user",
                content=f"[routine:{routine_id}] {user_text}",
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


def _truncate(text: str, max_len: int = 120) -> str:
    text = (text or "").replace("\n", " ")
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


def _format_topics(topics) -> str:
    """Render described topics as a prompt block.

    Topics with no description are skipped — they're plain storage and don't
    need explanation. Returns an empty string if nothing to inject.
    """
    described = [t for t in topics if t.description.strip()]
    if not described:
        return ""
    lines = ["", "", "Memory topics:"]
    for t in described:
        lines.append(f"- {t.id}: {t.description.strip()}")
    return "\n".join(lines)
