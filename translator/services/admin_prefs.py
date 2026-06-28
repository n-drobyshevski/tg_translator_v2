"""Per-admin UI preferences (currently: menu language).

The admin DM interface can render in English or Belarusian. Unlike the writable
*operational* settings (model, temperature, channels) — which are global and live
in ``.env`` via :mod:`translator.services.env_store` — a menu language is a
*personal* preference, so different operators can each pick their own without
affecting the others. It is therefore kept in a small JSON file
(``translator/cache/admin_prefs.json``), mirroring the display-label store in
:mod:`translator.services.admin_store` (same atomic-write, same ``_path``
indirection so tests can redirect it).

The file maps a stringified Telegram user id to a locale code:

    {"111": "be", "222": "en"}

A missing file, a corrupt file, or an unknown id all resolve to
:data:`translator.services.admin_i18n.DEFAULT_LANG`, so the menu never breaks on
a bad prefs file.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Dict, Tuple

from translator.services import admin_i18n

log = logging.getLogger("ADMIN.PREFS")

# translator/services/admin_prefs.py -> translator/cache/admin_prefs.json
_PREFS_FILE = Path(__file__).resolve().parents[1] / "cache" / "admin_prefs.json"


def _prefs_path() -> Path:
    """Path to the prefs JSON (indirected so tests can redirect it)."""
    return _PREFS_FILE


def _read() -> Dict[str, str]:
    """Read the id->lang map; tolerate a missing/corrupt file."""
    path = _prefs_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        log.warning("admin_prefs.json unreadable; ignoring")
        return {}


def _write(prefs: Dict[str, str]) -> None:
    """Atomically persist the id->lang map (same-dir temp file + os.replace)."""
    path = _prefs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=str(path.parent), prefix=".admin_prefs.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(prefs, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def get_lang(uid) -> str:
    """Return the stored locale for ``uid``, or the default if unset/unknown."""
    lang = _read().get(str(uid), admin_i18n.DEFAULT_LANG)
    return lang if lang in admin_i18n.LOCALES else admin_i18n.DEFAULT_LANG


def set_lang(uid, lang: str) -> Tuple[bool, str]:
    """Persist ``lang`` as ``uid``'s menu language. Rejects unknown locales."""
    if lang not in admin_i18n.LOCALES:
        return False, "unknown language"
    prefs = _read()
    prefs[str(uid)] = lang
    _write(prefs)
    return True, lang
