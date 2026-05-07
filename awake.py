"""Entry point: wake the agent up — assemble the body and run it."""
import asyncio
import signal

from apscheduler.schedulers.asyncio import AsyncIOScheduler

import config
from body import Body
from brain.brain import BrainConfig, build_brain
from memory.json_store import JsonMemory
from skills.memory_skill import MemorySkill
from skills.open_meteo import OpenMeteo
from spirit.spirit import Spirit
from voice.telegram import TelegramVoice


async def run() -> None:
    settings = config.load()

    brain = build_brain(BrainConfig(
        provider=settings.brain_provider,
        model=settings.brain_model,
        api_key=settings.brain_api_key,
        base_url=settings.brain_base_url,
    ))
    memory = JsonMemory(settings.memory_root)
    spirit = Spirit(settings.spirit_path)
    voice = TelegramVoice(settings.telegram_token, settings.telegram_chat_id)

    skills = [MemorySkill(memory), OpenMeteo()]
    body = Body(brain=brain, memory=memory, skills=skills, spirit=spirit, voice=voice)

    scheduler = AsyncIOScheduler()
    for sched in spirit.schedules:
        scheduler.add_job(
            body.fire_schedule,
            "cron",
            kwargs={"schedule": sched},
            id=sched.id,
            **sched.cron,
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


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
