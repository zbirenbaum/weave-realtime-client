import asyncio

from conversation_logger import log_conversation

idle_timer_task: asyncio.Task | None = None
IDLE_TIMEOUT_SECONDS = 5


async def _idle_timer_callback(logger, thread_id: str | None):
    global idle_timer_task
    try:
        await asyncio.sleep(IDLE_TIMEOUT_SECONDS)
        await logger.info(f"Event | no interaction for {IDLE_TIMEOUT_SECONDS} seconds")
        await log_conversation(logger, thread_id)
        idle_timer_task = None
    except asyncio.CancelledError:
        pass


def reset_idle_timer(logger, thread_id: str | None = None):
    global idle_timer_task
    if idle_timer_task is not None:
        idle_timer_task.cancel()
        idle_timer_task = None
    idle_timer_task = asyncio.create_task(_idle_timer_callback(logger, thread_id))
