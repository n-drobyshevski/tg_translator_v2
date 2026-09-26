"""The one way the admin DM sends or edits a message.

Every admin reply is a rich message (Bot API 10.3) with a classic-HTML fallback
(see :mod:`translator.services.rich_html`). Keeping the send logic in one place
is what guarantees that: before this module there were eight hand-written
``reply_text`` / ``edit_message_text`` call sites, and only the inline menus had
ever been taught the rich tier. A guard test now fails on any direct call left
in ``admin_commands`` / ``admin_menu``.

Both helpers accept a :class:`~translator.services.rich_html.Doc`, a rendered
:class:`~translator.services.rich_html.RichText`, or a legacy classic ``str``.

``admin_menu`` is imported lazily (it imports ``admin_commands``, which imports
this module), following the existing cycle-avoidance pattern.
"""

from __future__ import annotations

import logging

from pyrogram import enums

from translator.services import rich_html

log = logging.getLogger("ADMIN.SEND")


def _classic(content: rich_html.RichText) -> str:
    """Classic text within Telegram's cap (Docs already are; a raw str may not be)."""
    text = str(content)
    if len(text) <= rich_html.CLASSIC_LIMIT:
        return text
    return text[: rich_html.CLASSIC_LIMIT - 1] + "…"


async def reply(msg, content, *, rows=None, reply_markup=None):
    """Reply to ``msg`` with ``content``.

    ``rows`` is an inline-menu spec (``admin_menu.Rows``): rich puts the buttons
    in the message body, and the tiers in ``admin_menu.send_with_markup`` apply.
    ``reply_markup`` is a ready markup — in practice a reply keyboard, which can
    never live in the body, so it rides along with the rich send as-is. Order:
    rich (+ keyboard) → classic (+ keyboard) → classic bare. The message is never
    dropped for the sake of its markup.
    """
    from translator.services import admin_menu  # lazy: avoid import cycle

    c = rich_html.as_content(content)
    text = _classic(c)
    # getattr: test fakes, and kurigram < 2.2.25, have no reply_rich.
    send_rich = getattr(msg, "reply_rich", None) if c.rich else None

    async def _send(body, **kw):
        return await msg.reply_text(body, parse_mode=enums.ParseMode.HTML, **kw)

    if rows:
        return await admin_menu.send_with_markup(
            _send, text, rows, send_rich=send_rich, rich_body=c.rich
        )

    if send_rich is not None and admin_menu.rich_enabled():
        ok, result = await admin_menu._try_rich(send_rich, c.rich, reply_markup, "reply")
        if ok:
            return result

    if reply_markup is None:
        return await _send(text)
    try:
        return await _send(text, reply_markup=reply_markup)
    except Exception:
        log.warning("reply refused its keyboard; sending without it", exc_info=True)
    return await _send(text)


async def edit(cq, content, *, rows=None):
    """Replace the message behind callback query ``cq`` with ``content``.

    The rich edit omits ``text`` on purpose: kurigram's ``edit_message_text``
    checks ``text`` *first* and silently ignores ``rich_message`` whenever both
    are given — which is exactly what the menus-only implementation did, so its
    "rich" edits were quietly classic. If every edit tier fails (other than
    ``MessageNotModified``, re-raised for the caller to swallow), the screen is
    sent as a new message rather than lost.
    """
    from pyrogram.errors import MessageNotModified

    from translator.services import admin_menu  # lazy: avoid import cycle

    c = rich_html.as_content(content)
    text = _classic(c)

    async def _edit(body, **kw):
        return await cq.edit_message_text(body, parse_mode=enums.ParseMode.HTML, **kw)

    async def _edit_rich(rich, reply_markup=None):
        return await cq.edit_message_text(rich_message=rich, reply_markup=reply_markup)

    send_rich = _edit_rich if (c.rich and admin_menu.HAS_RICH_MESSAGES) else None
    try:
        return await admin_menu.send_with_markup(
            _edit, text, rows or [], send_rich=send_rich, rich_body=c.rich
        )
    except MessageNotModified:
        raise
    except Exception:
        log.warning("edit failed; sending the screen as a new message", exc_info=True)
    message = getattr(cq, "message", None)
    if message is None:
        return None
    return await reply(message, c, rows=rows)

