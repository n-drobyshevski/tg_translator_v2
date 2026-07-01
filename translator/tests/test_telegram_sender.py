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
    monkeypatch.delenv("LINK_PREVIEW_SHOW_ABOVE_TEXT", raising=False)
    monkeypatch.delenv("LINK_PREVIEW_URL", raising=False)
    opts = build_link_preview_options()
    assert opts == {"prefer_large_media": True, "show_above_text": False}


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
