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
    # Built only inside async handlers, so a running loop is guaranteed.
    # get_running_loop() replaces the deprecated get_event_loop() (which is
    # slated to stop implicitly creating a loop in newer CPython).
    response: asyncio.Future = field(
        default_factory=lambda: asyncio.get_running_loop().create_future()
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
    # Anthropic token usage for this translation (used for cost reporting).
    # model_used is the model that actually produced the text — recorded per
    # event because CONFIG.ANTHROPIC_MODEL can change over time, and cost must
    # be priced against the model in effect when the message was translated.
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    model_used: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict, keeping all fields (even if empty or zero)."""
        return asdict(self)
