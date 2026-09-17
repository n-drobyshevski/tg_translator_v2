"""Tests for the relay error-handling hardening:

- per-message EventRecorder isolation (the shared-recorder concurrency bug that
  produced empty-chat_id sends),
- edited posts with no relayed original → skipped + readable heads-up DM,
- genuine relay failures → readable admin DM alert.
"""

import asyncio
from unittest.mock import AsyncMock

import pytest

from translator import bot
from translator.services.event_logger import EventRecorder


class _DBLessRecorder(EventRecorder):
    """Real recorder minus the DB write, but keeping finalize()'s reset() — that
    reset is exactly what corrupts a *shared* recorder mid-send."""

    def finalize(self) -> None:  # noqa: D401
        self.reset()


class _MediaStubs:
    """No-op stubs for every media send the handler dispatches on.

    ``handle_message`` builds its dispatch dict eagerly from ``sender.send_*``,
    so a fake sender must expose all of them or attribute lookup fails before
    the test's own path is reached. Subclasses override only what they assert on.
    """

    async def send_photo_message(self, *a, **kw):
        return True

    async def send_video_message(self, *a, **kw):
        return True

    async def send_document_message(self, *a, **kw):
        return True

    async def send_animation_message(self, *a, **kw):
        return True

    async def send_audio_message(self, *a, **kw):
        return True

    async def send_voice_message(self, *a, **kw):
        return True

    async def send_video_note_message(self, *a, **kw):
        return True


class _FakeChat:
    def __init__(self, chat_id, title, username):
        self.id = chat_id
        self.title = title
        self.username = username


class _FakeMsg:
    def __init__(self, msg_id, chat):
        self.id = msg_id
        self.chat = chat
        self.text = "привет"
        self.caption = None
        self.entities = None
        self.caption_entities = None
        self.photo = self.video = self.document = None


class _CapturingPyro:
    """Captures the handlers register_handlers wires up so tests can call them."""

    def __init__(self):
        self.handlers = {}

    def on_message(self, _filt):
        def deco(fn):
            self.handlers["message"] = fn
            return fn

        return deco

    def on_edited_message(self, _filt):
        def deco(fn):
            self.handlers["edit"] = fn
            return fn

        return deco


class _FakeQueue:
    def __init__(self, meta=None):
        self._meta = meta if meta is not None else {"file": {}}

    async def put(self, req):
        if not req.response.done():
            req.response.set_result(self._meta)


def _wire(monkeypatch, sender, *, media=("", 0, "text"), meta=None, translated="translated"):
    """Patch the heavy pipeline pieces and return the registered handlers."""
    # Fresh per-message recorder without touching the DB.
    monkeypatch.setattr(bot, "EventRecorder", _DBLessRecorder)
    monkeypatch.setattr(bot, "query_queue", _FakeQueue(meta))
    monkeypatch.setattr(bot, "get_media_info", lambda msg, max_size: media)
    monkeypatch.setattr(bot, "entities_to_html", lambda text, ents: text)

    async def _translate(*_args, **_kwargs):
        return translated

    monkeypatch.setattr(bot, "translate_html", _translate)

    async def _rwr(func, *args, **kwargs):
        # Faithful enough for tests: just invoke the wrapped coroutine so real
        # exceptions from the sender propagate to the handler's except block.
        return await func(*args, **kwargs)

    monkeypatch.setattr(bot, "run_with_retries", _rwr)

    dest_by_src = {1: 111, 2: 222}
    name_by_dest = {111: "dest1", 222: "dest2"}
    monkeypatch.setattr(bot.CONFIG, "get_destination_id", lambda src: dest_by_src[src])
    monkeypatch.setattr(bot.CONFIG, "get_channel_name", lambda d: name_by_dest[d])

    pyro = _CapturingPyro()
    anthropic = object()
    bot.register_handlers(pyro, anthropic, sender, _DBLessRecorder())
    return pyro.handlers


@pytest.mark.asyncio
async def test_per_message_recorder_isolation(monkeypatch):
    """Two concurrent messages must each get their OWN recorder carrying their
    OWN destination — the fix for the shared-recorder empty-chat_id bug."""
    seen = []

    class _Sender(_MediaStubs):
        async def send_message(self, text, recorder):
            # Yield so the two handlers genuinely interleave.
            await asyncio.sleep(0)
            seen.append(
                (
                    recorder.get("source_channel_id"),
                    recorder.get("dest_channel_id"),
                    id(recorder),
                )
            )
            return True

    handlers = _wire(monkeypatch, _Sender())
    handle = handlers["message"]

    msg1 = _FakeMsg(10, _FakeChat(1, "Channel One", "chan1"))
    msg2 = _FakeMsg(20, _FakeChat(2, "Channel Two", "chan2"))
    await asyncio.gather(handle(None, msg1), handle(None, msg2))

    by_src = {src: (dest, rid) for src, dest, rid in seen}
    # Each message's send saw the destination resolved for ITS source channel.
    assert by_src[1][0] == 111
    assert by_src[2][0] == 222
    # And they used distinct recorder objects (would be the same shared object
    # under the old code).
    assert by_src[1][1] != by_src[2][1]


@pytest.mark.asyncio
async def test_relay_failure_sends_readable_alert(monkeypatch):
    alert = AsyncMock()
    monkeypatch.setattr(bot, "send_alert", alert)

    class _Sender(_MediaStubs):
        async def send_message(self, text, recorder):
            raise RuntimeError("boom")

    handlers = _wire(monkeypatch, _Sender())
    msg = _FakeMsg(10, _FakeChat(1, "Channel One", "chan1"))

    # Must not raise out of the handler.
    await handlers["message"](None, msg)

    alert.assert_awaited_once()
    text, kwargs = alert.await_args.args[0], alert.await_args.kwargs
    assert "Relay failed" in text
    assert "Channel One" in text
    assert "https://t.me/chan1/10" in text
    assert kwargs["key"].startswith("relay-fail:1:")


@pytest.mark.asyncio
async def test_edit_without_original_skips_and_heads_up(monkeypatch):
    alert = AsyncMock()
    monkeypatch.setattr(bot, "send_alert", alert)
    # No relayed original for this edit.
    monkeypatch.setattr(bot.CONFIG, "get_destination_msg_id", lambda *a: None)

    class _Sender(_MediaStubs):
        async def send_message(self, *a):
            return True

        async def edit_message(self, *a):
            raise AssertionError("edit_message must not be called when there is no original")

        async def edit_caption(self, *a):
            raise AssertionError("edit_caption must not be called when there is no original")

    handlers = _wire(monkeypatch, _Sender())
    # Private channel (-100…) → the alert link uses the t.me/c/ form.
    msg = _FakeMsg(13337, _FakeChat(-1001504042253, "Peace", None))

    # Must not raise — this is an expected, routine skip.
    await handlers["edit"](None, msg)

    alert.assert_awaited_once()
    text, kwargs = alert.await_args.args[0], alert.await_args.kwargs
    assert "Edited post skipped" in text
    assert "https://t.me/c/1504042253/13337" in text
    assert kwargs["key"] == "edit-no-dest:-1001504042253"


@pytest.mark.asyncio
async def test_long_caption_photo_splits_into_photo_plus_reply(monkeypatch):
    """A photo whose translated text exceeds 1024 chars posts the lead as the
    photo caption and the remainder as a reply to that photo."""
    from translator.utils.message_utils import _tags_balanced

    lead = "<b>Lead sentence.</b>"
    paras = "\n".join(f"<p>Paragraph number {i} with some body text.</p>" for i in range(40))
    long_html = f"{lead}\n\n{paras}"
    assert len(long_html) > 1024  # forces the split path

    calls = {}

    class _Sender(_MediaStubs):
        async def send_photo_message(self, photo, caption, recorder):
            calls["photo_caption"] = caption
            recorder.set(dest_message_id=999)  # the photo's message id
            return True

        async def send_message(self, text, recorder, reply_to_message_id=None):
            calls["reply_text"] = text
            calls["reply_to"] = reply_to_message_id
            return True

    handlers = _wire(
        monkeypatch,
        _Sender(),
        media=("fileid", 123, "photo"),
        meta={"file": {}, "file_download_link": "http://img/x.jpg"},
        translated=long_html,
    )
    msg = _FakeMsg(10, _FakeChat(1, "Channel One", "chan1"))
    await handlers["message"](None, msg)

    # Photo got a non-empty, within-limit, tag-balanced caption…
    assert 0 < len(calls["photo_caption"]) <= 1024
    assert _tags_balanced(calls["photo_caption"])
    assert calls["photo_caption"].startswith(lead)
    # …and the remainder was posted as a reply to the photo.
    assert calls["reply_to"] == 999
    assert calls["reply_text"]
    assert _tags_balanced(calls["reply_text"])


@pytest.mark.asyncio
async def test_animation_relays_through_send_animation(monkeypatch):
    """A GIF must go out via sendAnimation, not fall through to a text-only relay."""
    calls = {}

    class _Sender(_MediaStubs):
        async def send_animation_message(self, animation, caption, recorder):
            calls["animation"] = (animation, caption)
            return True

        async def send_message(self, text, recorder, reply_to_message_id=None):
            calls["text"] = text
            return True

    handlers = _wire(
        monkeypatch,
        _Sender(),
        media=("gif-id", 123, "animation"),
        meta={"file": {}, "file_download_link": "http://img/x.gif"},
        translated="<b>Short caption.</b>",
    )
    await handlers["message"](None, _FakeMsg(10, _FakeChat(1, "Channel One", "chan1")))

    assert calls["animation"] == ("gif-id", "<b>Short caption.</b>")
    assert "text" not in calls  # the caption rode along with the media


@pytest.mark.asyncio
async def test_video_note_posts_bare_note_plus_reply(monkeypatch):
    """sendVideoNote accepts no caption, so the note goes out bare and the whole
    translation follows as a reply to it — not silently dropped with the caption."""
    calls = {}

    class _Sender(_MediaStubs):
        async def send_video_note_message(self, note, caption, recorder):
            calls["note"] = (note, caption)
            recorder.set(dest_message_id=555)
            return True

        async def send_message(self, text, recorder, reply_to_message_id=None):
            calls["reply_text"] = text
            calls["reply_to"] = reply_to_message_id
            return True

    handlers = _wire(
        monkeypatch,
        _Sender(),
        media=("note-id", 123, "video_note"),
        meta={"file": {}, "file_download_link": "http://img/x.mp4"},
        translated="<b>Translated note text.</b>",
    )
    await handlers["message"](None, _FakeMsg(10, _FakeChat(1, "Channel One", "chan1")))

    # The note itself carried no caption...
    assert calls["note"] == ("note-id", "")
    # ...and the full translation landed as a reply to it.
    assert calls["reply_text"] == "<b>Translated note text.</b>"
    assert calls["reply_to"] == 555


@pytest.mark.asyncio
async def test_media_group_relays_as_one_album(monkeypatch):
    """An album must produce ONE sendMediaGroup with ONE translated caption —
    not one post (and one translation) per part."""
    calls = {}
    translations = []

    class _Sender(_MediaStubs):
        async def send_media_group(self, album, caption, recorder):
            calls["album"] = album
            calls["caption"] = caption
            recorder.set(dest_message_id=777)
            return True

        async def send_message(self, text, recorder, reply_to_message_id=None):
            calls.setdefault("texts", []).append(text)
            return True

    # Parts arrive as separate updates; only the first carries the caption.
    parts = []
    for i, has_caption in enumerate([True, False, False], start=1):
        m = _FakeMsg(i, _FakeChat(1, "Channel One", "chan1"))
        m.text = "подпись альбома" if has_caption else None
        m.caption = None
        m.media_group_id = "album-1"
        parts.append(m)

    media_by_id = {1: ("f1", 10, "photo"), 2: ("f2", 10, "photo"), 3: ("f3", 10, "video")}
    handlers = _wire(
        monkeypatch,
        _Sender(),
        meta={"file": {}, "file_download_link": "http://img/x.jpg"},
        translated="<b>Album caption.</b>",
    )
    monkeypatch.setattr(bot, "get_media_info", lambda msg, max_size: media_by_id[msg.id])

    async def _counting_translate(*_a, **_kw):
        translations.append(1)
        return "<b>Album caption.</b>"

    monkeypatch.setattr(bot, "translate_html", _counting_translate)
    # Buffer flushes on quiet; keep the test fast.
    monkeypatch.setenv("MEDIA_GROUP_DEBOUNCE", "0.02")

    for part in parts:
        await handlers["message"](None, part)
    await asyncio.sleep(0.15)

    # photo+video may share an album, so all three go in one call...
    assert calls["album"] == [("photo", "f1"), ("photo", "f2"), ("video", "f3")]
    assert calls["caption"] == "<b>Album caption.</b>"
    # ...and the caption was translated exactly once, not once per part.
    assert len(translations) == 1
    assert "texts" not in calls


@pytest.mark.asyncio
async def test_unalbumable_group_falls_back_to_separate_posts(monkeypatch):
    """A group Telegram won't accept as one album (here: a voice note, which is
    never albumable) must still relay every part rather than drop them."""
    sent = []

    class _Sender(_MediaStubs):
        async def send_media_group(self, album, caption, recorder):
            raise AssertionError("must not attempt an album for unsupported types")

        async def send_photo_message(self, photo, caption, recorder):
            sent.append(("photo", photo))
            return True

        async def send_voice_message(self, voice, caption, recorder):
            sent.append(("voice", voice))
            return True

        async def send_message(self, text, recorder, reply_to_message_id=None):
            sent.append(("text", text))
            return True

    parts = []
    for i in (1, 2):
        m = _FakeMsg(i, _FakeChat(1, "Channel One", "chan1"))
        m.media_group_id = "album-2"
        parts.append(m)

    media_by_id = {1: ("f1", 10, "photo"), 2: ("f2", 10, "voice")}
    handlers = _wire(
        monkeypatch,
        _Sender(),
        meta={"file": {}, "file_download_link": "http://img/x.jpg"},
        translated="<b>Short.</b>",
    )
    monkeypatch.setattr(bot, "get_media_info", lambda msg, max_size: media_by_id[msg.id])
    monkeypatch.setenv("MEDIA_GROUP_DEBOUNCE", "0.02")

    for part in parts:
        await handlers["message"](None, part)
    await asyncio.sleep(0.15)

    assert ("photo", "f1") in sent
    assert ("voice", "f2") in sent
