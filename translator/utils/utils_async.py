import asyncio
import logging
import random

logger = logging.getLogger("PYRO")

# Deterministic failures that retrying cannot fix — raise immediately instead of
# burning attempts (and, for translation, API budget) on them.
NON_RETRYABLE = (ValueError, KeyError, TypeError, FileNotFoundError)


async def run_with_retries(
    coro,
    *args,
    attempts: int = 3,
    delay: float = 2.0,
    backoff: float = 2.0,
    max_delay: float = 30.0,
    non_retryable: tuple = NON_RETRYABLE,
):
    """Retry an async coroutine with exponential backoff + jitter.

    - ``non_retryable`` exceptions are re-raised immediately (no retry).
    - Backoff grows as ``delay * backoff**i``, capped at ``max_delay``, with
      0.5x–1.5x jitter to avoid hammering an overloaded API in lockstep.
    Call signature is unchanged: ``run_with_retries(fn, *args)``.
    """
    name = getattr(coro, "__name__", repr(coro))
    for i in range(attempts):
        try:
            return await coro(*args)
        except non_retryable:
            raise
        except Exception as e:
            if i == attempts - 1:
                logger.warning("Final retry failed for %s: %s", name, e)
                raise
            wait = min(max_delay, delay * (backoff ** i)) * (0.5 + random.random())
            logger.warning(
                "Retry %s/%s for %s in %.1fs: %s", i + 1, attempts, name, wait, e
            )
            await asyncio.sleep(wait)
