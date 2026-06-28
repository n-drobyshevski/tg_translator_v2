"""Tests for the ERROR-log → Telegram DM forwarding handler."""

import asyncio
import logging

from translator.services import log_forwarding


def _record(name="MAIN", level=logging.ERROR, msg="boom"):
    return logging.LogRecord(
        name=name, level=level, pathname=__file__, lineno=1, msg=msg, args=(), exc_info=None
    )


async def test_emit_schedules_send_alert(monkeypatch):
    seen = []

    async def fake_send_alert(text, key=None):
        seen.append((text, key))

    monkeypatch.setattr(log_forwarding, "send_alert", fake_send_alert)
    loop = asyncio.get_running_loop()
    handler = log_forwarding.TelegramErrorHandler(loop)
    handler.setFormatter(logging.Formatter("%(message)s"))

    handler.emit(_record(msg="kaboom"))
    await asyncio.sleep(0.05)  # let the scheduled coroutine run

    assert any("kaboom" in t for t, _ in seen)


async def test_emit_skips_alert_logger(monkeypatch):
    seen = []

    async def fake_send_alert(text, key=None):
        seen.append(text)

    monkeypatch.setattr(log_forwarding, "send_alert", fake_send_alert)
    loop = asyncio.get_running_loop()
    handler = log_forwarding.TelegramErrorHandler(loop)

    handler.emit(_record(name="ALERT", msg="recursive"))
    await asyncio.sleep(0.05)

    assert seen == []


async def test_emit_never_raises(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("send failed")

    monkeypatch.setattr(log_forwarding, "send_alert", boom)
    loop = asyncio.get_running_loop()
    handler = log_forwarding.TelegramErrorHandler(loop)

    # Must not propagate — a logging handler that raises breaks logging.
    handler.emit(_record())
    await asyncio.sleep(0)
