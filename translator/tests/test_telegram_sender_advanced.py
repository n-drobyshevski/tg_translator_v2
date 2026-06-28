import pytest
from unittest.mock import patch, MagicMock, PropertyMock
from translator.services.telegram_sender import TelegramSender
from translator.models import ChannelConfig
from translator.services.event_logger import EventRecorder

# Test configurations
TEST_CHANNEL_ID = 123
TEST_BOT_TOKEN = "test_token"

# Test channel configs
TEST_CONFIGS = {
    "test": ChannelConfig(channel_id=TEST_CHANNEL_ID, bot_token=TEST_BOT_TOKEN),
}

def create_mock_message(msg_type="text", file_size=1024):
    """Helper to create mock messages with different types"""
    mock_msg = MagicMock()
    mock_msg.chat.id = TEST_CHANNEL_ID
    mock_msg.id = 456
    mock_msg.message_id = 456
    mock_msg.date = "2025-07-05"
    
    # Clear all media attributes
    for attr in ["photo", "video", "document"]:
        setattr(mock_msg, attr, None)
        
    # Set specific media type if requested
    if msg_type != "text":
        media = MagicMock()
        media.file_size = file_size
        setattr(mock_msg, msg_type, media)
    
    return mock_msg

def test_extract_meta_fields_text():
    """Test metadata extraction from text message"""
    sender = TelegramSender()
    mock_msg = create_mock_message("text")
    meta = {"source_msg": mock_msg}
    
    media_type, size, src_channel, msg_id = sender._extract_meta_fields(meta, "test")
    
    assert media_type == "text"
    assert size is None
    assert src_channel == str(TEST_CHANNEL_ID)
    assert msg_id == 456

def test_extract_meta_fields_photo():
    """Test metadata extraction from photo message"""
    sender = TelegramSender()
    mock_msg = create_mock_message("photo", 2048)
    meta = {"source_msg": mock_msg}
    
    media_type, size, src_channel, msg_id = sender._extract_meta_fields(meta, "test")
    
    assert media_type == "photo"
    assert size == 2048
    assert src_channel == str(TEST_CHANNEL_ID)
    assert msg_id == 456

def test_extract_meta_fields_video():
    """Test metadata extraction from video message"""
    sender = TelegramSender()
    mock_msg = create_mock_message("video", 4096)
    meta = {"source_msg": mock_msg}
    
    media_type, size, src_channel, msg_id = sender._extract_meta_fields(meta, "test")
    
    assert media_type == "video"
    assert size == 4096
    assert src_channel == str(TEST_CHANNEL_ID)
    assert msg_id == 456

def test_extract_meta_fields_document():
    """Test metadata extraction from document message"""
    sender = TelegramSender()
    mock_msg = create_mock_message("document", 8192)
    meta = {"source_msg": mock_msg}
    
    media_type, size, src_channel, msg_id = sender._extract_meta_fields(meta, "test")
    
    assert media_type == "doc"
    assert size == 8192
    assert src_channel == str(TEST_CHANNEL_ID)
    assert msg_id == 456

def test_extract_meta_fields_no_source_msg():
    """Test metadata extraction with no source message"""
    sender = TelegramSender()
    meta = {"source_channel_id": "789"}
    
    media_type, size, src_channel, msg_id = sender._extract_meta_fields(meta, "test")
    
    assert media_type == "text"
    assert size is None
    assert src_channel == "789"
    assert msg_id is None

def test_extract_meta_fields_none():
    """Test metadata extraction with None meta"""
    sender = TelegramSender()
    
    media_type, size, src_channel, msg_id = sender._extract_meta_fields(None, "test")
    
    assert media_type == "text"
    assert size is None
    assert src_channel is None
    assert msg_id is None

def test_store_message():
    """Test message storage functionality"""
    sender = TelegramSender()
    mock_msg = create_mock_message("text")
    meta = {"mapping": {"dest-123": "test_channel"}}
    
    sender._store_message(
        TEST_CHANNEL_ID,
        456,
        mock_msg,
        "test_channel",
        "<b>Test</b>",
        meta
    )
    # Currently storage is disabled, so we just verify it doesn't crash
    # Add more assertions if storage is implemented

@pytest.mark.asyncio
async def test_send_photo_message_success():
    """Test successful photo message sending"""
    sender = TelegramSender()
    recorder = EventRecorder()
    recorder.set(
        dest_channel_name="test",
        dest_channel_id=TEST_CHANNEL_ID
    )
    
    with patch("translator.services.telegram_sender.CHANNEL_CONFIGS", TEST_CONFIGS), \
         patch("requests.Session.post") as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "ok": True,
            "result": {"message_id": 789}
        }
        
        success = await sender.send_photo_message(
            "photo123.jpg",
            "Test caption",
            recorder
        )
        
        assert success is True
        mock_post.assert_called_once()
        args = mock_post.call_args[1]
        assert args["data"]["photo"] == "photo123.jpg"
        assert args["data"]["caption"] == "Test caption"

@pytest.mark.asyncio
async def test_send_photo_message_api_error():
    """Test photo message sending with API error"""
    sender = TelegramSender()
    recorder = EventRecorder()
    recorder.set(
        dest_channel_name="test",
        dest_channel_id=TEST_CHANNEL_ID
    )
    
    with patch("translator.services.telegram_sender.CHANNEL_CONFIGS", TEST_CONFIGS), \
         patch("requests.Session.post") as mock_post:
        mock_post.return_value.status_code = 400
        mock_post.return_value.json.return_value = {
            "ok": False,
            "description": "Bad photo"
        }
        mock_post.return_value.text = "Bad photo"
        
        success = await sender.send_photo_message(
            "invalid.jpg",
            "Test caption",
            recorder
        )
        
        assert success is False
        mock_post.assert_called_once()
        args = mock_post.call_args[1]
        assert args["data"]["photo"] == "invalid.jpg"
        assert args["data"]["caption"] == "Test caption"

@pytest.mark.asyncio
async def test_edit_message_success():
    """Test successful message editing"""
    sender = TelegramSender()
    recorder = EventRecorder()
    recorder.set(
        dest_channel_name="test",
        dest_channel_id=TEST_CHANNEL_ID
    )
    
    with patch("translator.services.telegram_sender.CHANNEL_CONFIGS", TEST_CONFIGS), \
         patch("requests.Session.post") as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "ok": True,
            "result": {"message_id": 123}
        }
        
        success = await sender.edit_message(
            TEST_CHANNEL_ID,
            123,
            "New text",
            recorder
        )
        
        assert success is True
        mock_post.assert_called_once()

@pytest.mark.asyncio
async def test_edit_message_no_changes():
    """Test editing message with identical content"""
    sender = TelegramSender()
    recorder = EventRecorder()
    recorder.set(
        dest_channel_name="test",
        dest_channel_id=TEST_CHANNEL_ID
    )
    
    with patch("translator.services.telegram_sender.CHANNEL_CONFIGS", TEST_CONFIGS):
        original_text = "Test <b>message</b>"
        new_text = "Test <b>message</b>"
        
        success = await sender.edit_message(
            TEST_CHANNEL_ID,
            123,
            new_text,
            recorder,
            original_text
        )
        
        # Should return True since content is identical (no need to edit)
        assert success is True
