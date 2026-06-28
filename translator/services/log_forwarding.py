"""Forward ERROR-level logs to the admin's Telegram DM.

Failures used to land only in ``bot.log`` (which nobody watched). This attaches
a handler to the root logger that pushes any ``ERROR``+ record to the admin via
``error_sender.send_alert``.

The tricky part is the sync→async boundary: ``logging.Handler.emit`` is
synchronous and may run on the event-loop thread, while ``send_alert`` is a
coroutine. We capture the running loop at startup and schedule the coroutine
with ``asyncio.run_coroutine_threadsafe`` (the canonical thread-safe way to push
a coroutine onto a running loop). The returned future is intentionally ignored —
calling ``.result()`` from the loop thread would deadlock.

Three defenses keep this from looping or flooding:
1. records from the ``ALERT`` logger are skipped (that is where send_alert /
   httpx failures log — handling them here would recurse);
2. a reentrancy flag guards against an error logged *inside* ``emit``;
3. ``send_alert`` already throttles per signature key.
"""

from __future__ import annotations

import asyncio
import logging

from translator.services.error_sender import send_alert


class TelegramErrorHandler(logging.Handler):
    """Root-logger handler that DMs ERROR+ records to the admin (best effort)."""

    def __init__(self, loop: asyncio.AbstractEventLoop, level: int = logging.ERROR):
        super().__init__(level)
        self._loop = loop
        self._in_emit = False

    def emit(self, record: logging.LogRecord) -> None:
        # Skip our own alert plumbing and guard against reentry (defense 1 & 2).
        # Also honor an explicit opt-out: records logged with
        # ``extra={"no_forward": True}`` (relay/translation failures, which are
        # pull-only via /status) stay in bot.log but are never DM'd.
        if record.name == "ALERT" or self._in_emit or getattr(
            record, "no_forward", False
        ):
            return
        try:
            self._in_emit = True
            msg = self.format(record)
            key = f"log:{record.name}:{record.funcName}:{record.lineno}"
            asyncio.run_coroutine_threadsafe(
                send_alert(msg[:4000], key=key), self._loop
            )
        except Exception:
            # A logging handler must never raise; and we must not log here (would
            # risk recursing through this very handler).
            pass
        finally:
            self._in_emit = False


def attach_error_forwarding(
    loop: asyncio.AbstractEventLoop, level: int = logging.ERROR
) -> TelegramErrorHandler:
    """Build, configure and attach the error-forwarding handler to the root logger."""
    handler = TelegramErrorHandler(loop, level=level)
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    logging.getLogger().addHandler(handler)
    return handler
