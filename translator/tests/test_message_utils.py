from types import SimpleNamespace
import pytest
from translator.utils.message_utils import (
    get_media_info,
    build_payload,
)


class DummyMsg(SimpleNamespace):
    pass


def test_get_media_info_none():
    msg = DummyMsg(document=None, photo=None, video=None)
    assert get_media_info(msg, 1) == (None, None, "text")


def test_get_media_info_large_file():
    doc = SimpleNamespace(file_id="id", file_size=5000)
    msg = DummyMsg(document=doc, photo=None, video=None)
    # Too large: should fall back to text
    assert get_media_info(msg, 1) == (None, None, "text")


def test_get_media_info_large_file_logs_warning(caplog):
    # Oversized media must be skipped *and* logged, not silently dropped.
    doc = SimpleNamespace(file_id="id", file_size=5000)
    msg = DummyMsg(
        document=doc, photo=None, video=None,
        chat=SimpleNamespace(id=42), id=7,
    )
    with caplog.at_level("WARNING"):
        result = get_media_info(msg, 1)
    assert result == (None, None, "text")
    assert any("Skipping doc" in r.getMessage() for r in caplog.records)


def _media(file_id="id", size=10):
    return SimpleNamespace(file_id=file_id, file_size=size)


@pytest.mark.parametrize(
    "attr,expected",
    [
        ("animation", "animation"),
        ("voice", "voice"),
        ("video_note", "video_note"),
        ("audio", "audio"),
        ("document", "doc"),
        ("photo", "photo"),
        ("video", "video"),
    ],
)
def test_get_media_info_recognises_every_relayable_kind(attr, expected):
    # Animations, audio, voice and video notes used to fall through to "text",
    # which silently dropped the media from the mirrored post.
    msg = DummyMsg(**{attr: _media()})
    assert get_media_info(msg, 1000) == ("id", 10, expected)


def test_get_media_info_prefers_animation_over_document_and_video():
    # Pyrogram sets .document (and sometimes .video) alongside .animation for
    # GIFs. Probing document first would relay the GIF via sendDocument, losing
    # autoplay — so animation has to win.
    msg = DummyMsg(
        animation=_media("gif-id"),
        document=_media("doc-id"),
        video=_media("vid-id"),
    )
    assert get_media_info(msg, 1000)[0] == "gif-id"
    assert get_media_info(msg, 1000)[2] == "animation"


def test_get_media_info_prefers_voice_over_audio():
    msg = DummyMsg(voice=_media("voice-id"), audio=_media("audio-id"))
    assert get_media_info(msg, 1000)[2] == "voice"


def test_get_media_info_prefers_video_note_over_video():
    msg = DummyMsg(video_note=_media("note-id"), video=_media("vid-id"))
    assert get_media_info(msg, 1000)[2] == "video_note"


def test_build_payload_no_username():
    chat = SimpleNamespace(title="T", username=None)
    msg = DummyMsg(chat=chat, id=11, text=None, caption="c")
    res = build_payload(msg, "html", {})
    assert "Source channel: T" in res["Html"]


def test_get_media_info_text_only():
    m = DummyMsg(document=None, photo=None, video=None)
    assert get_media_info(m, 10_000) == (None, None, "text")


def test_build_payload_includes_channel_link():
    m = DummyMsg(
        chat=SimpleNamespace(title="T", username="U"), id=1, text="Hi", caption=None
    )
    res = build_payload(m, "<b>Test</b>", {})
    assert "Source channel:" in res["Html"]
