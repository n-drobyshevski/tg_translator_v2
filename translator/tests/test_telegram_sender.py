import pytest
from unittest.mock import patch, MagicMock
from translator.services.telegram_sender import TelegramSender
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
@patch("requests.Session.post")
async def test_send_message_unknown_channel(mock_post):
    sender = TelegramSender()
    recorder = EventRecorder()
    recorder.set(dest_channel_name="notachannel")
    success = await sender.send_message("text", recorder)
    assert not success


@pytest.mark.asyncio
@patch(
    "translator.config.CHANNEL_CONFIGS",
    {"test": ChannelConfig(channel_id=0, bot_token=TEST_BOT_TOKEN)},
)
@patch("requests.Session.post")
async def test_send_message_no_channel_id(mock_post):
    sender = TelegramSender()
    recorder = EventRecorder()
    recorder.set(dest_channel_name="test")
    success = await sender.send_message("text", recorder)
    assert not success


@pytest.mark.asyncio
@patch(
    "translator.config.CHANNEL_CONFIGS",
    {"test": ChannelConfig(channel_id=TEST_CHANNEL_ID, bot_token=TEST_BOT_TOKEN)},
)
@patch("requests.Session.post")
async def test_send_message_api_error(mock_post):
    mock_post.return_value.status_code = 400
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
@patch("requests.Session.post")
async def test_send_message_success(mock_post):
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {"ok": True, "result": {"message_id": 123}}
    sender = TelegramSender()
    recorder = EventRecorder()
    recorder.set(dest_channel_name="test", dest_channel_id=TEST_CHANNEL_ID)
    success = await sender.send_message("text", recorder)
    assert success
