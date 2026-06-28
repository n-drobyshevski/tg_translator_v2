"""Manage the Telegram-admin allow-list and their display labels.

Admin user IDs are authoritative and live in the ``ADMIN_CHAT_ID`` env var
(parsed into ``CONFIG.ADMIN_CHAT_IDS``). Add/remove rewrites the whole
comma-joined string via :mod:`translator.services.env_store` and reloads
``CONFIG``, mirroring the channel commands in
:mod:`translator.services.admin_commands`.

Optional human labels are *display-only* metadata kept in a small JSON file
(``translator/cache/admin_labels.json``) so free text never has to be quoted
into ``.env``; this follows the existing ``cache/channel_cache.json`` precedent.

Names are also resolved best-effort via the Bot API ``getChat`` — which only
returns a username/name for users who have DM'd the bot (a Telegram privacy
limit), so resolution falls back to the raw numeric id. Results are cached
briefly to keep the DM menu snappy and avoid hammering the API.

These helpers are deliberately free of Pyrogram/Flask plumbing so they can be
unit-tested with a fake ``.env`` path and a monkeypatched ``requests``.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

from translator.config import CONFIG
from translator.services import env_store

log = logging.getLogger("ADMIN.STORE")

# translator/services/admin_store.py -> translator/cache/admin_labels.json
_LABELS_FILE = Path(__file__).resolve().parents[1] / "cache" / "admin_labels.json"

_HTTP_TIMEOUT = 4  # short: a slow/failed getChat must not stall the DM menu
_CACHE_TTL = 600.0  # seconds to cache a resolved (or failed) name lookup
_name_cache: Dict[int, Tuple[Optional[str], float]] = {}


def _labels_path() -> Path:
    """Path to the labels JSON (indirected so tests can redirect it)."""
    return _LABELS_FILE


# --- ID validation -----------------------------------------------------------


def _parse_id(raw: str) -> Optional[int]:
    """Parse a Telegram user id, accepting an optional leading ``-``.

    Mirrors the filter the config parser applies to ``ADMIN_CHAT_ID``
    (``x.strip().lstrip("-").isdigit()``). Returns ``None`` for anything that
    isn't a whole number.
    """
    s = (raw or "").strip()
    if not s or s == "-" or not s.lstrip("-").isdigit():
        return None
    return int(s)


def _reload() -> Optional[str]:
    """Run ``CONFIG.reload()``; return an error string on failure, else None."""
    try:
        CONFIG.reload()
        return None
    except Exception as exc:  # pragma: no cover - only a broken .env trips this
        return str(exc)


# --- Label persistence -------------------------------------------------------


def get_labels() -> Dict[str, str]:
    """Read the id->label map; tolerate a missing/corrupt file."""
    path = _labels_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        log.warning("admin_labels.json unreadable; ignoring")
        return {}


def _write_labels(labels: Dict[str, str]) -> None:
    """Atomically persist the id->label map (same-dir temp file + os.replace)."""
    path = _labels_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=str(path.parent), prefix=".admin_labels.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(labels, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def set_label(raw_id: str, label: Optional[str]) -> Tuple[bool, str]:
    """Set (or clear, when ``label`` is blank) the display label for an id."""
    uid = _parse_id(str(raw_id))
    if uid is None:
        return False, "id must be a whole number (Telegram user id)"
    labels = get_labels()
    clean = (label or "").strip()
    if clean:
        labels[str(uid)] = clean
    else:
        labels.pop(str(uid), None)
    _write_labels(labels)
    return True, f"label for {uid} updated"


# --- Name resolution (best-effort) -------------------------------------------


def resolve_name(uid: int) -> Optional[str]:
    """Best-effort ``@username`` / full name for ``uid`` via Bot API getChat.

    Returns ``None`` when the bot can't resolve the user (they never DM'd it,
    no token, network error, etc.). Results — including failures — are cached
    for ``_CACHE_TTL`` seconds.
    """
    cached = _name_cache.get(uid)
    if cached is not None and (time.monotonic() - cached[1]) < _CACHE_TTL:
        return cached[0]

    name: Optional[str] = None
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if token:
        try:
            r = requests.get(
                f"https://api.telegram.org/bot{token}/getChat",
                params={"chat_id": uid},
                timeout=_HTTP_TIMEOUT,
            )
            if r.status_code == 200:
                res = r.json().get("result", {})
                if res.get("username"):
                    name = "@" + res["username"]
                else:
                    full = " ".join(
                        p for p in (res.get("first_name"), res.get("last_name")) if p
                    )
                    name = full or None
        except Exception:
            name = None  # best-effort; fall back to the raw id

    _name_cache[uid] = (name, time.monotonic())
    return name


# --- Listing -----------------------------------------------------------------


def list_admins(resolve: bool = True) -> List[dict]:
    """Return one dict per admin: ``{id, label, resolved, display}``.

    ``display`` is the manual label, else the resolved name, else the raw id.
    """
    labels = get_labels()
    out: List[dict] = []
    for uid in CONFIG.ADMIN_CHAT_IDS:
        manual = labels.get(str(uid))
        resolved = resolve_name(uid) if resolve else None
        out.append(
            {
                "id": uid,
                "label": manual,
                "resolved": resolved,
                "display": manual or resolved or str(uid),
            }
        )
    return out


# --- Mutations ---------------------------------------------------------------


def add_admin(raw_id: str, label: Optional[str] = None) -> Tuple[bool, str]:
    """Add ``raw_id`` to the admin list (optionally with a label)."""
    new_id = _parse_id(raw_id)
    if new_id is None:
        return False, "id must be a whole number (Telegram user id)"
    ids = list(CONFIG.ADMIN_CHAT_IDS)
    if new_id in ids:
        if label and label.strip():
            set_label(str(new_id), label)
            return True, f"{new_id} is already an admin (label updated)"
        return False, f"{new_id} is already an admin"
    ids.append(new_id)
    env_store.set_env_var("ADMIN_CHAT_ID", ",".join(str(i) for i in ids))
    err = _reload()
    if err:
        return False, f"add failed on reload: {err}"
    if label and label.strip():
        set_label(str(new_id), label)
    return True, f"added admin {new_id}"


def remove_admin(raw_id: str) -> Tuple[bool, str]:
    """Remove ``raw_id`` from the admin list, refusing to empty it."""
    target = _parse_id(raw_id)
    if target is None:
        return False, "id must be a whole number (Telegram user id)"
    ids = list(CONFIG.ADMIN_CHAT_IDS)
    if target not in ids:
        return False, f"{target} is not an admin"
    if len(ids) <= 1:
        return (
            False,
            "refusing to remove the last admin (would lock out DM control and alerts)",
        )
    env_store.set_env_var(
        "ADMIN_CHAT_ID", ",".join(str(i) for i in ids if i != target)
    )
    err = _reload()
    if err:
        return False, f"remove failed on reload: {err}"
    labels = get_labels()
    if labels.pop(str(target), None) is not None:
        _write_labels(labels)
    return True, f"removed admin {target}"
