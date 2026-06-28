"""
Centralized configuration with environment validation and
bi-directional channel lookups.
"""

import os
from typing import Dict, Any, List
from pathlib import Path
from dataclasses import dataclass
import logging
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass  # dotenv is optional

from translator.models import ChannelConfig


@dataclass(frozen=True)
class ChannelInfo:
    channel_id: int                # Telegram channel ID
    channel_name: str   # Human-readable channel name
    channel_type: str              # "source" or "destination"
    pair_key: int # The paired channel's ID (destination for source, source for destination)

    def __str__(self):
        return (
            f"ChannelInfo(\n"
            f"  channel_id={self.channel_id}\n"
            f"  channel_name={self.channel_name}\n"
            f"  channel_type={self.channel_type}\n"
            f"  pair_key={self.pair_key}\n"
            f")"
        )


class Config:
    def __init__(self) -> None:
        self.reload()

    def reload(self) -> None:
        # Core values
        self.TELEGRAM_BOT_TOKEN = self._require("TELEGRAM_BOT_TOKEN")
        self.TELEGRAM_API_ID = int(self._require("TELEGRAM_API_ID"))
        self.TELEGRAM_API_HASH = self._require("TELEGRAM_API_HASH")
        self.ANTHROPIC_API_KEY = self._require("ANTHROPIC_API_KEY")
        self.SOURCE_TEST_ID = int(self._require("TEST_CHANNEL"))
        self.LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

        # Load channel mappings
        self.channels: Dict[str, ChannelInfo] = {}
        for logical in ("christianvision", "shaltnotkill", "test"):
            src_env = f"{logical.upper()}_CHANNEL"
            tgt_env = f"{logical.upper()}_EN_CHANNEL_ID"
            src_id = int(self._require(src_env))
            tgt_id = os.getenv(tgt_env)
            if not tgt_id:
                raise RuntimeError(
                    f"Missing required environment variable: {tgt_env} for logical channel '{logical}'"
                )
            tgt_id = int(tgt_id)
            src_name_env = os.getenv(f"{logical.upper()}_CHANNEL_NAME", logical)
            tgt_name_env = os.getenv(f"{logical.upper()}_EN_CHANNEL_NAME", logical + "_en")
            # Add source channel
            self.channels[logical] = ChannelInfo(
                channel_id=src_id,
                channel_name=src_name_env,
                channel_type="source",
                pair_key=tgt_id,
            )
            # Add destination channel if present
            if tgt_id:
                self.channels[logical + "_en"] = ChannelInfo(
                    channel_id=int(tgt_id),
                    channel_name=tgt_name_env,
                    channel_type="destination",
                    pair_key=src_id,
                )

    def _require(self, var: str) -> str:
        val = os.getenv(var)
        if not val:
            raise RuntimeError(f"Missing required environment variable: {var}")
        return val

    def get_channel_id(self, name: str) -> int:
        """Get source-channel ID by logical name."""
        info = self.channels.get(name)
        if info :
            return info.channel_id 
        else:
            raise ValueError(f"Channel '{name}' not found in configuration.")
        
    def get_destination_id(self, src_channel_id: int) -> int:
        """
        Get destination channel_id by source channel id (int).
        Returns the paired destination channel's id, or raises ValueError if not found.
        """
        for ch in self.channels.values():
            if ch.channel_id == src_channel_id and ch.channel_type == "source" and ch.pair_key:
                dest = next((d for d in self.channels.values()
                             if d.channel_id == ch.pair_key and d.channel_type == "destination"), None)
                if dest:
                    return dest.channel_id
                else:
                    print(f"[WARNING] No paired destination channel for ID: {src_channel_id}")
                    raise ValueError(f"No paired destination channel for ID: {src_channel_id}")
        print(f"[WARNING] No destination channel found for: {src_channel_id}")
        raise ValueError(f"No destination channel found for: {src_channel_id}")

    def get_channel_name(self, channel_id: int) -> str:
        """
        Reverse lookup: channel_id → channel_name.
        Accepts channel_id as str or int.
        """
        for info in self.channels.values():
            if info:
                if info.channel_id == channel_id:
                    # logging.info("[DEBUG] Found channel name for ID %s: %s", channel_id, info.channel_name)
                    return info.channel_name
        raise ValueError(f"Channel ID '{channel_id}' not found in configuration.")

    def validate(self) -> None:
        """Ensure required env vars are set."""
        keys = [
            "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_API_ID",
            "TELEGRAM_API_HASH",
            "ANTHROPIC_API_KEY",
            "SOURCE_TEST_ID",
            *(f"{n.upper()}_CHANNEL" for n in self.channels),
        ]
        missing = [k for k in keys if not os.getenv(k)]
        if missing:
            raise RuntimeError(f"Missing required variables: {', '.join(missing)}")

    def as_dict(self) -> Dict[str, Any]:
        """Return config snapshot for debugging."""
        return {
            "TELEGRAM_BOT_TOKEN": self.TELEGRAM_BOT_TOKEN,
            "TELEGRAM_API_ID": self.TELEGRAM_API_ID,
            "TELEGRAM_API_HASH": self.TELEGRAM_API_HASH,
            "ANTHROPIC_API_KEY": self.ANTHROPIC_API_KEY,
            "LOG_LEVEL": self.LOG_LEVEL,
            "channels": {n: info.__dict__ for n, info in self.channels.items()},
        }

    def __str__(self):
        def crop(token):
            if not token:
                return ""
            return token[:8] + "..." if len(token) > 8 else token

        return (
            f"Config(\n"
            f"  TELEGRAM_BOT_TOKEN={crop(self.TELEGRAM_BOT_TOKEN)!r},\n"
            f"  TELEGRAM_API_ID={self.TELEGRAM_API_ID!r},\n"
            f"  TELEGRAM_API_HASH={crop(self.TELEGRAM_API_HASH)!r},\n"
            f"  ANTHROPIC_API_KEY={crop(self.ANTHROPIC_API_KEY)!r},\n"
            f"  SOURCE_TEST_ID={self.SOURCE_TEST_ID!r},\n"
            f"  LOG_LEVEL={self.LOG_LEVEL!r},\n"
            f"  channels={{\n    " +
            ",\n    ".join(f"{k}: {v!r}" for k, v in self.channels.items()) +
            "\n  }\n)"
        )

    def get_source_channel_ids(self) -> List[int | str]:
        """
        Return a list of all source channel IDs as strings.
        """
        return [info.channel_id for info in self.channels.values() if info.channel_type == "source"]

    def get_destination_msg_id(self, source_channel_id: int, message_id: str) -> str | None:
        """
        Get the destination message ID for a given source channel and message ID.
        
        Args:
            source_channel_id (int): The source channel ID
            message_id (str): The source message ID

        Returns:
            str: The destination message ID if found, None otherwise

        Raises:
            ValueError: If the input parameters are invalid
            FileNotFoundError: If events.json cannot be loaded
            json.JSONDecodeError: If events.json is malformed
        """
        import json
        import logging
        from pathlib import Path
        from .models import MessageEvent

        if not isinstance(source_channel_id, int):
            raise ValueError("source_channel_id must be an integer")
        if not message_id:
            raise ValueError("message_id cannot be empty")

        # Convert to strings for comparison since events log stores them as strings
        source_channel_id_str = str(source_channel_id)
        message_id_str = str(message_id)

        # Get path to events.json
        events_path = Path(EVENTS_PATH)
        if not events_path.exists():
            logging.warning(f"Events file not found: {events_path}")
            return None

        try:
            # Load and parse events.json
            with open(events_path, "r", encoding="utf-8") as f:
                events_data = json.load(f)
                
            # Search through messages in reverse order (newest first) to get the latest state
            # This handles cases where a message may have been reposted or edited
            for event in reversed(events_data.get("messages", [])):
                if (str(event["source_channel_id"]) == source_channel_id_str and 
                    str(event["message_id"]) == message_id_str and
                    event["dest_message_id"] is not None):  # Ensure we have a valid destination ID
                    # Found a match - return the destination message ID
                    logging.debug(
                        f"Found mapping: source channel {source_channel_id}, "
                        f"message {message_id} -> destination message {event['dest_message_id']}"
                    )
                    return str(event["dest_message_id"])

            # No matching event found
            logging.debug(
                f"No event found mapping source channel {source_channel_id}, "
                f"message {message_id} to a destination message"
            )
            return None

        except json.JSONDecodeError as e:
            logging.error(f"Failed to parse events.json: {e}")
            raise
        except Exception as e:
            logging.error(f"Error searching events log: {e}")
            return None

# Singleton config
CONFIG = Config()

# Paths and defaults
CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")
EVENTS_PATH = os.path.join(CACHE_DIR, "events.json")
STORE_PATH = os.path.join(CACHE_DIR, "channel_cache.json")
DEFAULT_STATS = {"messages": []}
MESSAGES_LIMIT = 9

# Prompt loader
PROMPT_TEMPLATE_PATH = Path(__file__).parent / "prompt_template.txt"


def load_prompt_template() -> str:
    return (
        PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")
        if PROMPT_TEMPLATE_PATH.exists()
        else "{message_text}"
    )


# Build ChannelConfig map for telegram_sender
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHANNEL_CONFIGS: Dict[str, ChannelConfig] = {}
for logical, info in CONFIG.channels.items():
    if info.channel_type == "destination":
        CHANNEL_CONFIGS[logical] = ChannelConfig(
            channel_id=int(info.channel_id),
            bot_token=BOT_TOKEN,
        )
