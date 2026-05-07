"""Entry point: wake the agent up — assemble the body and run it."""
import asyncio
import os
import signal
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler

import config
from body import Body
from brain.brain import BrainConfig, build_brain
from memory.tinydb_store import TinyDbMemory
from skills import default_skills
from spirit.spirit import Spirit
from voice.telegram import TelegramVoice


_PID_FILE = Path("data/bot.pid")


def _write_pid_file() -> None:
    _PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PID_FILE.write_text(str(os.getpid()))


def _remove_pid_file() -> None:
    try:
        _PID_FILE.unlink()
    except FileNotFoundError:
        pass


async def run() -> None:
    settings = config.load()
    _write_pid_file()

    brain = build_brain(BrainConfig(
        provider=settings.brain_provider,
        model=settings.brain_model,
        api_key=settings.brain_api_key,
        base_url=settings.brain_base_url,
    ))
    memory = TinyDbMemory(settings.memory_path)
    spirit = Spirit(settings.spirit_path)
    voice = TelegramVoice(settings.telegram_token, settings.telegram_chat_id)

    body = Body(brain=brain, memory=memory, skills=default_skills(memory), spirit=spirit, voice=voice)

    scheduler = AsyncIOScheduler()
    body.reconcile_schedules(scheduler)
    # Pick up Spirit edits made via the View without a restart.
    scheduler.add_job(
        body.reconcile_schedules,
        "interval",
        kwargs={"scheduler": scheduler},
        seconds=30,
        id="_reconcile_schedules",
    )
    scheduler.start()

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    await voice.run(body.handle_user_message)
    try:
        await stop_event.wait()
    finally:
        scheduler.shutdown(wait=False)
        await voice.stop()
        _remove_pid_file()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
