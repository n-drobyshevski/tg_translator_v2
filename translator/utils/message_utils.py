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
    # First present wins, so ORDER MATTERS. A live photo (Bot API 10.0) arrives
    # with `.photo` set to its still image as well, so it must be probed before
    # `photo` or its motion is silently dropped; its file_id is the video part
    # (see live_photo_still_id for the still). Pyrogram populates `.document`
    # (and sometimes `.video`) alongside `.animation` for GIFs, and a GIF
    # relayed via sendDocument loses its autoplay, so `animation` has to be
    # probed early too. Likewise `voice`/`video_note` are probed before the
    # generic `audio`/`video` they resemble.
    for kind, attr in (
        ("live_photo", "live_photo"),
        ("animation", "animation"),
        ("voice", "voice"),
        ("video_note", "video_note"),
        ("audio", "audio"),
        ("doc", "document"),
        ("photo", "photo"),
        ("video", "video"),
    ):
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

def live_photo_still_id(msg) -> Optional[str]:
    """File id of a live photo's static image (Pyrogram keeps it in ``.photo``)."""
    photo = getattr(msg, "photo", None)
    return getattr(photo, "file_id", None) if photo else None


def _plain(value) -> str:
    """Text of a Pyrogram ``FormattedText`` (or a plain str / None)."""
    if value is None:
        return ""
    return str(getattr(value, "text", value) or "")


def checklist_to_html(checklist) -> str:
    """A checklist as a text post: bold title, one ✅ / ⬜️ line per task.

    Bots can send real checklists only on behalf of a business account
    (``sendChecklist`` requires ``business_connection_id``), never to a channel,
    so the relay posts the checklist's content as translated text instead.
    """
    lines = []
    title = _plain(getattr(checklist, "title", ""))
    if title:
        lines.append(f"<b>{escape(title)}</b>")
    for task in getattr(checklist, "tasks", None) or []:
        done = getattr(task, "completed_by", None) or getattr(task, "completion_date", None)
        lines.append(f"{'✅' if done else '⬜️'} {escape(_plain(getattr(task, 'text', '')))}")
    return "\n".join(lines)


# sendPoll limits (Bot API 10.0).
POLL_QUESTION_MAX = 300
POLL_OPTION_MAX = 100
POLL_EXPLANATION_MAX = 200
POLL_DESCRIPTION_MAX = 1024


def _fit(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def poll_source_fields(poll) -> Dict[str, Any]:
    """The translatable text of a Pyrogram ``Poll``: question, options, extras."""
    return {
        "question": _plain(getattr(poll, "question", "")),
        "options": [_plain(getattr(o, "text", o)) for o in (getattr(poll, "options", None) or [])],
        "description": _plain(getattr(poll, "description", None)),
        "explanation": _plain(getattr(poll, "explanation", None)),
    }


def build_poll_request(poll, translated: Dict[str, Any], now_ts: float) -> Dict[str, Any]:
    """``sendPoll`` fields for a relayed poll, from the source poll + translations.

    Channel polls are always anonymous. A quiz whose correct answer the bot
    cannot see (the field is empty) goes out as a regular poll rather than
    failing — ``correct_option_ids`` is required for quizzes. A close date is
    copied only while it is still far enough ahead for Telegram to accept it
    (5 s … ~30 days).
    """
    body: Dict[str, Any] = {
        "question": _fit(translated["question"], POLL_QUESTION_MAX),
        "options": [{"text": _fit(o, POLL_OPTION_MAX)} for o in translated["options"]],
        "is_anonymous": True,
    }
    poll_type = str(getattr(getattr(poll, "type", None), "value", getattr(poll, "type", "")) or "").lower()
    correct = list(getattr(poll, "correct_option_ids", None) or [])
    if poll_type == "quiz" and correct:
        body["type"] = "quiz"
        body["correct_option_ids"] = sorted(correct)
        if translated.get("explanation"):
            body["explanation"] = _fit(translated["explanation"], POLL_EXPLANATION_MAX)
    else:
        body["type"] = "regular"
    if getattr(poll, "allows_multiple_answers", None):
        body["allows_multiple_answers"] = True
    if getattr(poll, "allows_revoting", None) is not None:
        body["allows_revoting"] = bool(poll.allows_revoting)
    if getattr(poll, "members_only", None):
        body["members_only"] = True
    if getattr(poll, "country_codes", None):
        body["country_codes"] = list(poll.country_codes)
    if translated.get("description"):
        body["description"] = _fit(translated["description"], POLL_DESCRIPTION_MAX)
    close_date = getattr(poll, "close_date", None)
    if close_date is not None:
        ts = close_date.timestamp() if hasattr(close_date, "timestamp") else float(close_date)
        if now_ts + 5 < ts < now_ts + 2_628_000:
            body["close_date"] = int(ts)
    if getattr(poll, "is_closed", None):
        body["is_closed"] = True
    return body


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
