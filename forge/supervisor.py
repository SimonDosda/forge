"""Supervisor: process-level supervisor for running golems.

Each running golem is its own subprocess (`python -m forge.runner <name>`).
The supervisor only manages lifecycle — spawning, sending SIGTERM, polling
liveness. The brain client, scheduler, and dialog polling all live inside
the child, so a crash in one golem cannot take down the forge or its peers.

Children are tied to the forge's lifetime: `shutdown()` terminates them all.
"""
from __future__ import annotations

import asyncio
import subprocess
import sys

from forge.store import ForgeStore


# How long to wait between SIGTERM and SIGKILL when sleeping a golem.
_TERM_TIMEOUT_S = 5.0
# How long to wait after spawn before assuming the child started successfully.
_STARTUP_PROBE_S = 0.5


class Supervisor:
    def __init__(self, store: ForgeStore):
        self._store = store
        self._procs: dict[str, subprocess.Popen[bytes]] = {}

    # ---- Process-tree lifecycle ----

    async def autowake_enabled(self) -> None:
        for spec in self._store.list_enabled():
            try:
                await self.awake(spec.name)
            except Exception as exc:  # noqa: BLE001 — keep other golems running
                print(f"[forge] failed to awake {spec.name!r}: {exc}", file=sys.stderr)

    async def shutdown(self) -> None:
        for name in list(self._procs.keys()):
            try:
                await self.sleep(name)
            except Exception as exc:  # noqa: BLE001
                print(f"[forge] error sleeping {name!r}: {exc}", file=sys.stderr)

    # ---- Per-golem lifecycle ----

    def is_awake(self, name: str) -> bool:
        proc = self._procs.get(name)
        if proc is None:
            return False
        if proc.poll() is not None:
            # Child has exited; reap it.
            del self._procs[name]
            return False
        return True

    def running_names(self) -> set[str]:
        return {name for name in list(self._procs.keys()) if self.is_awake(name)}

    async def awake(self, name: str) -> None:
        if self.is_awake(name):
            return
        # Verify the spec exists before spawning, so we get a clear error here
        # instead of via the child's exit code.
        self._store.get_golem(name)
        proc = subprocess.Popen(
            [sys.executable, "-m", "forge.runner", name],
            # Inherit stdout/stderr so child logs land in the forge's terminal
            # (or systemd's journal when running as a service).
        )
        self._procs[name] = proc

        # Brief probe: if the child immediately failed (e.g. invalid telegram
        # token, missing brain api key), surface that synchronously instead of
        # leaving the user wondering why the badge keeps flipping back to sleeping.
        await asyncio.sleep(_STARTUP_PROBE_S)
        if proc.poll() is not None:
            del self._procs[name]
            raise RuntimeError(
                f"golem {name!r} exited immediately (code {proc.returncode}); "
                "check the forge's stderr for details"
            )

    async def sleep(self, name: str) -> None:
        proc = self._procs.pop(name, None)
        if proc is None:
            return
        if proc.poll() is not None:
            return  # already dead
        proc.terminate()
        try:
            await asyncio.to_thread(proc.wait, _TERM_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            proc.kill()
            await asyncio.to_thread(proc.wait)

    async def reshape(self, name: str, new_name: str | None = None) -> None:
        """Restart the running child with the current stored spec.

        Pass `new_name` if the golem was renamed in the store; the new child
        is spawned under the new key.
        """
        if not self.is_awake(name):
            return
        await self.sleep(name)
        await self.awake(new_name or name)
