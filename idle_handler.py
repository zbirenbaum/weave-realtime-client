import asyncio

from config import IDLE_TIMEOUT_SECONDS
from conversation_logger import log_conversation

idle_timer_task: asyncio.Task | None = None


async def _idle_timer_callback(logger, thread_id: str | None):
    global idle_timer_task
    try:
        await asyncio.sleep(IDLE_TIMEOUT_SECONDS)
        await logger.info(f"Idle | No interaction for {IDLE_TIMEOUT_SECONDS} seconds")
        await log_conversation(logger, thread_id)
        idle_timer_task = None
    except asyncio.CancelledError:
        pass


async def clear_idle_timer(logger):
    """Cancel the idle timer without starting a new one. Use when user or assistant starts speaking."""

    global idle_timer_task
    if idle_timer_task is not None:
        if logger is not None:
            await logger.info("Idle | Clearing idle timer")
        idle_timer_task.cancel()
        idle_timer_task = None


async def reset_idle_timer(logger, thread_id: str | None = None):
    """Cancel any existing idle timer and start a new one. Use when user or assistant finishes speaking."""

    global idle_timer_task
    await clear_idle_timer(None)
    await logger.info("Idle | Restarting idle timer")
    idle_timer_task = asyncio.create_task(_idle_timer_callback(logger, thread_id))
