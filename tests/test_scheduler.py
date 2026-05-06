from dataclasses import dataclass, field
from typing import Any

from communication.scheduler import Scheduler


@dataclass
class _StubScheduler:
    jobs: list[dict] = field(default_factory=list)
    started: bool = False
    stopped: bool = False

    def add_job(self, func: Any, trigger: str, **kwargs):
        self.jobs.append({"func": func, "trigger": trigger, "kwargs": kwargs})

    def start(self):
        self.started = True

    def shutdown(self, wait: bool = True):
        self.stopped = True


async def _noop():
    return None


def test_daily_registers_cron_job_at_hour():
    stub = _StubScheduler()
    sched = Scheduler(scheduler=stub)

    sched.daily(hour=8, callback=_noop)

    assert len(stub.jobs) == 1
    job = stub.jobs[0]
    assert job["trigger"] == "cron"
    assert job["kwargs"]["hour"] == 8
    assert job["kwargs"]["minute"] == 0
    assert job["func"] is _noop


def test_start_and_stop_proxy_to_underlying_scheduler():
    stub = _StubScheduler()
    sched = Scheduler(scheduler=stub)

    sched.start()
    assert stub.started

    sched.stop()
    assert stub.stopped
