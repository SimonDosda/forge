from typing import Any, Awaitable, Callable


DailyCallback = Callable[[], Awaitable[None]]


class Scheduler:
    """Thin wrapper around APScheduler's AsyncIOScheduler."""

    def __init__(self, scheduler: Any | None = None):
        if scheduler is None:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler

            scheduler = AsyncIOScheduler()
        self._scheduler = scheduler

    def daily(self, hour: int, callback: DailyCallback) -> None:
        self._scheduler.add_job(callback, "cron", hour=hour, minute=0)

    def start(self) -> None:
        self._scheduler.start()

    def stop(self) -> None:
        self._scheduler.shutdown(wait=False)
