"""Button-driven admin surface layered on top of the typed DM commands.

Non-technical operators get two Telegram keyboards instead of having to
remember slash commands:

* a **persistent reply keyboard** (always-visible buttons above the text box)
  whose taps send a label such as ``📊 Status`` — :func:`resolve_button_label`
  maps that label back to the existing ``/status`` command, and
* an **inline keyboard** for the Settings tree (model / temperature / max-tokens
  / log level / remove-channel / language), navigated in place via
  ``on_callback_query``.

Every action ultimately routes back through the ``_cmd_*`` helpers in
:mod:`translator.services.admin_commands` — no business logic is duplicated.
The pure menu logic (:func:`resolve_button_label`, :func:`handle_callback`,
:func:`build_menu`) is deliberately free of Pyrogram plumbing so it can be
unit-tested with plain strings; the Pyrogram-aware glue lives at the bottom.

All operator-facing text comes from :mod:`translator.services.admin_i18n` via
``t(key, lang)``; the active ``lang`` is the per-admin preference
(:mod:`translator.services.admin_prefs`), resolved at the Pyrogram entry points
and threaded down. Pure functions default ``lang="en"`` for back-compat.
"""

from __future__ import annotations

import html
import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

from pyrogram import enums

from translator.config import CONFIG
from translator.services import (
    admin_commands,
    admin_i18n,
    admin_prefs,
    admin_store,
    admin_wizard,
)
from translator.services.admin_i18n import t

log = logging.getLogger("ADMIN.MENU")

# A button row is a list of (label, callback_data) pairs; a menu is a list of
# rows. Reply-keyboard specs are just lists of rows of plain labels.
Row = List[Tuple[str, str]]
Rows = List[Row]


# --- Persistent reply keyboard ------------------------------------------------

# Each reply-keyboard button maps to a command (or a menu-bearing pseudo-command).
# Keyed by i18n string key so the *label* renders in any locale while the command
# it resolves to stays stable.
BUTTON_KEYS = {
    "btn_status": "/status",
    "btn_stats": "/stats",
    "btn_channels": "/channelsmenu",
    "btn_admins": "/adminsmenu",
    "btn_prompt": "/prompt",
    "btn_reload": "/reload",
    "btn_help": "/help",
    "btn_settings": "/settings",
    # Shown on the temporary "add admin" keyboard; resolves to /menu so tapping
    # it cancels the add-flow and restores the main keyboard.
    "btn_back_to_menu": "/menu",
}

# Reverse map built across *all* locales so a tapped label resolves to its
# command regardless of the language it was rendered in.
_LABEL_TO_CMD = {
    t(key, lang): cmd
    for key, cmd in BUTTON_KEYS.items()
    for lang in admin_i18n.LOCALES
}


def resolve_button_label(text: Optional[str]) -> Optional[str]:
    """Map a persistent-keyboard label (any locale) to its command, else None."""
    if not text:
        return None
    return _LABEL_TO_CMD.get(text.strip())


def build_reply_keyboard(lang: str = "en") -> List[List[str]]:
    """Spec for the persistent reply keyboard (rows of plain labels)."""
    return [
        [t("btn_status", lang), t("btn_stats", lang)],
        [t("btn_channels", lang), t("btn_admins", lang)],
        [t("btn_prompt", lang), t("btn_reload", lang)],
        [t("btn_help", lang), t("btn_settings", lang)],
    ]


# --- Inline settings menu tree ------------------------------------------------

MODEL_PRESETS = [
    ("Haiku 4.5 (default)", "claude-haiku-4-5"),
    ("Sonnet 4.6", "claude-sonnet-4-6"),
    ("Opus 4.8", "claude-opus-4-8"),
]
TEMP_PRESETS = ["0", "0.3", "0.5", "0.7", "1.0"]
TOKEN_PRESETS = ["1500", "2000", "4000", "8192"]


def _back_to_settings(lang: str = "en") -> Row:
    return [(t("btn_back", lang), "nav:settings")]


# Identifier echoed back in ``users_shared.button_id`` for the add-admin picker.
ADD_ADMIN_BUTTON_ID = 1


@dataclass
class CallbackResult:
    """What a button press should do: new message text + optional keyboard."""

    text: str
    rows: Optional[Rows] = None
    alert: Optional[str] = None  # short toast shown via callback_query.answer


def _settings_menu(lang: str = "en") -> Tuple[str, Rows]:
    title = t("settings_title", lang, summary=admin_commands._config_summary(lang))
    rows: Rows = [
        [(t("settings_btn_model", lang), "nav:model")],
        [
            (t("settings_btn_temp", lang), "nav:temp"),
            (t("settings_btn_tokens", lang), "nav:tokens"),
        ],
        [(t("settings_btn_log", lang), "nav:log")],
        [(t("settings_btn_rmch", lang), "nav:rmch")],
        [(t("btn_admins", lang), "nav:admins")],
        [(t("btn_language", lang), "nav:lang")],
        [(t("settings_btn_close", lang), "nav:close")],
    ]
    return title, rows


def _model_menu(lang: str = "en") -> Tuple[str, Rows]:
    title = t("model_title", lang, current=CONFIG.ANTHROPIC_MODEL)
    rows: Rows = [[(label, f"set:model:{value}")] for label, value in MODEL_PRESETS]
    rows.append(_back_to_settings(lang))
    return title, rows


def _temp_menu(lang: str = "en") -> Tuple[str, Rows]:
    title = t("temp_title", lang, current=CONFIG.ANTHROPIC_TEMPERATURE)
    rows: Rows = [
        [(v, f"set:temp:{v}") for v in TEMP_PRESETS],
        _back_to_settings(lang),
    ]
    return title, rows


def _tokens_menu(lang: str = "en") -> Tuple[str, Rows]:
    title = t("tokens_title", lang, current=CONFIG.ANTHROPIC_MAX_TOKENS)
    rows: Rows = [
        [(v, f"set:tokens:{v}") for v in TOKEN_PRESETS],
        _back_to_settings(lang),
    ]
    return title, rows


def _log_menu(lang: str = "en") -> Tuple[str, Rows]:
    title = t("log_title", lang, current=CONFIG.LOG_LEVEL)
    levels = sorted(admin_commands._VALID_LOG_LEVELS)
    rows: Rows = [[(lvl, f"set:log:{lvl}")] for lvl in levels]
    rows.append(_back_to_settings(lang))
    return title, rows


def _lang_menu(lang: str = "en") -> Tuple[str, Rows]:
    title = t("lang_title", lang)
    rows: Rows = [
        [(t("lang_en", lang), "setlang:en")],
        [(t("lang_be", lang), "setlang:be")],
        _back_to_settings(lang),
    ]
    return title, rows


def _channels_menu(lang: str = "en") -> Tuple[str, Rows]:
    title = admin_commands._cmd_channels(lang) + t("channels_menu_hint", lang)
    rows: Rows = [
        [(t("btn_add_channel_pair", lang), "addch:start")],
        _back_to_settings(lang),
    ]
    return title, rows


def _rmch_menu(lang: str = "en") -> Tuple[str, Rows]:
    title = t("rmch_menu_title", lang)
    removable = [
        n
        for n in admin_commands._logical_names()
        if n not in admin_commands._PROTECTED_CHANNELS
    ]
    if removable:
        rows: Rows = [[(name, f"rmch:{name}")] for name in removable]
    else:
        rows = [[(t("rmch_none", lang), "nav:settings")]]
    rows.append(_back_to_settings(lang))
    return title, rows


def _rmch_confirm(name: str, lang: str = "en") -> Tuple[str, Rows]:
    title = t("rmch_confirm_title", lang, name=name)
    rows: Rows = [
        [
            (t("btn_yes_remove", lang), f"rmchok:{name}"),
            (t("btn_no_back", lang), "nav:rmch"),
        ]
    ]
    return title, rows


def _admins_menu(lang: str = "en") -> Tuple[str, Rows]:
    admins = admin_store.list_admins()
    lines = [t("admins_menu_title", lang)]
    for a in admins:
        if a["label"]:
            lines.append(f"{html.escape(a['label'])} (<code>{a['id']}</code>)")
        elif a["resolved"]:
            lines.append(f"{html.escape(a['resolved'])} (<code>{a['id']}</code>)")
        else:
            lines.append(f"<code>{a['id']}</code>")
    if not admins:
        lines.append(t("common_none", lang))
    lines += ["", t("admins_menu_help", lang)]
    title = "\n".join(lines)
    rows: Rows = [
        [(f"🗑️ {a['display']}", f"rmadmin:{a['id']}")] for a in admins
    ]
    rows.append([(t("btn_add_admin", lang), "admin:add")])
    rows.append(_back_to_settings(lang))
    return title, rows


def _admin_confirm(uid: str, lang: str = "en") -> Tuple[str, Rows]:
    title = t("admin_confirm_title", lang, uid=html.escape(uid))
    rows: Rows = [
        [
            (t("btn_yes_remove", lang), f"rmadminok:{uid}"),
            (t("btn_no_back", lang), "nav:admins"),
        ]
    ]
    return title, rows


def build_menu(menu_id: str, lang: str = "en") -> Tuple[str, Rows]:
    """Return ``(title_html, rows)`` for a navigation target."""
    if menu_id == "model":
        return _model_menu(lang)
    if menu_id == "temp":
        return _temp_menu(lang)
    if menu_id == "tokens":
        return _tokens_menu(lang)
    if menu_id == "log":
        return _log_menu(lang)
    if menu_id == "lang":
        return _lang_menu(lang)
    if menu_id == "channels":
        return _channels_menu(lang)
    if menu_id == "rmch":
        return _rmch_menu(lang)
    if menu_id == "admins":
        return _admins_menu(lang)
    # Default / "settings".
    return _settings_menu(lang)


def settings_entry(lang: str = "en") -> Tuple[str, Rows]:
    """Title + rows for the top-level Settings menu (used by the DM wrapper)."""
    return _settings_menu(lang)


def admins_entry(lang: str = "en") -> Tuple[str, Rows]:
    """Title + rows for the Admins menu (used by the DM wrapper / reply button)."""
    return _admins_menu(lang)


def channels_entry(lang: str = "en") -> Tuple[str, Rows]:
    """Title + rows for the Channels menu (used by the /channelsmenu reply button)."""
    return _channels_menu(lang)


def _fallback(lang: str = "en") -> CallbackResult:
    return CallbackResult(
        t("menu_expired", lang),
        None,
        t("alert_expired", lang),
    )


def handle_callback(
    data: str,
    *,
    lang: str = "en",
    uid=None,
    start_ts: Optional[float] = None,
    query_queue=None,
    pyro=None,
) -> CallbackResult:
    """Pure dispatcher for an inline-button press. Never raises."""
    parts = (data or "").split(":")
    head = parts[0] if parts else ""

    if head == "nav":
        target = parts[1] if len(parts) > 1 else "settings"
        if target == "close":
            return CallbackResult(
                t("menu_closed", lang), None, t("alert_closed", lang)
            )
        title, rows = build_menu(target, lang)
        return CallbackResult(title, rows)

    if head == "setlang" and len(parts) >= 2 and uid is not None:
        new_lang = parts[1]
        ok, _ = admin_prefs.set_lang(uid, new_lang)
        if not ok:
            new_lang = lang
        title, rows = _settings_menu(new_lang)
        return CallbackResult(title, rows, t("alert_lang", new_lang))

    if head == "set" and len(parts) >= 3:
        kind = parts[1]
        value = ":".join(parts[2:])  # defensive: values never contain ':'
        setters = {
            "model": admin_commands._cmd_setmodel,
            "temp": admin_commands._cmd_settemp,
            "tokens": admin_commands._cmd_setmaxtokens,
            "log": admin_commands._cmd_setloglevel,
        }
        fn = setters.get(kind)
        if fn is None:
            return _fallback(lang)
        text = fn([value], lang)
        alert = t("alert_saved", lang) if text.startswith("✅") else t("alert_error", lang)
        return CallbackResult(text, [_back_to_settings(lang)], alert)

    if head == "rmch" and len(parts) >= 2:
        title, rows = _rmch_confirm(parts[1], lang)
        return CallbackResult(title, rows)

    if head == "rmchok" and len(parts) >= 2:
        text = admin_commands._cmd_removechannel([parts[1]], lang)
        alert = t("alert_removed", lang) if text.startswith("✅") else t("alert_error", lang)
        return CallbackResult(text, [_back_to_settings(lang)], alert)

    if head == "rmadmin" and len(parts) >= 2:
        title, rows = _admin_confirm(parts[1], lang)
        return CallbackResult(title, rows)

    if head == "rmadminok" and len(parts) >= 2:
        ok, msg = admin_store.remove_admin(parts[1])
        text = ("✅ " if ok else "❌ ") + html.escape(msg)
        alert = t("alert_removed", lang) if ok else t("alert_error", lang)
        return CallbackResult(text, [_back_to_settings(lang)], alert)

    return _fallback(lang)


# --- Pyrogram glue (the only client-aware part) -------------------------------


def to_inline_markup(rows: Rows):
    """Convert a rows spec into a Pyrogram ``InlineKeyboardMarkup``."""
    from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(label, callback_data=cd) for label, cd in row]
            for row in rows
        ]
    )


def to_reply_markup(spec: List[List[str]]):
    """Convert a label-row spec into a persistent ``ReplyKeyboardMarkup``."""
    from pyrogram.types import KeyboardButton, ReplyKeyboardMarkup

    return ReplyKeyboardMarkup(
        [[KeyboardButton(label) for label in row] for row in spec],
        resize_keyboard=True,
    )


def build_add_admin_keyboard(lang: str = "en"):
    """Temporary reply keyboard whose first button opens Telegram's user picker.

    Selecting a user makes Telegram send a ``users_shared`` service message
    (handled in ``admin_commands``); the second button cancels and restores the
    main menu (its label maps to ``/menu`` via the reverse label map).
    """
    from pyrogram.types import (
        KeyboardButton,
        KeyboardButtonRequestUsers,
        ReplyKeyboardMarkup,
    )

    return ReplyKeyboardMarkup(
        [
            [
                KeyboardButton(
                    t("btn_pick_user", lang),
                    request_users=KeyboardButtonRequestUsers(
                        button_id=ADD_ADMIN_BUTTON_ID,
                        max_quantity=1,
                        request_name=True,
                        request_username=True,
                    ),
                )
            ],
            [KeyboardButton(t("btn_back_to_menu", lang))],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def register_callback_handler(pyro, *, start_ts=None, query_queue=None):
    """Register the admin-gated ``on_callback_query`` handler on ``pyro``."""
    from pyrogram.errors import MessageNotModified

    @pyro.on_callback_query(admin_commands._admin_filter())
    async def _on_callback(client, cq):  # noqa: ANN001
        uid = getattr(getattr(cq, "from_user", None), "id", None)
        lang = admin_prefs.get_lang(uid) if uid is not None else admin_i18n.DEFAULT_LANG
        data = cq.data or ""

        # The user picker needs a *reply* keyboard, which can't be attached to an
        # edited inline message — so send a fresh message instead of editing.
        if data == "admin:add":
            try:
                await cq.answer()
            except Exception:
                pass
            try:
                await cq.message.reply_text(
                    t("add_admin_prompt", lang),
                    parse_mode=enums.ParseMode.HTML,
                    reply_markup=build_add_admin_keyboard(lang),
                )
            except Exception:
                log.exception("failed to start add-admin flow")
            return

        # Start the add-channel wizard: stash pending state and send the first
        # prompt as a fresh message carrying a Cancel button.
        if data == "addch:start":
            try:
                await cq.answer()
            except Exception:
                pass
            admin_wizard.start(uid)
            try:
                await cq.message.reply_text(
                    t("wiz_prompt_name", lang),
                    parse_mode=enums.ParseMode.HTML,
                    reply_markup=to_inline_markup(
                        [[(t("btn_cancel", lang), "addch:cancel")]]
                    ),
                )
            except Exception:
                log.exception("failed to start add-channel wizard")
            return

        if data == "addch:cancel":
            admin_wizard.cancel(uid)
            try:
                await cq.answer(t("alert_closed", lang))
            except Exception:
                pass
            try:
                await cq.edit_message_text(
                    admin_commands._truncate(t("wiz_cancelled", lang)),
                    parse_mode=enums.ParseMode.HTML,
                )
            except MessageNotModified:
                pass
            except Exception:
                log.exception("failed to cancel add-channel wizard")
            return

        try:
            result = handle_callback(
                data,
                lang=lang,
                uid=uid,
                start_ts=start_ts,
                query_queue=query_queue,
                pyro=pyro,
            )
        except Exception:  # never let a button press crash the handler
            log.exception("admin callback failed")
            try:
                await cq.answer(t("alert_error", lang))
            except Exception:
                pass
            return
        try:
            await cq.answer(result.alert or "")
        except Exception:
            log.exception("callback answer failed")
        markup = to_inline_markup(result.rows) if result.rows else None
        try:
            await cq.edit_message_text(
                admin_commands._truncate(result.text),
                parse_mode=enums.ParseMode.HTML,
                reply_markup=markup,
            )
        except MessageNotModified:
            pass  # re-tapping a nav button that shows identical content
        except Exception:
            log.exception("callback edit failed")

        # An inline edit can't re-skin the *persistent* reply keyboard, so after a
        # language switch push a fresh message carrying the new-language keyboard.
        if data.startswith("setlang:"):
            new_lang = admin_prefs.get_lang(uid) if uid is not None else lang
            try:
                await cq.message.reply_text(
                    t("lang_switched", new_lang),
                    parse_mode=enums.ParseMode.HTML,
                    reply_markup=to_reply_markup(build_reply_keyboard(new_lang)),
                )
            except Exception:
                log.exception("failed to refresh reply keyboard after setlang")

    return _on_callback
