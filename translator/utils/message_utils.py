import logging
import re
from html import escape
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("MEDIA")

# Telegram caps media captions at 1024 chars (plain messages allow 4096). We
# count raw HTML length (tags included) against this, which is conservative:
# Telegram counts only the visible caption text, so tag overhead is free margin.
CAPTION_LIMIT = 1024

_TAG_RE = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9-]*)[^>]*?(/?)>")


def _tags_balanced(html: str) -> bool:
    """True if ``html`` has every tag opened-and-closed and doesn't end mid-tag.

    Used to pick caption/remainder split points that never cut through a tag
    (e.g. a ``<a href=…>`` link or a ``<b>``/``<blockquote>`` span).
    """
    if html.count("<") != html.count(">"):
        return False  # ends inside an unfinished tag
    stack: List[str] = []
    for m in _TAG_RE.finditer(html):
        closing, name, self_closing = m.group(1), m.group(2).lower(), m.group(3)
        if name == "br" or self_closing:
            continue  # void / self-closing: no nesting
        if closing:
            if stack and stack[-1] == name:
                stack.pop()
            else:
                return False  # stray or mismatched close
        else:
            stack.append(name)
    return not stack


def split_caption_html(text: str, limit: int = CAPTION_LIMIT) -> Tuple[str, str]:
    """Split translated HTML into ``(caption, remainder)`` for a photo + reply.

    ``caption`` is the largest run of whole lines that fits within ``limit``
    while keeping all HTML tags balanced, so a tag/link is never cut in half.
    ``remainder`` is meant to be posted as a reply to the photo. If not even the
    first line fits with balanced tags (e.g. one giant paragraph), ``caption`` is
    empty and the whole text goes to ``remainder`` (photo sent without caption).
    """
    if len(text) <= limit and _tags_balanced(text):
        return text, ""
    best = 0
    for m in re.finditer(r"\n", text):
        pos = m.end()
        if pos > limit:
            break
        if _tags_balanced(text[:pos]):
            best = pos
    caption = text[:best].rstrip()
    remainder = text[best:].lstrip()
    return caption, remainder


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


def build_post_link(msg) -> str:
    """Build a human-clickable link to a source post for admin alerts.

    Public channels expose a ``t.me/<username>/<id>`` link; private channels
    (``-100…`` ids) use the internal ``t.me/c/<internal_id>/<id>`` form. When
    neither is resolvable, fall back to a plain ``(chat …, msg …)`` string so
    the alert still identifies the post.
    """
    msg_id = getattr(msg, "id", None) or getattr(msg, "message_id", None)
    chat = getattr(msg, "chat", None)
    username = getattr(chat, "username", None) if chat else None
    if username:
        return f"https://t.me/{username}/{msg_id}"
    chat_id = getattr(chat, "id", None) if chat else None
    cid = str(chat_id) if chat_id is not None else ""
    if cid.startswith("-100"):
        return f"https://t.me/c/{cid[4:]}/{msg_id}"
    return f"(chat {chat_id}, msg {msg_id})"


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
