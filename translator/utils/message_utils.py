from typing import Any, Dict, List, Optional, Tuple

def get_media_info(msg, max_size: int) -> Tuple[Optional[str], Optional[int], str]:
    """Extract file_id, file_size_bytes, media_type from message."""
    file_id = None
    file_size_bytes = None
    media_type = "text"
    if msg.document and msg.document.file_size <= max_size:
        file_id = msg.document.file_id
        file_size_bytes = msg.document.file_size
        media_type = "doc"
    elif msg.photo and getattr(msg.photo, "file_size", 0) <= max_size:
        file_id = msg.photo.file_id
        file_size_bytes = getattr(msg.photo, "file_size", None)
        media_type = "photo"
    elif msg.video and msg.video.file_size <= max_size:
        file_id = msg.video.file_id
        file_size_bytes = msg.video.file_size
        media_type = "video"
    return file_id, file_size_bytes, media_type

def build_payload(msg, html_text: str, meta: Dict[str, Any]) -> Dict[str, Any]:
    """Build payload dict for translation."""
    source_link = (
        f'<a href="https://t.me/{msg.chat.username}">{msg.chat.title}</a>'
        if getattr(msg.chat, "username", None)
        else msg.chat.title
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
