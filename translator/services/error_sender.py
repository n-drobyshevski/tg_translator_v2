"""Lightweight failure alerting to a Telegram admin chat.

Motivation: the retired-model outage sat broken for weeks because failures only
landed in a log file nobody watched. This pushes critical failures to a chat.

Enable by setting ``ADMIN_ALERT_CHAT_ID`` — or, failing that, ``ADMIN_CHAT_ID``
(the same admin who controls the bot via DM) — to a chat/user id the bot can
message. When neither is set, alerts are no-ops (logged only), so this is safe
to call anywhere. Alerts are throttled per signature to avoid floods when every
message fails.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Dict, Optional

import httpx

from translator.config import BOT_TOKEN

logger = logging.getLogger("ALERT")

# Minimum seconds between alerts sharing the same signature.
_MIN_INTERVAL = float(os.getenv("ALERT_MIN_INTERVAL", "300"))
_last_sent: Dict[str, float] = {}


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

    # Read live so a /reload-added ADMIN_CHAT_ID is honored without a restart.
    chat_id = os.getenv("ADMIN_ALERT_CHAT_ID") or os.getenv("ADMIN_CHAT_ID", "")
    if not chat_id or not BOT_TOKEN:
        logger.warning(
            "Alert (undelivered; set ADMIN_ALERT_CHAT_ID or ADMIN_CHAT_ID): %s", text
        )
        return False

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                url, json={"chat_id": chat_id, "text": text[:4000]}
            )
        if r.status_code != 200:
            logger.error("Alert delivery failed (%s): %s", r.status_code, r.text)
            return False
        return True
    except Exception as e:
        logger.error("Alert delivery error: %s", e)
        return False
