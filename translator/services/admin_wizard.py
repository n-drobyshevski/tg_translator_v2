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

from typing import Dict

from translator.services import admin_i18n
from translator.services.rich_html import (
    Bullets,
    Doc,
    Footer,
    Heading,
    Para,
    RichText,
    Status,
    esc,
)

# uid -> {"step": "name"|"src"|"dst", "name": str, "src": str}
_PENDING: Dict[int, dict] = {}

# (step, label key, instruction key) in the order the wizard asks for them.
_STEPS = (
    ("name", "lbl_wiz_name", "txt_wiz_name"),
    ("src", "lbl_wiz_src", "txt_wiz_src"),
    ("dst", "lbl_wiz_dst", "txt_wiz_dst"),
)


def is_active(uid) -> bool:
    """True when ``uid`` is partway through the add-channel wizard."""
    return uid in _PENDING


def current_step(uid) -> str | None:
    """Which field the wizard is waiting on: ``name``/``src``/``dst``, else None.

    The Pyrogram layer reads this *after* :func:`feed` to decide whether to
    attach the native channel picker — the id steps get one, the name step does
    not. Kept here rather than inferred from the reply text so the two can't
    drift apart.
    """
    st = _PENDING.get(uid)
    return st.get("step") if st else None


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


def _step_doc(st: dict, lang: str) -> Doc:
    """Heading with the step number, a ✅ / ▶️ / ▫️ progress list, the ask."""
    t = admin_i18n.t
    index = next(i for i, (step, _, _) in enumerate(_STEPS) if step == st["step"])
    items = []
    for i, (step, label_key, _) in enumerate(_STEPS):
        label = t(label_key, lang)
        if i < index:
            items.append(f"✅ {label}: <code>{esc(st.get(step, ''))}</code>")
        elif i == index:
            items.append(f"▶️ <b>{label}</b>")
        else:
            items.append(f"▫️ {label}")
    return Doc(
        Heading(t("h_wizard", lang, step=index + 1)),
        Bullets(items),
        Para(t(_STEPS[index][2], lang)),
        Footer(t("hint_wiz_cancel", lang)),
    )


def prompt(uid, lang: str = "en") -> RichText:
    """The current step's prompt for ``uid`` (the first one right after start)."""
    st = _PENDING.get(uid)
    if st is None:
        return cancelled(lang)
    return _step_doc(st, lang).render()


def cancelled(lang: str = "en") -> RichText:
    t = admin_i18n.t
    return Doc(Status(True, t("ok_cancelled", lang)), Para(t("txt_wiz_cancelled", lang))).render()


def _retry(title_html: str, lang: str) -> RichText:
    """A validation failure: the same field is asked again, nothing advances."""
    return Doc(Status(False, title_html), Para(admin_i18n.t("txt_retry", lang))).render()


def feed(uid, text: str, lang: str = "en") -> RichText:
    """Advance the wizard with the admin's latest message; return the reply.

    On the final step this commits via ``_cmd_addchannel`` and clears the state.
    A validation failure re-prompts the *same* field without advancing.
    """
    from translator.services import admin_commands as ac  # lazy: avoid cycle

    t = admin_i18n.t
    st = _PENDING.get(uid)
    if st is None:
        return cancelled(lang)
    text = (text or "").strip()

    if st["step"] == "name":
        name = text.lower()
        if not ac._NAME_RE.fullmatch(name):
            return _retry(t("err_wiz_name", lang), lang)
        if name in ac._logical_names():
            return _retry(t("err_wiz_dup", lang, name=esc(name)), lang)
        st["name"] = name
        st["step"] = "src"
        return _step_doc(st, lang).render()

    if st["step"] == "src":
        if not _is_int(text):
            return _retry(t("err_wiz_int", lang), lang)
        st["src"] = text
        st["step"] = "dst"
        return _step_doc(st, lang).render()

    # st["step"] == "dst"
    if not _is_int(text):
        return _retry(t("err_wiz_int", lang), lang)
    args = [st["name"], st["src"], text]
    cancel(uid)
    return ac._cmd_addchannel(args, lang)
