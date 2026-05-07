"""Supervisor: in-process registry of running golems.

Owns one shared `AsyncIOScheduler` and a name→Golem map. Its API mirrors the
golem lifecycle: `awake(name)`, `sleep(name)`, `reshape(name)`. The forge UI
calls these in response to user actions; the FastAPI lifespan hook calls
`autowake_enabled()` on startup and `shutdown()` on teardown.
"""
from __future__ import annotations

import sys

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from forge.store import ForgeStore
from golem.golem import Golem


class Supervisor:
    def __init__(self, store: ForgeStore):
        self._store = store
        self._scheduler = AsyncIOScheduler()
        self._running: dict[str, Golem] = {}
        self._started = False

    # ---- Process lifecycle ----

    async def autowake_enabled(self) -> None:
        if not self._started:
            self._scheduler.start()
            # Pick up Spirit edits made via the UI (system_prompt re-reads on every
            # chat, but schedules need an explicit reconcile when they change).
            self._scheduler.add_job(
                self._reconcile_all,
                "interval",
                seconds=30,
                id="_reconcile_schedules",
            )
            self._started = True
        for spec in self._store.list_enabled():
            try:
                await self.awake(spec.name)
            except Exception as exc:  # noqa: BLE001 — keep other golems running
                print(f"[forge] failed to awake {spec.name!r}: {exc}", file=sys.stderr)

    async def shutdown(self) -> None:
        for name in list(self._running.keys()):
            try:
                await self.sleep(name)
            except Exception as exc:  # noqa: BLE001
                print(f"[forge] error sleeping {name!r}: {exc}", file=sys.stderr)
        if self._started:
            self._scheduler.shutdown(wait=False)
            self._started = False

    # ---- Per-golem lifecycle ----

    def is_awake(self, name: str) -> bool:
        return name in self._running

    def running_names(self) -> set[str]:
        return set(self._running.keys())

    async def awake(self, name: str) -> Golem:
        if name in self._running:
            return self._running[name]
        spec = self._store.get_golem(name)
        golem = Golem(spec, self._store, self._scheduler)
        try:
            await golem.awake()
        except Exception:
            await golem.sleep()  # clean up partial state
            raise
        self._running[name] = golem
        return golem

    async def sleep(self, name: str) -> None:
        golem = self._running.pop(name, None)
        if golem is not None:
            await golem.sleep()

    async def reshape(self, name: str, new_name: str | None = None) -> None:
        """Restart the running instance with the current stored spec.

        If the golem was renamed in the store, pass `new_name` so we awake under
        the new key. No-op if the golem isn't currently running.
        """
        if name not in self._running:
            return
        await self.sleep(name)
        target = new_name or name
        await self.awake(target)

    # ---- Internal ----

    def _reconcile_all(self) -> None:
        for golem in self._running.values():
            try:
                golem.reconcile_schedules()
            except Exception as exc:  # noqa: BLE001
                print(f"[forge] reconcile error for {golem.name!r}: {exc}", file=sys.stderr)
