import os
import json
import logging
from typing import Dict, Any, List, Optional

STORE_PATH = os.path.join(os.path.dirname(__file__), "..", "cache", "channel_cache.json")
CACHE_SIZE_LIMIT = 10  # Keep last N messages per channel

class MessageIdInvalid(Exception):
    """Raised when a message ID is no longer valid in Telegram."""
    pass

class ChannelCache:
    """Cache for storing channel messages."""
    def __init__(self) -> None:
        self.cache: Dict[str, List[Dict[str, Any]]] = self._load_cache()

    def _load_cache(self) -> Dict[str, List[Dict[str, Any]]]:
        """Load cache from disk."""
        try:
            with open(STORE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_cache(self) -> None:
        """Save cache to disk."""
        os.makedirs(os.path.dirname(STORE_PATH), exist_ok=True)
        with open(STORE_PATH, "w", encoding="utf-8") as f:
            json.dump(self.cache, f, ensure_ascii=False, indent=2)

    def store_message(self, channel_id: str, msg_data: Dict[str, Any]) -> None:
        """Store a message in the cache."""
        if channel_id not in self.cache:
            self.cache[channel_id] = []
        
        # Add new message
        self.cache[channel_id].append(msg_data)
        
        # Trim to limit if needed
        if len(self.cache[channel_id]) > CACHE_SIZE_LIMIT:
            self.cache[channel_id] = self.cache[channel_id][-CACHE_SIZE_LIMIT:]
        
        self._save_cache()

    def get_last_messages(self, channel_id: str) -> List[Dict[str, Any]]:
        """Get the last N messages for a channel."""
        return self.cache.get(channel_id, [])

    def check_deleted_messages(self, client: Any) -> None:
        """Check for and remove messages that no longer exist in Telegram."""
        for channel_id in list(self.cache.keys()):
            valid_msgs = []
            for msg in self.cache[channel_id]:
                try:
                    if client.get_messages(channel_id, msg["message_id"]):
                        valid_msgs.append(msg)
                except MessageIdInvalid:
                    continue
            self.cache[channel_id] = valid_msgs
        self._save_cache()

# Module-level functions that use a singleton cache instance
_cache = ChannelCache()

def store_message(channel_id: str, msg_data: Dict[str, Any]) -> None:
    """Store a message in the global cache."""
    _cache.store_message(channel_id, msg_data)

def get_last_messages(channel_id: str) -> List[Dict[str, Any]]:
    """Get the last N messages for a channel from the global cache."""
    return _cache.get_last_messages(channel_id)

def check_deleted_messages(client: Any) -> None:
    """Check for deleted messages using the global cache."""
    _cache.check_deleted_messages(client)
