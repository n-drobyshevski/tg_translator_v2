import logging
from typing import Optional
import requests


class TelegramAPI:
    """Helper class for Telegram API channel utilities."""

    @staticmethod
    def format_channel_id(channel_id: str) -> Optional[str]:
        """Format channel ID for Telegram API."""
        if not channel_id:
            return None
        channel_id = str(channel_id).strip()
        if channel_id.startswith("@"):
            return channel_id
        if channel_id.startswith("-100") and channel_id[4:].isdigit():
            return channel_id
        if channel_id.replace("-", "").isdigit():
            clean_id = channel_id.replace("-", "")
            return f"-100{clean_id}"
        if channel_id.isalnum() or "_" in channel_id:
            return f"@{channel_id}"
        logging.error("Invalid channel ID format: %s", channel_id)
        return None

    @staticmethod
    def validate_channel(
        channel_id: str, channel_name: str, bot_token: Optional[str] = None
    ):
        """Validate that the bot has access to the channel."""
        if not channel_id:
            raise ValueError(f"No channel ID provided for {channel_name}")

        base_url = f"https://api.telegram.org/bot{bot_token}"
        try:
            logging.info(
                "Attempting to validate channel %s with ID: %s",
                channel_name,
                channel_id,
            )
            response = requests.get(
                f"{base_url}/getChat", params={"chat_id": channel_id}, timeout=10
            )

            if response.status_code != 200:
                error_msg = response.json().get("description", "Unknown error")
                logging.error(
                    "Failed to validate %s channel (%s): %s",
                    channel_name,
                    channel_id,
                    error_msg,
                )
                raise ValueError(f"Invalid channel configuration for {channel_name}")

            chat_info = response.json().get("result", {})
            logging.info(
                "Successfully validated %s channel (%s)", channel_name, channel_id
            )
            logging.info(
                "Channel info: %s (%s)", chat_info.get("title"), chat_info.get("type")
            )

        except Exception as e:
            logging.error("Error validating %s channel: %s", channel_name, e)
            raise ValueError(
                f"Failed to validate {channel_name} channel configuration"
            ) from e


# convenience exports for direct import
format_channel_id = TelegramAPI.format_channel_id
validate_channel = TelegramAPI.validate_channel
