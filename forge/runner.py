"""Per-golem subprocess entry point.

Spawned by the forge supervisor as `python -m forge.runner <id>`. Loads the
golem from `data/forge.json` by its stable id, awakes it, and blocks until
SIGTERM/SIGINT. Each running golem is its own process — crashes and reshapes
are isolated.
"""
import asyncio
import signal
import sys
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from forge.store import ForgeStore, GolemNotFoundError
from golem.golem import Golem


async def _run(id_: str) -> int:
    store = ForgeStore()
    try:
        spec = store.get_golem(id_)
    except GolemNotFoundError:
        print(f"[{id_}] not found in forge store", file=sys.stderr)
        return 2

    scheduler = AsyncIOScheduler()
    scheduler.start()
    golem = Golem(spec, store, scheduler)

    try:
        await golem.awake()
    except Exception as exc:  # noqa: BLE001
        print(f"[{id_}] awake failed: {exc}", file=sys.stderr)
        scheduler.shutdown(wait=False)
        return 1

    # Pick up Spirit edits made via the forge UI without a restart.
    scheduler.add_job(
        golem.reconcile_routines,
        "interval",
        seconds=30,
        id="_reconcile_routines",
    )

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    print(f"[{id_}] awake", file=sys.stderr)
    try:
        await stop_event.wait()
    finally:
        await golem.sleep()
        scheduler.shutdown(wait=False)
    print(f"[{id_}] sleeping", file=sys.stderr)
    return 0


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python -m forge.runner <id>", file=sys.stderr)
        sys.exit(2)
    # Ensure relative paths (data/forge.json, data/<id>/memory.json) resolve
    # against the project root regardless of where the supervisor invoked us.
    Path("data").mkdir(exist_ok=True)
    sys.exit(asyncio.run(_run(sys.argv[1])))


if __name__ == "__main__":
    main()
