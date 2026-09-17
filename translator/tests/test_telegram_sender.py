import json
import logging

import pytest
from unittest.mock import patch, MagicMock
from translator.services import telegram_sender as ts_module
from translator.services.telegram_sender import (
    TelegramSender,
    build_link_preview_options,
)
from translator.models import ChannelConfig
from translator.services.event_logger import EventRecorder

# Test configurations
TEST_CHANNEL_ID = 123
TEST_BOT_TOKEN = "test_token"


def test_split_message_short():
    sender = TelegramSender()
    text = "short text"
    assert sender.split_message(text) == [text]


def test_split_message_long():
    sender = TelegramSender()
    long_line = "A" * (sender.MAX_MESSAGE_LENGTH + 5)
    messages = sender.split_message(long_line)
    assert len(messages) == 2
    assert "".join(messages).replace("\n", "") == long_line


@pytest.mark.asyncio
@patch("translator.config.CHANNEL_CONFIGS", {})
@patch("httpx.AsyncClient.post")
async def test_send_message_empty_dest_raises(mock_post):
    # An unresolved destination (no dest_channel_id on the recorder) must raise
    # a non-retryable ValueError *before* any POST, instead of silently sending
    # to an empty chat_id. This is the guard that prevents the shared-recorder
    # concurrency bug from reaching the Telegram API.
    sender = TelegramSender()
    recorder = EventRecorder()
    recorder.set(dest_channel_name="notachannel")
    with pytest.raises(ValueError):
        await sender.send_message("text", recorder)
    mock_post.assert_not_called()


@pytest.mark.asyncio
@patch(
    "translator.config.CHANNEL_CONFIGS",
    {"test": ChannelConfig(channel_id=0, bot_token=TEST_BOT_TOKEN)},
)
@patch("httpx.AsyncClient.post")
async def test_send_message_no_channel_id(mock_post):
    # dest_channel_name set but no dest_channel_id → same guard fires.
    sender = TelegramSender()
    recorder = EventRecorder()
    recorder.set(dest_channel_name="test")
    with pytest.raises(ValueError):
        await sender.send_message("text", recorder)
    mock_post.assert_not_called()


@pytest.mark.asyncio
@patch(
    "translator.config.CHANNEL_CONFIGS",
    {"test": ChannelConfig(channel_id=TEST_CHANNEL_ID, bot_token=TEST_BOT_TOKEN)},
)
@patch("httpx.AsyncClient.post")
async def test_send_media_empty_dest_raises(mock_post):
    # Media path has the same guard: an empty dest_channel_id must raise before
    # the POST rather than send media to an empty chat_id.
    sender = TelegramSender()
    recorder = EventRecorder()
    recorder.set(dest_channel_name="test")  # no dest_channel_id
    with pytest.raises(ValueError):
        await sender.send_photo_message("file_id", "caption", recorder)
    mock_post.assert_not_called()


@pytest.mark.asyncio
@patch(
    "translator.config.CHANNEL_CONFIGS",
    {"test": ChannelConfig(channel_id=TEST_CHANNEL_ID, bot_token=TEST_BOT_TOKEN)},
)
@patch("httpx.AsyncClient.post")
async def test_send_message_api_error(mock_post):
    mock_post.return_value = MagicMock(status_code=400)
    mock_post.return_value.json.return_value = {"description": "fail"}
    sender = TelegramSender()
    recorder = EventRecorder()
    recorder.set(dest_channel_name="test", dest_channel_id=TEST_CHANNEL_ID)
    success = await sender.send_message("text", recorder)
    assert not success


@pytest.mark.asyncio
@patch(
    "translator.config.CHANNEL_CONFIGS",
    {"test": ChannelConfig(channel_id=TEST_CHANNEL_ID, bot_token=TEST_BOT_TOKEN)},
)
@patch("httpx.AsyncClient.post")
async def test_send_message_success(mock_post):
    mock_post.return_value = MagicMock(status_code=200)
    mock_post.return_value.json.return_value = {"ok": True, "result": {"message_id": 123}}
    sender = TelegramSender()
    recorder = EventRecorder()
    recorder.set(dest_channel_name="test", dest_channel_id=TEST_CHANNEL_ID)
    success = await sender.send_message("text", recorder)
    assert success


@pytest.mark.asyncio
@patch(
    "translator.config.CHANNEL_CONFIGS",
    {"test": ChannelConfig(channel_id=TEST_CHANNEL_ID, bot_token=TEST_BOT_TOKEN)},
)
@patch("httpx.AsyncClient.post")
async def test_send_message_failure_marks_no_forward(mock_post, caplog):
    # A send failure is recorded on the event and shown under /status, so its
    # ERROR logs must carry extra={"no_forward": True} to skip the DM forwarder.
    mock_post.return_value = MagicMock(status_code=400)
    mock_post.return_value.json.return_value = {"description": "fail"}
    sender = TelegramSender()
    recorder = EventRecorder()
    recorder.set(dest_channel_name="test", dest_channel_id=TEST_CHANNEL_ID)
    with caplog.at_level(logging.ERROR):
        await sender.send_message("text", recorder)
    fail_records = [r for r in caplog.records if "Send message:" in r.getMessage()]
    assert fail_records  # the failure was logged
    assert all(getattr(r, "no_forward", False) is True for r in fail_records)


# --- Link preview ("message filling") options -------------------------------


def test_link_preview_enabled_by_default(monkeypatch):
    monkeypatch.setattr(ts_module, "DISABLE_LINK_PREVIEW", False)
    monkeypatch.delenv("LINK_PREVIEW_PREFER_LARGE_MEDIA", raising=False)
    monkeypatch.delenv("LINK_PREVIEW_PREFER_SMALL_MEDIA", raising=False)
    monkeypatch.delenv("LINK_PREVIEW_SHOW_ABOVE_TEXT", raising=False)
    monkeypatch.delenv("LINK_PREVIEW_URL", raising=False)
    opts = build_link_preview_options()
    assert opts == {
        "prefer_large_media": True,
        "prefer_small_media": False,
        "show_above_text": False,
    }


def test_link_preview_disabled_override(monkeypatch):
    monkeypatch.setattr(ts_module, "DISABLE_LINK_PREVIEW", True)
    assert build_link_preview_options() == {"is_disabled": True}


def test_link_preview_pinned_url(monkeypatch):
    monkeypatch.setattr(ts_module, "DISABLE_LINK_PREVIEW", False)
    monkeypatch.setenv("LINK_PREVIEW_URL", "https://t.me/example")
    assert build_link_preview_options()["url"] == "https://t.me/example"


@pytest.mark.asyncio
@patch(
    "translator.config.CHANNEL_CONFIGS",
    {"test": ChannelConfig(channel_id=TEST_CHANNEL_ID, bot_token=TEST_BOT_TOKEN)},
)
@patch("httpx.AsyncClient.post")
async def test_send_message_includes_link_preview_options(mock_post, monkeypatch):
    monkeypatch.setattr(ts_module, "DISABLE_LINK_PREVIEW", False)
    mock_post.return_value = MagicMock(status_code=200)
    mock_post.return_value.json.return_value = {"ok": True, "result": {"message_id": 1}}
    sender = TelegramSender()
    recorder = EventRecorder()
    recorder.set(dest_channel_name="test", dest_channel_id=TEST_CHANNEL_ID)
    await sender.send_message("text", recorder)
    body = mock_post.call_args.kwargs["json"]
    assert "link_preview_options" in body
    assert body["link_preview_options"]["prefer_large_media"] is True


# --- Modern send options (reply_parameters / protect_content / …) ------------


def test_build_reply_parameters_none_without_target():
    assert ts_module.build_reply_parameters(None) is None
    assert ts_module.build_reply_parameters(0) is None


def test_build_reply_parameters_allows_sending_without_reply():
    # allow_sending_without_reply must stay on: a long-caption post is relayed as
    # media + reply, and if the media vanishes in between, the remainder should
    # still post rather than be rejected outright.
    assert ts_module.build_reply_parameters(42) == {
        "message_id": 42,
        "allow_sending_without_reply": True,
    }


def test_build_send_options_defaults_to_nothing(monkeypatch):
    for var in ("PROTECT_CONTENT", "DISABLE_NOTIFICATION", "SHOW_CAPTION_ABOVE_MEDIA"):
        monkeypatch.delenv(var, raising=False)
    assert ts_module.build_send_options() == {}
    assert ts_module.build_send_options(with_caption=True) == {}


def test_build_send_options_reads_env(monkeypatch):
    monkeypatch.setenv("PROTECT_CONTENT", "1")
    monkeypatch.setenv("DISABLE_NOTIFICATION", "1")
    monkeypatch.setenv("SHOW_CAPTION_ABOVE_MEDIA", "1")
    # show_caption_above_media only applies to captioned media.
    assert ts_module.build_send_options() == {
        "protect_content": True,
        "disable_notification": True,
    }
    assert ts_module.build_send_options(with_caption=True)["show_caption_above_media"] is True


def test_as_form_value_encodes_booleans_as_json_literals():
    # httpx would form-encode Python's True as "True", which is not a value
    # Telegram documents for Boolean fields.
    assert ts_module._as_form_value(True) == "true"
    assert ts_module._as_form_value(False) == "false"
    assert ts_module._as_form_value({"a": 1}) == '{"a": 1}'
    assert ts_module._as_form_value("text") == "text"


@pytest.mark.asyncio
@patch(
    "translator.config.CHANNEL_CONFIGS",
    {"test": ChannelConfig(channel_id=TEST_CHANNEL_ID, bot_token=TEST_BOT_TOKEN)},
)
@patch("httpx.AsyncClient.post")
async def test_send_message_uses_reply_parameters_not_legacy_field(mock_post, monkeypatch):
    monkeypatch.setattr(ts_module, "DISABLE_LINK_PREVIEW", False)
    mock_post.return_value = MagicMock(status_code=200)
    mock_post.return_value.json.return_value = {"ok": True, "result": {"message_id": 1}}
    sender = TelegramSender()
    recorder = EventRecorder()
    recorder.set(dest_channel_name="test", dest_channel_id=TEST_CHANNEL_ID)
    await sender.send_message("text", recorder, reply_to_message_id=77)
    body = mock_post.call_args.kwargs["json"]
    # JSON body -> reply_parameters nests directly, no JSON-encoding.
    assert body["reply_parameters"] == {
        "message_id": 77,
        "allow_sending_without_reply": True,
    }
    assert "reply_to_message_id" not in body


@pytest.mark.asyncio
# The media path resolves the channel through telegram_sender's own module-level
# CHANNEL_CONFIGS binding (`from translator.config import CHANNEL_CONFIGS`), so
# patching translator.config's name would not be seen here.
@patch.dict(
    ts_module.CHANNEL_CONFIGS,
    {"test": ChannelConfig(channel_id=TEST_CHANNEL_ID, bot_token=TEST_BOT_TOKEN)},
)
@patch("httpx.AsyncClient.post")
async def test_media_send_options_are_form_encoded(mock_post, monkeypatch):
    monkeypatch.setenv("PROTECT_CONTENT", "1")
    monkeypatch.setenv("SHOW_CAPTION_ABOVE_MEDIA", "1")
    mock_post.return_value = MagicMock(status_code=200)
    mock_post.return_value.json.return_value = {"ok": True, "result": {"message_id": 5}}
    sender = TelegramSender()
    recorder = EventRecorder()
    recorder.set(dest_channel_name="test", dest_channel_id=TEST_CHANNEL_ID)
    await sender.send_photo_message("file-id", "caption", recorder)
    data = mock_post.call_args.kwargs["data"]
    # Form-encoded body -> lowercase JSON literals, not Python's "True".
    assert data["protect_content"] == "true"
    assert data["show_caption_above_media"] == "true"


@pytest.mark.asyncio
@patch.dict(
    ts_module.CHANNEL_CONFIGS,
    {"test": ChannelConfig(channel_id=TEST_CHANNEL_ID, bot_token=TEST_BOT_TOKEN)},
)
@patch("httpx.AsyncClient.post")
async def test_video_note_send_drops_caption(mock_post, monkeypatch):
    # sendVideoNote accepts no caption at all; sending one is an API error.
    monkeypatch.setenv("SHOW_CAPTION_ABOVE_MEDIA", "1")
    mock_post.return_value = MagicMock(status_code=200)
    mock_post.return_value.json.return_value = {"ok": True, "result": {"message_id": 6}}
    sender = TelegramSender()
    recorder = EventRecorder()
    recorder.set(dest_channel_name="test", dest_channel_id=TEST_CHANNEL_ID)
    await sender.send_video_note_message("file-id", "some caption", recorder)
    data = mock_post.call_args.kwargs["data"]
    assert "caption" not in data
    # ...and the caption-only option must not ride along either.
    assert "show_caption_above_media" not in data


# --- Media relay (photo/video/document) -------------------------------------


@pytest.mark.asyncio
@patch(
    "translator.services.telegram_sender.CHANNEL_CONFIGS",
    {"test": ChannelConfig(channel_id=TEST_CHANNEL_ID, bot_token=TEST_BOT_TOKEN)},
)
@patch("httpx.AsyncClient.post")
async def test_send_video_message_success(mock_post):
    mock_post.return_value = MagicMock(status_code=200)
    mock_post.return_value.json.return_value = {"ok": True, "result": {"message_id": 9}}
    sender = TelegramSender()
    recorder = EventRecorder()
    recorder.set(dest_channel_name="test", dest_channel_id=TEST_CHANNEL_ID)
    success = await sender.send_video_message("file_id_1", "caption", recorder)
    assert success
    sent = mock_post.call_args
    assert sent.args[0].endswith("/sendVideo")
    assert sent.kwargs["data"]["video"] == "file_id_1"
    assert sent.kwargs["data"]["caption"] == "caption"
    assert sent.kwargs["data"]["parse_mode"] == "HTML"


@pytest.mark.asyncio
@patch(
    "translator.services.telegram_sender.CHANNEL_CONFIGS",
    {"test": ChannelConfig(channel_id=TEST_CHANNEL_ID, bot_token=TEST_BOT_TOKEN)},
)
@patch("httpx.AsyncClient.post")
async def test_send_document_message_success(mock_post):
    mock_post.return_value = MagicMock(status_code=200)
    mock_post.return_value.json.return_value = {"ok": True, "result": {"message_id": 10}}
    sender = TelegramSender()
    recorder = EventRecorder()
    recorder.set(dest_channel_name="test", dest_channel_id=TEST_CHANNEL_ID)
    success = await sender.send_document_message("file_id_2", "", recorder)
    assert success
    sent = mock_post.call_args
    assert sent.args[0].endswith("/sendDocument")
    assert sent.kwargs["data"]["document"] == "file_id_2"
    # Empty caption is omitted entirely.
    assert "caption" not in sent.kwargs["data"]


# --- Caption edits ----------------------------------------------------------


@pytest.mark.asyncio
@patch("httpx.AsyncClient.post")
async def test_edit_caption_success(mock_post):
    mock_post.return_value = MagicMock(status_code=200)
    mock_post.return_value.json.return_value = {"ok": True, "result": {"message_id": 5}}
    sender = TelegramSender()
    recorder = EventRecorder()
    success = await sender.edit_caption(TEST_CHANNEL_ID, 5, "new caption", recorder)
    assert success
    sent = mock_post.call_args
    assert sent.args[0].endswith("/editMessageCaption")
    assert sent.kwargs["data"]["caption"] == "new caption"
    assert sent.kwargs["data"]["parse_mode"] == "HTML"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.post")
async def test_edit_caption_unchanged_skips_api(mock_post):
    sender = TelegramSender()
    recorder = EventRecorder()
    success = await sender.edit_caption(
        TEST_CHANNEL_ID, 5, "same", recorder, original_text="same"
    )
    assert success
    mock_post.assert_not_called()


# --- sendMediaGroup (albums) -------------------------------------------------


@pytest.mark.asyncio
@patch.dict(
    ts_module.CHANNEL_CONFIGS,
    {"test": ChannelConfig(channel_id=TEST_CHANNEL_ID, bot_token=TEST_BOT_TOKEN)},
)
@patch("httpx.AsyncClient.post")
async def test_send_media_group_wire_format(mock_post, monkeypatch):
    monkeypatch.delenv("SHOW_CAPTION_ABOVE_MEDIA", raising=False)
    mock_post.return_value = MagicMock(status_code=200)
    # sendMediaGroup returns an ARRAY of messages, unlike every other send.
    mock_post.return_value.json.return_value = {
        "ok": True,
        "result": [{"message_id": 31}, {"message_id": 32}],
    }
    sender = TelegramSender()
    recorder = EventRecorder()
    recorder.set(dest_channel_name="test", dest_channel_id=TEST_CHANNEL_ID)

    ok = await sender.send_media_group(
        [("photo", "f1"), ("video", "f2")], "<b>Caption.</b>", recorder
    )
    assert ok is True

    data = mock_post.call_args.kwargs["data"]
    media = json.loads(data["media"])
    assert [m["type"] for m in media] == ["photo", "video"]
    assert [m["media"] for m in media] == ["f1", "f2"]
    # Telegram shows the album caption from the FIRST item only.
    assert media[0]["caption"] == "<b>Caption.</b>"
    assert media[0]["parse_mode"] == "HTML"
    assert "caption" not in media[1]
    # The first message id is recorded so the edit mapping keeps working.
    assert recorder.get("dest_message_id") == 31
    assert recorder.get("posting_success") is True


@pytest.mark.asyncio
@patch.dict(
    ts_module.CHANNEL_CONFIGS,
    {"test": ChannelConfig(channel_id=TEST_CHANNEL_ID, bot_token=TEST_BOT_TOKEN)},
)
@patch("httpx.AsyncClient.post")
async def test_send_media_group_records_api_failure(mock_post):
    mock_post.return_value = MagicMock(status_code=400)
    mock_post.return_value.json.return_value = {
        "ok": False,
        "description": "Bad Request: media must be an array",
    }
    sender = TelegramSender()
    recorder = EventRecorder()
    recorder.set(dest_channel_name="test", dest_channel_id=TEST_CHANNEL_ID)

    ok = await sender.send_media_group([("photo", "f1"), ("photo", "f2")], "c", recorder)
    assert ok is False
    assert recorder.get("posting_success") is False
    assert "media must be an array" in recorder.get("exception_message")


@pytest.mark.asyncio
@patch("httpx.AsyncClient.post")
async def test_send_media_group_empty_dest_raises(mock_post):
    # Same guard as the other send paths: never POST to an empty chat_id.
    sender = TelegramSender()
    recorder = EventRecorder()
    recorder.set(dest_channel_name="test")  # no dest_channel_id
    with pytest.raises(ValueError):
        await sender.send_media_group([("photo", "f1"), ("photo", "f2")], "c", recorder)
    mock_post.assert_not_called()
