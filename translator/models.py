from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any
import asyncio

@dataclass
class ChannelConfig:
    """Configuration for a Telegram channel."""
    channel_id: int
    bot_token: str

@dataclass
class MetadataRequest:
    """Metadata fetch request for relay worker."""
    chat_id: int
    message_id: int
    file_id: Optional[str] = None
    message_entities: Optional[List[Dict[str, Any]]] = None
    response: asyncio.Future = field(
        default_factory=lambda: asyncio.get_event_loop().create_future()
    )

@dataclass
class MessageEvent:
    """Statistics log entry for a message event."""
    timestamp: str
    event_type: str
    source_channel_id: str
    dest_channel_id: str
    source_channel_name: str = ""
    dest_channel_name: str = ""
    message_id: str = ""
    media_type: str = ""
    file_size_bytes: int = 0
    original_size: int = 0
    translated_size: int = 0
    translation_time: float = 0.0
    retry_count: int = 0
    posting_success: bool = False
    api_error_code: int = 0
    exception_message: str = ""
    # Optional fields for edits, etc.
    edit_timestamp: str = ""
    previous_size: int = 0
    new_size: int = 0
    source_message: str = ""
    translated_message: str = ""
    dest_message_id: str = ""
    file_path: str = ""  

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict, keeping all fields (even if empty or zero)."""
        return asdict(self)
