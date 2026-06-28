import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from translator.services.telegram_sender import TelegramSender, sanitize_html, normalize_for_comparison
from translator.models import ChannelConfig
from translator.services.event_logger import EventRecorder

# Test edge cases for sanitize_html
def test_sanitize_html_empty():
    assert sanitize_html("") == ""

def test_sanitize_html_complex():
    html = "<p>First paragraph</p><br>Line break<p>Second <b>bold</b> paragraph</p><br/>Another break<br />Final break"
    expected = "First paragraph\nLine break\nSecond <b>bold</b> paragraph\nAnother break\nFinal break"
    result = sanitize_html(html)
    # Print debug info if test fails
    if result != expected:
        print("Expected:")
        print(repr(expected))
        print("Got:")
        print(repr(result))
    assert result == expected

def test_normalize_comparison_empty():
    assert normalize_for_comparison("") == ""

def test_normalize_comparison_whitespace():
    text = "  Multiple    spaces   and\nlines\n\n"
    assert normalize_for_comparison(text) == "Multiple spaces and lines"

def test_normalize_comparison_html():
    html = "<p>Text with <b>bold</b> and <i>italic</i></p>"
    assert normalize_for_comparison(html) == "Text with bold and italic"

@pytest.mark.asyncio
async def test_edit_message_network_error():
    """Test edit_message handling of network errors"""
    sender = TelegramSender()
    recorder = EventRecorder()
    recorder.set(
        dest_channel_name="test",
        dest_channel_id=123
    )
    
    with patch("translator.services.telegram_sender.CHANNEL_CONFIGS", {
        "test": ChannelConfig(channel_id=123, bot_token="test_token")
    }), patch("requests.Session.post") as mock_post:
        mock_post.side_effect = Exception("Network timeout")
        
        success = await sender.edit_message(
            123,
            456,
            "New text",
            recorder
        )
        
        assert not success
        error_msg = recorder.get("exception_message")
        assert isinstance(error_msg, str)
        assert "Network timeout" in error_msg

@pytest.mark.asyncio
async def test_edit_message_rate_limit():
    """Test edit_message handling of rate limiting"""
    sender = TelegramSender()
    recorder = EventRecorder()
    recorder.set(
        dest_channel_name="test",
        dest_channel_id=123
    )
    
    with patch("translator.services.telegram_sender.CHANNEL_CONFIGS", {
        "test": ChannelConfig(channel_id=123, bot_token="test_token")
    }), patch("requests.Session.post") as mock_post:
        mock_post.return_value.status_code = 429
        mock_post.return_value.json.return_value = {
            "ok": False,
            "description": "Too Many Requests: retry after 30"
        }
        
        success = await sender.edit_message(
            123,
            456,
            "New text",
            recorder
        )
        
        assert not success
        error_msg = recorder.get("exception_message")
        assert "Too Many Requests" in error_msg

@pytest.mark.asyncio
async def test_send_photo_large_file():
    """Test sending large photo files"""
    sender = TelegramSender()
    recorder = EventRecorder()
    recorder.set(
        dest_channel_name="test",
        dest_channel_id=123
    )
    
    with patch("translator.services.telegram_sender.CHANNEL_CONFIGS", {
        "test": ChannelConfig(channel_id=123, bot_token="test_token")
    }), patch("requests.Session.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            "ok": False,
            "description": "File too large"
        }
        mock_post.return_value = mock_response
        
        success = await sender.send_photo_message(
            "huge_photo.jpg",
            "Test caption",
            recorder
        )
        
        assert not success
        # Get the error message from the recorder
        _, _, err = recorder.get("posting_success", "api_error_code", "exception_message")
        assert "File too large" in str(err)

@pytest.mark.asyncio
async def test_send_photo_invalid_format():
    """Test sending photos with invalid format"""
    sender = TelegramSender()
    recorder = EventRecorder()
    recorder.set(
        dest_channel_name="test",
        dest_channel_id=123
    )
    
    with patch("translator.services.telegram_sender.CHANNEL_CONFIGS", {
        "test": ChannelConfig(channel_id=123, bot_token="test_token")
    }), patch("requests.Session.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            "ok": False,
            "description": "Invalid file format"
        }
        mock_post.return_value = mock_response
        
        success = await sender.send_photo_message(
            "invalid.txt",
            "Test caption",
            recorder
        )
        
        assert not success
        _, _, err = recorder.get("posting_success", "api_error_code", "exception_message")
        assert "Invalid file format" in str(err)

@pytest.mark.asyncio
async def test_edit_message_concurrent():
    """Test concurrent edits to the same message"""
    sender = TelegramSender()
    recorder = EventRecorder()
    recorder.set(
        dest_channel_name="test",
        dest_channel_id=123
    )
    
    with patch("translator.services.telegram_sender.CHANNEL_CONFIGS", {
        "test": ChannelConfig(channel_id=123, bot_token="test_token")
    }), patch("requests.Session.post") as mock_post:
        # First edit succeeds
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "ok": True,
            "result": {"message_id": 123}
        }
        
        success1 = await sender.edit_message(
            123,
            456,
            "First edit",
            recorder
        )
        
        # Second concurrent edit fails
        mock_post.return_value.status_code = 400
        mock_post.return_value.json.return_value = {
            "ok": False,
            "description": "Message can't be edited"
        }
        
        success2 = await sender.edit_message(
            123,
            456,
            "Second edit",
            recorder
        )
        
        assert success1
        assert not success2
        _, _, err = recorder.get("posting_success", "api_error_code", "exception_message")
        assert "can't be edited" in str(err)
