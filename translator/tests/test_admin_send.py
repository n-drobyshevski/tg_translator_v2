"""Tests for the single admin send path (rich first, classic fallback)."""

import pathlib
import re

import pytest
from pyrogram.errors import MessageNotModified

from translator.services import admin_menu, admin_send, rich_html
from translator.services.rich_html import Doc, Heading, Para


@pytest.fixture
def rich_on(monkeypatch):
    monkeypatch.setattr(admin_menu, "HAS_RICH_MESSAGES", True)


class FakeMsg:
    """A message with both send paths; each can be told to fail."""

    def __init__(self, *, rich_fails=False, markup_fails=False, with_rich=True):
        self.calls = []
        self.rich_fails = rich_fails
        self.markup_fails = markup_fails
        if not with_rich:
            self.reply_rich = None  # getattr() returns None → classic only

    async def reply_rich(self, rich, reply_markup=None):
        self.calls.append(("rich", rich.html, reply_markup))
        if self.rich_fails:
            raise ValueError("RICH_MESSAGE_INVALID")
        return "rich"

    async def reply_text(self, text, parse_mode=None, reply_markup=None):
        self.calls.append(("classic", text, reply_markup))
        if self.markup_fails and reply_markup is not None:
            raise ValueError("REPLY_MARKUP_INVALID")
        return "classic"


class FakeCQ:
    def __init__(self, *, rich_fails=False, all_fail=False, not_modified=False):
        self.calls = []
        self.rich_fails = rich_fails
        self.all_fail = all_fail
        self.not_modified = not_modified
        self.message = FakeMsg()

    async def edit_message_text(self, text=None, parse_mode=None, rich_message=None,
                                reply_markup=None):
        self.calls.append(("edit", text, rich_message, reply_markup))
        if self.not_modified:
            raise MessageNotModified
        if self.all_fail or (rich_message is not None and self.rich_fails):
            raise ValueError("EDIT_FAILED")
        return "edited"


def _doc():
    return Doc(Heading("Title"), Para("body"))


# --------------------------------------------------------------------------- #
# reply
# --------------------------------------------------------------------------- #


async def test_reply_goes_rich_when_enabled(rich_on):
    msg = FakeMsg()
    assert await admin_send.reply(msg, _doc()) == "rich"
    assert msg.calls == [("rich", "<h3>Title</h3><p>body</p>", None)]


async def test_reply_with_rows_puts_buttons_in_the_body(rich_on):
    msg = FakeMsg()
    await admin_send.reply(msg, _doc(), rows=[[("A", "nav:a")]])
    kind, body, markup = msg.calls[0]
    assert kind == "rich" and markup is None
    assert body.startswith("<h3>Title</h3>") and "<tg-button-row>" in body


async def test_reply_keyboard_rides_along_with_the_rich_send(rich_on):
    msg = FakeMsg()
    keyboard = object()
    await admin_send.reply(msg, _doc(), reply_markup=keyboard)
    assert msg.calls == [("rich", "<h3>Title</h3><p>body</p>", keyboard)]


async def test_a_refused_rich_reply_falls_back_to_classic_with_the_keyboard(rich_on):
    msg = FakeMsg(rich_fails=True)
    keyboard = object()
    assert await admin_send.reply(msg, _doc(), reply_markup=keyboard) == "classic"
    assert msg.calls[-1] == ("classic", "<b>Title</b>\nbody", keyboard)


async def test_a_refused_keyboard_still_delivers_the_text(rich_on):
    msg = FakeMsg(rich_fails=True, markup_fails=True)
    assert await admin_send.reply(msg, _doc(), reply_markup=object()) == "classic"
    assert msg.calls[-1] == ("classic", "<b>Title</b>\nbody", None)


async def test_no_reply_rich_means_classic_only(rich_on):
    msg = FakeMsg(with_rich=False)
    await admin_send.reply(msg, _doc())
    assert [c[0] for c in msg.calls] == ["classic"]


async def test_kill_switch_means_classic_only(rich_on, monkeypatch):
    monkeypatch.setenv(rich_html.RICH_ENV, "0")
    msg = FakeMsg()
    await admin_send.reply(msg, _doc(), rows=[[("A", "nav:a")]])
    assert [c[0] for c in msg.calls] == ["classic"]


async def test_a_legacy_str_is_sent_as_paragraphs(rich_on):
    msg = FakeMsg()
    await admin_send.reply(msg, "<b>a</b>\nb")
    assert msg.calls == [("rich", "<p><b>a</b><br>b</p>", None)]


async def test_an_oversized_legacy_str_is_capped_for_classic(rich_on):
    msg = FakeMsg(with_rich=False)
    await admin_send.reply(msg, "x" * 10_000)
    assert len(msg.calls[0][1]) <= rich_html.CLASSIC_LIMIT


async def test_repeated_rich_failures_open_the_breaker(rich_on):
    msg = FakeMsg(rich_fails=True)
    for _ in range(admin_menu._RichBreaker.THRESHOLD):
        await admin_send.reply(msg, _doc())
    msg.calls.clear()
    await admin_send.reply(msg, _doc())
    assert [c[0] for c in msg.calls] == ["classic"], "an open breaker skips rich"


# --------------------------------------------------------------------------- #
# edit
# --------------------------------------------------------------------------- #


async def test_rich_edit_omits_text(rich_on):
    """kurigram checks ``text`` first and silently ignores ``rich_message`` when
    both are given — the menus-only version's rich edits were quietly classic."""
    cq = FakeCQ()
    assert await admin_send.edit(cq, _doc(), rows=[[("A", "nav:a")]]) == "edited"
    _, text, rich, markup = cq.calls[0]
    assert text is None and rich is not None and markup is None
    assert "<tg-button-row>" in rich.html


async def test_a_refused_rich_edit_falls_back_to_a_classic_edit(rich_on):
    cq = FakeCQ(rich_fails=True)
    await admin_send.edit(cq, _doc(), rows=[[("A", "nav:a")]])
    _, text, rich, markup = cq.calls[-1]
    assert text == "<b>Title</b>\nbody" and rich is None and markup is not None


async def test_edit_without_rows_sends_no_markup(rich_on, monkeypatch):
    monkeypatch.setenv(rich_html.RICH_ENV, "0")
    cq = FakeCQ()
    await admin_send.edit(cq, _doc())
    assert cq.calls == [("edit", "<b>Title</b>\nbody", None, None)]


async def test_when_every_edit_fails_the_screen_is_sent_as_a_new_message(rich_on):
    cq = FakeCQ(all_fail=True)
    assert await admin_send.edit(cq, _doc()) == "rich"
    assert cq.message.calls[0][0] == "rich"


async def test_message_not_modified_propagates(rich_on):
    cq = FakeCQ(not_modified=True)
    with pytest.raises(MessageNotModified):
        await admin_send.edit(cq, _doc(), rows=[[("A", "nav:a")]])
    assert cq.message.calls == [], "identical content is not a failure to recover from"


# --------------------------------------------------------------------------- #
# Guard: nothing bypasses this module
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("module", ["admin_commands.py", "admin_menu.py", "admin_wizard.py"])
def test_no_direct_sends_outside_admin_send(module):
    """Every admin message must be able to go rich; a direct ``reply_text`` or
    ``edit_message_text`` call is a message that silently can't."""
    source = (pathlib.Path(admin_send.__file__).parent / module).read_text("utf-8")
    code = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )
    # Strip docstrings/comments mentioning the names; only calls matter.
    calls = re.findall(r"\.(reply_text|edit_message_text|reply_rich)\(", code)
    assert calls == [], f"{module} sends directly: {calls}"
