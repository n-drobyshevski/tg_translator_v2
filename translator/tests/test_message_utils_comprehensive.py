from types import SimpleNamespace
import pytest
from translator.utils.message_utils import (
    get_media_info,
    build_payload,
    extract_channel_info
)

class DummyFile:
    def __init__(self, file_id: str, file_size: int):
        self.file_id = file_id
        self.file_size = file_size

class DummyChat:
    def __init__(self, title: str, username: str | None = None, chat_id: int | None = None):
        self.title = title
        self.username = username
        self.id = chat_id

class DummyMessage:
    def __init__(self, **kwargs):
        self.document = kwargs.get('document')
        self.photo = kwargs.get('photo')
        self.video = kwargs.get('video')
        self.chat = kwargs.get('chat')
        self.text = kwargs.get('text')
        self.caption = kwargs.get('caption')
        self.id = kwargs.get('id', 1)

# Test get_media_info with different media types and sizes
@pytest.mark.parametrize("media_type,size,max_size,expected", [
    ("document", 1000, 2000, ("document_id", 1000, "doc")),
    ("document", 2000, 1000, (None, None, "text")),  # Too large
    ("photo", 500, 1000, ("photo_id", 500, "photo")),
    ("video", 800, 1000, ("video_id", 800, "video")),
    (None, 0, 1000, (None, None, "text")),  # No media
])
def test_get_media_info_types(media_type, size, max_size, expected):
    """Test media info extraction for different types and sizes"""
    kwargs = {}
    if media_type:
        file = DummyFile(f"{media_type}_id", size)
        kwargs[media_type] = file
    
    msg = DummyMessage(**kwargs)
    assert get_media_info(msg, max_size) == expected

def test_get_media_info_photo_no_file_size():
    """Test photo handling when file_size attribute is missing"""
    photo = SimpleNamespace(file_id="photo_id")  # No file_size attribute
    msg = DummyMessage(photo=photo)
    file_id, size, type = get_media_info(msg, 1000)
    assert type == "photo"
    assert file_id == "photo_id"
    assert size is None

# Test build_payload with different message types
@pytest.mark.parametrize("msg_type,content,expected_text", [
    ("text", "Hello", "Hello"),
    ("caption", "Photo caption", "Photo caption"),
    ("both", ("Text", "Caption"), "Text"),  # Text takes precedence
    ("neither", None, ""),
])
def test_build_payload_content_types(msg_type, content, expected_text):
    """Test payload building with different content types"""
    kwargs = {
        "chat": DummyChat("Channel", "username"),
        "id": 123
    }
    
    if msg_type == "text":
        kwargs["text"] = content
    elif msg_type == "caption":
        kwargs["caption"] = content
    elif msg_type == "both":
        kwargs["text"] = content[0]
        kwargs["caption"] = content[1]
    
    msg = DummyMessage(**kwargs)
    payload = build_payload(msg, "<p>HTML content</p>", {})
    
    assert payload["Text"] == expected_text
    assert "HTML content" in payload["Html"]
    assert payload["Channel"] == "Channel"
    assert f"https://t.me/username/123" == payload["Link"]

def test_build_payload_private_chat():
    """Test payload building for private chat without username"""
    msg = DummyMessage(
        chat=DummyChat("Private Chat"),  # No username
        text="Secret message",
        id=456
    )
    payload = build_payload(msg, "<p>Private message</p>", {})
    assert "Private Chat" in payload["Html"]  # Should use title directly
    assert payload["Link"] == "https://t.me/None/456"  # Link with no username

def test_build_payload_with_meta():
    """Test payload building with metadata"""
    meta = {"key": "value", "nested": {"data": "test"}}
    msg = DummyMessage(
        chat=DummyChat("Channel", "username"),
        text="Message with meta",
        id=789
    )
    payload = build_payload(msg, "<p>Content</p>", meta)
    assert payload["Meta"] == meta

# Test extract_channel_info with different scenarios
def test_extract_channel_info_found():
    """Test channel info extraction with matching mapping"""
    msg = DummyMessage(
        chat=DummyChat("Source Channel", chat_id=100)
    )
    mapping = {200: "Target Channel"}
    src_id, src_name, dst_id, dst_name = extract_channel_info(
        msg, mapping, "Target Channel"
    )
    assert src_id == "100"
    assert src_name == "Source Channel"
    assert dst_id == "200"
    assert dst_name == "Target Channel"

def test_extract_channel_info_not_found():
    """Test channel info extraction with no matching mapping"""
    msg = DummyMessage(
        chat=DummyChat("Source", chat_id=100)
    )
    mapping = {200: "Other Channel"}
    src_id, src_name, dst_id, dst_name = extract_channel_info(
        msg, mapping, "Target"
    )
    assert src_id == "100"
    assert src_name == "Source"
    assert dst_id == ""  # No matching destination found
    assert dst_name == "Target"

def test_extract_channel_info_no_title():
    """Test channel info extraction when chat title is missing"""
    msg = DummyMessage(
        chat=SimpleNamespace(id=100)  # No title attribute
    )
    mapping = {200: "Target"}
    src_id, src_name, dst_id, dst_name = extract_channel_info(
        msg, mapping, "Target"
    )
    assert src_id == "100"
    assert src_name is None
    assert dst_name == "Target"
