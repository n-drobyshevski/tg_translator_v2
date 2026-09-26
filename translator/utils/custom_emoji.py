"""Custom emoji in relayed posts: keep them when Telegram allows it, else fall back.

Telegram lets a bot put custom emoji (``<tg-emoji emoji-id="…">``) into a
*channel* post only if the bot owns an extra username bought on Fragment; the
Bot API 9.4 allowance for bots whose owner has Premium covers private chats and
groups, not channels. Mirrored posts carry the *source* channel's emoji, so
without that right Telegram refuses the post.

``PRESERVE_CUSTOM_EMOJI`` selects the behaviour:

* ``auto`` (the default, also when unset): keep the emoji; if Telegram refuses
  a post that contains them, the sender re-sends it once with the emoji
  flattened to their plain fallback character and remembers that for
  :data:`COOLDOWN` seconds, so later posts are flattened up front instead of
  costing a refused call each. After the cool-down the next post tries again —
  which is how a newly bought Fragment username starts working without a
  restart.
* ``1`` / ``true`` / ``yes`` / ``on``: always keep them (the fallback retry still
  applies, but nothing is remembered).
* ``0`` / ``false`` / ``no`` / ``off``: always flatten (the old default).

State is per process. The Flask app's own sanitizer
(``app/admin_manager._preserve_custom_emoji``) still flattens when the variable
is unset and keeps the tags for any other value; its posts go through the same
:class:`TelegramSender`, so the flattened retry covers them too.
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any, Dict, Optional

log = logging.getLogger("EMOJI")

ENV = "PRESERVE_CUSTOM_EMOJI"
COOLDOWN = 24 * 3600.0

TG_EMOJI_RE = re.compile(r"<tg-emoji\b[^>]*>(.*?)</tg-emoji>", re.DOTALL)

_TRUTHY = frozenset({"1", "true", "yes", "on"})
_FALSEY = frozenset({"0", "false", "no", "off"})

# monotonic() of the last refusal that a flattened retry fixed; None = none yet.
_refused_at: Optional[float] = None


def mode() -> str:
    """``"auto"``, ``"on"`` or ``"off"`` from the env (read live)."""
    raw = (os.getenv(ENV) or "").strip().lower()
    if raw in _TRUTHY:
        return "on"
    if raw in _FALSEY:
        return "off"
    return "auto"


def should_preserve() -> bool:
    """Whether to keep ``<tg-emoji>`` in the HTML sent to Telegram right now."""
    m = mode()
    if m == "on":
        return True
    if m == "off":
        return False
    return _refused_at is None or time.monotonic() - _refused_at >= COOLDOWN


def mark_refused(reason: Any = None) -> None:
    """Record that Telegram refused custom emoji (auto mode flattens for a while)."""
    global _refused_at
    if mode() != "auto":
        return
    first = _refused_at is None or time.monotonic() - _refused_at >= COOLDOWN
    _refused_at = time.monotonic()
    if first:
        log.warning(
            "Telegram refused custom emoji (%s); relaying them as plain emoji for "
            "the next %dh. A bot can post custom emoji in a channel only with a "
            "Fragment username.",
            reason,
            int(COOLDOWN // 3600),
        )


def reset() -> None:
    """Forget any recorded refusal (tests, or after buying a Fragment username)."""
    global _refused_at
    _refused_at = None


def flatten(text: str) -> str:
    """Replace every ``<tg-emoji …>X</tg-emoji>`` with its plain fallback ``X``."""
    return TG_EMOJI_RE.sub(r"\1", text)


def flatten_body(body: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """A copy of a Bot API request body with custom emoji flattened, or None.

    Covers every place relayed HTML travels: ``text`` (sendMessage / edits),
    ``caption`` (media), and ``media`` (sendMediaGroup's JSON-encoded list, where
    the tag's quotes are JSON-escaped — the pattern matches either way). Returns
    None when there is nothing to flatten, so the caller knows a retry is moot.
    """
    if not body:
        return None
    changed = False
    out = dict(body)
    for key, value in body.items():
        if isinstance(value, str) and "<tg-emoji" in value:
            out[key] = flatten(value)
            changed = True
    return out if changed else None
