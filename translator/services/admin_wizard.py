"""A small per-admin state machine for the 'add channel pair' menu flow.

Adding a channel pair from a DM used to require typing the whole
``/addchannel <name> <src_id> <dst_id>`` line. This wizard collects the three
fields across separate messages instead, prompting one at a time, so a
non-technical operator can do it from the button menu.

State is **in-memory only**, keyed by Telegram user id — nothing is persisted
until the final step commits through :func:`admin_commands._cmd_addchannel`,
which owns the real env-write / ``LOGICAL_CHANNELS`` / reload logic (we do not
duplicate it). A process restart simply drops a half-entered pair, which is fine:
no partial channel was ever written.

The validation here intentionally mirrors ``_cmd_addchannel`` (the same
``_NAME_RE``, the same integer check, the same duplicate-name guard) so the
wizard rejects exactly what the command would, and a confirmed entry can never
fail the final commit on a validation error.

``admin_commands`` is imported lazily inside the functions to avoid an import
cycle (it imports the menu, which would otherwise import us at module load).
"""

from __future__ import annotations

import html
from typing import Dict

from translator.services import admin_i18n

# uid -> {"step": "name"|"src"|"dst", "name": str, "src": str}
_PENDING: Dict[int, dict] = {}


def is_active(uid) -> bool:
    """True when ``uid`` is partway through the add-channel wizard."""
    return uid in _PENDING


def start(uid) -> None:
    """Begin (or restart) the wizard for ``uid`` at the first field."""
    _PENDING[uid] = {"step": "name"}


def cancel(uid) -> None:
    """Abandon any in-progress wizard for ``uid`` (no-op if none)."""
    _PENDING.pop(uid, None)


def _is_int(text: str) -> bool:
    try:
        int(text)
        return True
    except ValueError:
        return False


def feed(uid, text: str, lang: str = "en") -> str:
    """Advance the wizard with the admin's latest message; return the reply HTML.

    On the final step this commits via ``_cmd_addchannel`` and clears the state.
    A validation failure re-prompts the *same* field without advancing.
    """
    from translator.services import admin_commands as ac  # lazy: avoid cycle

    st = _PENDING.get(uid)
    if st is None:
        return admin_i18n.t("wiz_cancelled", lang)
    text = (text or "").strip()

    if st["step"] == "name":
        name = text.lower()
        if not ac._NAME_RE.fullmatch(name):
            return admin_i18n.t("wiz_bad_name", lang)
        if name in ac._logical_names():
            return admin_i18n.t("wiz_dup_name", lang, name=html.escape(name))
        st["name"] = name
        st["step"] = "src"
        return admin_i18n.t("wiz_prompt_src", lang)

    if st["step"] == "src":
        if not _is_int(text):
            return admin_i18n.t("wiz_bad_int", lang)
        st["src"] = text
        st["step"] = "dst"
        return admin_i18n.t("wiz_prompt_dst", lang)

    # st["step"] == "dst"
    if not _is_int(text):
        return admin_i18n.t("wiz_bad_int", lang)
    args = [st["name"], st["src"], text]
    cancel(uid)
    return ac._cmd_addchannel(args, lang)
