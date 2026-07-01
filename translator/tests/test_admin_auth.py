"""Regression tests for the admin DM authorization gate.

These lock in the guarantee that only ``CONFIG.ADMIN_CHAT_IDS`` can open the
admin DM menu: the ``_is_admin`` predicate, the live-read behaviour, the
composed ``filters.private & _admin_filter()`` gate on the DM dispatcher, and
the defense-in-depth group-1 catch-all that drops non-admin DMs.
"""

import asyncio
import logging
import types

import pytest

from pyrogram import enums

from translator.config import CONFIG
from translator.services import admin_commands


def _user(uid):
    return types.SimpleNamespace(id=uid)


def _msg(uid, *, private=True):
    """A minimal Pyrogram-message stand-in for filter evaluation."""
    chat_type = enums.ChatType.PRIVATE if private else enums.ChatType.CHANNEL
    return types.SimpleNamespace(
        from_user=_user(uid) if uid is not None else None,
        sender_chat=None,
        chat=types.SimpleNamespace(id=uid or 0, type=chat_type),
    )


# --------------------------------------------------------------------------- #
# A. _is_admin predicate
# --------------------------------------------------------------------------- #

def test_is_admin_accepts_configured_admin(monkeypatch):
    monkeypatch.setattr(CONFIG, "ADMIN_CHAT_IDS", [111, 222])
    assert admin_commands._is_admin(None, None, _msg(111)) is True


def test_is_admin_rejects_non_admin(monkeypatch):
    monkeypatch.setattr(CONFIG, "ADMIN_CHAT_IDS", [111, 222])
    assert admin_commands._is_admin(None, None, _msg(999)) is False


def test_is_admin_rejects_missing_from_user(monkeypatch):
    monkeypatch.setattr(CONFIG, "ADMIN_CHAT_IDS", [111])
    assert admin_commands._is_admin(None, None, _msg(None)) is False


def test_is_admin_rejects_when_no_admins_configured(monkeypatch):
    monkeypatch.setattr(CONFIG, "ADMIN_CHAT_IDS", [])
    assert admin_commands._is_admin(None, None, _msg(111)) is False


def test_is_admin_reads_roster_live(monkeypatch):
    """The predicate must re-read CONFIG on every call (not capture at import)."""
    msg = _msg(111)
    monkeypatch.setattr(CONFIG, "ADMIN_CHAT_IDS", [111])
    assert admin_commands._is_admin(None, None, msg) is True
    monkeypatch.setattr(CONFIG, "ADMIN_CHAT_IDS", [222])
    assert admin_commands._is_admin(None, None, msg) is False


# --------------------------------------------------------------------------- #
# B. Handler composition + defense-in-depth catch-all
# --------------------------------------------------------------------------- #

class FakePyro:
    """Records handler registrations instead of wiring a real client."""

    def __init__(self):
        self.msg_handlers = []  # (filter, group, fn)
        self.cb_handlers = []   # (filter, group, fn)

    def on_message(self, flt=None, group=0):
        def deco(fn):
            self.msg_handlers.append((flt, group, fn))
            return fn
        return deco

    def on_callback_query(self, flt=None, group=0):
        def deco(fn):
            self.cb_handlers.append((flt, group, fn))
            return fn
        return deco


class _RecordingMsg:
    def __init__(self, uid):
        self.from_user = _user(uid) if uid is not None else None
        self.replies = []

    async def reply_text(self, *args, **kwargs):
        self.replies.append((args, kwargs))


def _register():
    fake = FakePyro()
    admin_commands.register_admin_handlers(fake)
    return fake


def test_registers_dispatch_and_catchall_and_callback():
    fake = _register()
    groups = sorted(g for _, g, _ in fake.msg_handlers)
    assert groups == [0, 1], "expected a group-0 dispatcher and a group-1 guard"
    assert len(fake.cb_handlers) == 1, "expected one admin-gated callback handler"


async def test_dispatch_filter_rejects_non_admins(monkeypatch):
    """The group-0 DM handler's composed filter must reject non-admins.

    This is the regression guard: if someone drops ``& _admin_filter()`` from
    the registration, the non-admin case below starts matching and fails.
    """
    monkeypatch.setattr(CONFIG, "ADMIN_CHAT_IDS", [111])
    fake = _register()
    flt = next(f for f, g, _ in fake.msg_handlers if g == 0)
    # Pyrogram runs sync filter predicates via ``client.loop.run_in_executor``.
    client = types.SimpleNamespace(loop=asyncio.get_running_loop(), executor=None)
    assert await flt(client, _msg(111)), "admin private DM should match dispatcher"
    assert not await flt(client, _msg(999)), "non-admin DM must NOT match dispatcher"


async def test_catchall_drops_non_admin_with_warning(monkeypatch, caplog):
    monkeypatch.setattr(CONFIG, "ADMIN_CHAT_IDS", [111])
    fake = _register()
    catch_all = next(fn for _, g, fn in fake.msg_handlers if g == 1)
    msg = _RecordingMsg(999)
    with caplog.at_level(logging.WARNING, logger="ADMIN"):
        await catch_all(object(), msg)
    assert msg.replies == [], "non-admin must receive no reply"
    assert any(
        "unauthorized" in r.getMessage() and "999" in r.getMessage()
        for r in caplog.records
    ), "expected a WARNING naming the unauthorized user id"


async def test_catchall_ignores_admin_silently(monkeypatch, caplog):
    monkeypatch.setattr(CONFIG, "ADMIN_CHAT_IDS", [111])
    fake = _register()
    catch_all = next(fn for _, g, fn in fake.msg_handlers if g == 1)
    msg = _RecordingMsg(111)
    with caplog.at_level(logging.WARNING, logger="ADMIN"):
        await catch_all(object(), msg)
    assert msg.replies == [], "guard never replies"
    assert not any(
        "unauthorized" in r.getMessage() for r in caplog.records
    ), "admin DMs must not be logged as unauthorized"
