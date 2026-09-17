"""Tests for the album (media-group) buffer and its sendMediaGroup constraints.

Telegram gives no "album complete" signal — parts arrive as independent updates
sharing a media_group_id — so the buffer debounces on quiet and flushes once.
"""

import asyncio
from types import SimpleNamespace

import pytest

from translator.services import media_group_buffer as mgb
from translator.services.media_group_buffer import (
    MediaGroupBuffer,
    can_send_as_album,
    debounce_seconds,
    input_media_type,
)


def _msg(msg_id):
    return SimpleNamespace(id=msg_id)


# --- buffering / debounce ---------------------------------------------------


@pytest.mark.asyncio
async def test_buffer_flushes_once_with_all_parts():
    flushed = []

    async def flush(items):
        flushed.append(items)

    buf = MediaGroupBuffer(flush, debounce=0.02)
    for i in (1, 2, 3):
        await buf.add(chat_id=7, media_group_id="g1", message=_msg(i))
    await asyncio.sleep(0.1)

    assert len(flushed) == 1, "an album must produce exactly one relay"
    assert [m.id for m in flushed[0]] == [1, 2, 3]


@pytest.mark.asyncio
async def test_buffer_orders_parts_by_message_id():
    # Updates can arrive out of order; album order is visible to readers.
    flushed = []

    async def flush(items):
        flushed.append([m.id for m in items])

    buf = MediaGroupBuffer(flush, debounce=0.02)
    for i in (3, 1, 2):
        await buf.add(7, "g1", _msg(i))
    await asyncio.sleep(0.1)

    assert flushed == [[1, 2, 3]]


@pytest.mark.asyncio
async def test_late_part_extends_the_debounce_window():
    """Each new part resets the timer, so a slow-arriving part isn't split off
    into its own post."""
    flushed = []

    async def flush(items):
        flushed.append([m.id for m in items])

    buf = MediaGroupBuffer(flush, debounce=0.08)
    await buf.add(7, "g1", _msg(1))
    await asyncio.sleep(0.05)  # less than the debounce
    await buf.add(7, "g1", _msg(2))
    await asyncio.sleep(0.05)  # still within the extended window
    assert flushed == []
    await asyncio.sleep(0.1)
    assert flushed == [[1, 2]]


@pytest.mark.asyncio
async def test_separate_groups_and_chats_do_not_mix():
    flushed = []

    async def flush(items):
        flushed.append([m.id for m in items])

    buf = MediaGroupBuffer(flush, debounce=0.02)
    await buf.add(7, "g1", _msg(1))
    await buf.add(7, "g2", _msg(2))
    await buf.add(8, "g1", _msg(3))  # same group id, different chat
    await asyncio.sleep(0.1)

    assert sorted(flushed) == [[1], [2], [3]]


@pytest.mark.asyncio
async def test_flush_error_does_not_escape():
    # One bad album must not take the relay down.
    async def flush(items):
        raise RuntimeError("boom")

    buf = MediaGroupBuffer(flush, debounce=0.02)
    await buf.add(7, "g1", _msg(1))
    await asyncio.sleep(0.1)
    assert buf.pending_groups == 0


@pytest.mark.asyncio
async def test_close_cancels_pending_groups():
    flushed = []

    async def flush(items):
        flushed.append(items)

    buf = MediaGroupBuffer(flush, debounce=0.05)
    await buf.add(7, "g1", _msg(1))
    await buf.close()
    await asyncio.sleep(0.1)

    assert flushed == []
    assert buf.pending_groups == 0


# --- debounce configuration -------------------------------------------------


def test_debounce_defaults_and_env_override(monkeypatch):
    monkeypatch.delenv("MEDIA_GROUP_DEBOUNCE", raising=False)
    assert debounce_seconds() == mgb.DEFAULT_DEBOUNCE
    monkeypatch.setenv("MEDIA_GROUP_DEBOUNCE", "0.5")
    assert debounce_seconds() == 0.5


@pytest.mark.parametrize("bad", ["abc", "0", "-1"])
def test_debounce_rejects_bad_values(monkeypatch, bad):
    # A garbage or non-positive value must not disable buffering entirely.
    monkeypatch.setenv("MEDIA_GROUP_DEBOUNCE", bad)
    assert debounce_seconds() == mgb.DEFAULT_DEBOUNCE


# --- sendMediaGroup constraints ---------------------------------------------


def test_input_media_type_mapping():
    assert input_media_type("photo") == "photo"
    assert input_media_type("video") == "video"
    assert input_media_type("doc") == "document"
    assert input_media_type("audio") == "audio"
    # Not permitted inside an album at all.
    assert input_media_type("animation") is None
    assert input_media_type("voice") is None
    assert input_media_type("video_note") is None
    assert input_media_type("text") is None


@pytest.mark.parametrize(
    "types,expected",
    [
        (["photo", "photo"], True),
        (["photo", "video"], True),          # photo+video may mix
        (["doc", "doc"], True),
        (["audio", "audio"], True),
        (["photo", "doc"], False),           # families may not mix
        (["audio", "photo"], False),
        (["photo"], False),                  # below the 2-item minimum
        (["photo"] * 11, False),             # above the 10-item maximum
        (["photo", "animation"], False),     # animation is never albumable
        (["photo", "voice"], False),
        (["photo", "text"], False),          # an oversized/unknown part
    ],
)
def test_can_send_as_album(types, expected):
    assert can_send_as_album(types) is expected
