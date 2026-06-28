import logging
from html import escape
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("MEDIA")


def get_media_info(msg, max_size: int) -> Tuple[Optional[str], Optional[int], str]:
    """Extract ``(file_id, file_size_bytes, media_type)`` from a message.

    The Bot API can only fetch files up to ``max_size`` (20 MB), so anything
    larger can't be re-sent and the post is relayed as text only. Previously that
    drop was silent; now it is logged at WARNING so an operator can see why the
    media is missing from the English channel.
    """
    file_id = None
    file_size_bytes = None
    media_type = "text"
    # A message carries at most one of these; first present wins.
    for kind, attr in (("doc", "document"), ("photo", "photo"), ("video", "video")):
        media = getattr(msg, attr, None)
        if not media:
            continue
        size = getattr(media, "file_size", 0) or 0
        if size <= max_size:
            file_id = media.file_id
            file_size_bytes = getattr(media, "file_size", None)
            media_type = kind
        else:
            logger.warning(
                "Skipping %s of %d bytes (over the %d-byte Bot API limit) in "
                "chat %s msg %s; relaying text only.",
                kind,
                size,
                max_size,
                getattr(getattr(msg, "chat", None), "id", "?"),
                getattr(msg, "id", "?"),
            )
        break
    return file_id, file_size_bytes, media_type

def build_payload(msg, html_text: str, meta: Dict[str, Any]) -> Dict[str, Any]:
    """Build payload dict for translation."""
    # Escape dynamic values before interpolating into the <a> link / HTML so a
    # username or title containing &, <, > or " can't break the markup.
    title = escape(msg.chat.title or "")
    source_link = (
        f'<a href="https://t.me/{escape(msg.chat.username, quote=True)}">{title}</a>'
        if getattr(msg.chat, "username", None)
        else title
    )
    html_with_source = f"{html_text}\n\nSource channel: {source_link}"
    return {
        "Channel": msg.chat.title,
        "Text": msg.text or msg.caption or "",
        "Html": html_with_source,
        "Link": f"https://t.me/{msg.chat.username}/{msg.id}",
        "Meta": meta,
    }


def extract_channel_info(
    msg, mapping: Dict[int, str], target: str
) -> Tuple[str, Optional[str], str, str]:
    """Extract IDs and names for stats logging."""
    src_id = str(msg.chat.id)
    src_name = getattr(msg.chat, "title", None)
    dst_name = target
    dst_id = ""
    for k, v in mapping.items():
        if v == target:
            dst_id = str(k)
            break
    return src_id, src_name, dst_id, dst_name
