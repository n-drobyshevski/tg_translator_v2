"""Lightweight failure alerting to a Telegram admin chat.

Motivation: the retired-model outage sat broken for weeks because failures only
landed in a log file nobody watched. This pushes critical failures to a chat.

Enable by setting ``ADMIN_ALERT_CHAT_ID`` — or, failing that, ``ADMIN_CHAT_ID``
(the same admin who controls the bot via DM) — to a chat/user id the bot can
message. When neither is set, alerts are no-ops (logged only), so this is safe
to call anywhere. Alerts are throttled per signature to avoid floods when every
message fails.

Alerts are sent as **rich messages** (Bot API 10.3 ``sendRichMessage``): the
first line becomes a heading, the ``Key: value`` lines after it a table, and
anything else — a traceback — an expandable quotation that keeps its tail.
Every caller already writes that shape, so the signature stays plain text. If
Telegram refuses the rich payload the same text goes out through
``sendMessage`` exactly as before; ``ADMIN_RICH_MESSAGES=0`` skips rich entirely.
"""

from __future__ import annotations

import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Dict, Optional

import httpx

from translator.config import BOT_TOKEN
from translator.services import rich_html
from translator.services.rich_html import KV, Doc, Footer, Heading, RawQuote, esc

logger = logging.getLogger("ALERT")

# Minimum seconds between alerts sharing the same signature.
_MIN_INTERVAL = float(os.getenv("ALERT_MIN_INTERVAL", "300"))
_last_sent: Dict[str, float] = {}

# "Channel: News" / "Post: https://…" — a short label, then a value.
_KV_LINE = re.compile(r"^([^:\s][^:]{0,30}):\s+(\S.*)$")
_TITLE_MAX = 200


def _kv_value(value: str) -> str:
    value = value.strip()
    if re.fullmatch(r"https?://\S+", value):
        return f'<a href="{esc(value)}">{esc(value)}</a>'
    return esc(value)


def build_alert_html(text: str) -> str:
    """Rich-message HTML for an alert: heading, key/value table, details quote."""
    lines = str(text).split("\n")
    title = lines[0].strip() or "Alert"
    rest_lines = lines[1:]
    if len(title) > _TITLE_MAX:
        # A long first line (typically a formatted log record) keeps its full
        # text in the quotation below; the heading just has to be scannable.
        rest_lines = [title] + rest_lines
        title = title[:_TITLE_MAX] + "…"
    if title[0].isalnum():
        title = "🚨 " + title

    pairs = []
    while rest_lines and _KV_LINE.match(rest_lines[0]):
        key, value = _KV_LINE.match(rest_lines[0]).groups()
        pairs.append((esc(key), _kv_value(value)))
        rest_lines = rest_lines[1:]
    rest = "\n".join(rest_lines).strip("\n")

    doc = Doc(
        Heading(esc(title), 4),
        KV(pairs) if pairs else None,
        # The exception line is at the bottom of a traceback, so keep the tail.
        RawQuote(rest, expandable=True, keep="tail") if rest.strip() else None,
        Footer(datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")),
    )
    return doc.render().rich


def _alert_chat_id() -> str:
    """The alert target, read live so a /reload-added ADMIN_CHAT_ID is honored.

    ``ADMIN_CHAT_ID`` may list several admins (``"111,222"`` — see config.py),
    which Telegram rejects as a chat id, so alerts go to the first one.
    """
    raw = os.getenv("ADMIN_ALERT_CHAT_ID") or os.getenv("ADMIN_CHAT_ID", "")
    return re.split(r"[,;]", raw)[0].strip()


async def send_alert(text: str, key: Optional[str] = None) -> bool:
    """Best-effort alert to the admin chat. Returns True if delivered.

    ``key`` groups alerts for throttling (defaults to a prefix of the text).
    Never raises — failures are logged so alerting can't break the relay.
    """
    sig = key or text[:60]
    now = time.monotonic()
    last = _last_sent.get(sig)
    if last is not None and (now - last) < _MIN_INTERVAL:
        return False
    _last_sent[sig] = now

    chat_id = _alert_chat_id()
    if not chat_id or not BOT_TOKEN:
        logger.warning(
            "Alert (undelivered; set ADMIN_ALERT_CHAT_ID or ADMIN_CHAT_ID): %s", text
        )
        return False

    rich = None
    if rich_html.rich_env_enabled():
        try:
            rich = build_alert_html(text)
        except Exception:
            logger.warning("alert rich formatting failed", exc_info=True)

    base = f"https://api.telegram.org/bot{BOT_TOKEN}"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            if rich:
                # WARNING, not ERROR, below: this logger is skipped by the
                # forwarder anyway, but a handled fallback is not an error.
                try:
                    r = await client.post(
                        f"{base}/sendRichMessage",
                        json={"chat_id": chat_id, "rich_message": {"html": rich}},
                    )
                    if r.status_code == 200:
                        return True
                    logger.warning("Rich alert refused (%s): %s", r.status_code, r.text)
                except Exception as e:
                    logger.warning("Rich alert error: %s", e)
            r = await client.post(
                f"{base}/sendMessage", json={"chat_id": chat_id, "text": text[:4000]}
            )
        if r.status_code != 200:
            logger.error("Alert delivery failed (%s): %s", r.status_code, r.text)
            return False
        return True
    except Exception as e:
        logger.error("Alert delivery error: %s", e)
        return False
