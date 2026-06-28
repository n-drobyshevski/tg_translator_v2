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
