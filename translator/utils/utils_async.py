import asyncio
import logging

logger = logging.getLogger("PYRO")

async def run_with_retries(coro, *args, attempts: int = 3, delay: int = 2):
    """Retry an async coroutine up to N times with delay."""
    for i in range(attempts):
        try:
            return await coro(*args)
        except Exception as e:
            logger.warning("Retry attempt %s for %s: %s", i + 1, coro.__name__, e)
            if i == attempts - 1:
                raise
            await asyncio.sleep(delay)
