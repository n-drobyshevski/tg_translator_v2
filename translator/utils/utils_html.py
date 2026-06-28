import html
from typing import Any, List, Optional
from pyrogram.enums import MessageEntityType

def entities_to_html(text: str, entities: Optional[List[Any]]) -> str:
    """Convert Telegram message entities to HTML."""
    escaped = html.escape(text)
    if not entities:
        return escaped

    entities_sorted = sorted(entities, key=lambda e: e.offset, reverse=True)
    for ent in entities_sorted:
        start, length = ent.offset, ent.length
        end = start + length

        if ent.type == MessageEntityType.BOLD:
            open_tag, close_tag = "<b>", "</b>"
        elif ent.type == MessageEntityType.ITALIC:
            open_tag, close_tag = "<i>", "</i>"
        elif ent.type == MessageEntityType.CODE:
            open_tag, close_tag = "<code>", "</code>"
        elif ent.type == MessageEntityType.PRE:
            lang = getattr(ent, "language", "")
            open_tag = (
                f'<pre><code{" language="+html.escape(lang) if lang else ""}>'
            )
            close_tag = "</code></pre>"
        elif ent.type == MessageEntityType.TEXT_LINK:
            url = html.escape(ent.url)
            open_tag, close_tag = f'<a href="{url}">', "</a>"
        elif ent.type == MessageEntityType.TEXT_MENTION:
            user_id = ent.user.id
            open_tag, close_tag = f'<a href="tg://user?id={user_id}">', "</a>"
        else:
            continue

        before, middle, after = escaped[:start], escaped[start:end], escaped[end:]
        escaped = before + open_tag + middle + close_tag + after

    return escaped
