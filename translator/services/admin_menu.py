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
import inspect
import logging
import os
from dataclasses import dataclass
from typing import List, Optional, Tuple

from pyrogram import enums
from pyrogram import types as pyro_types
from pyrogram.client import Client

from translator.config import CONFIG
from translator.services import (
    admin_commands,
    admin_i18n,
    admin_prefs,
    admin_store,
    admin_wizard,
)
from translator.services.admin_i18n import t
from translator.utils.model_capabilities import supports_effort, supports_sampling_params

log = logging.getLogger("ADMIN.MENU")

# A button row is a list of (label, callback_data) pairs; a menu is a list of
# rows. Reply-keyboard specs are just lists of rows of plain labels.
Row = List[Tuple[str, str]]
Rows = List[Row]

# --- Reserved callback_data heads ---------------------------------------------
#
# Two newer inline-button kinds carry no callback at all, so rather than widen
# the (label, data) pair — which every menu and every test is written against —
# they are encoded as reserved prefixes in the data slot and decoded in
# :func:`to_inline_markup`. Telegram fires no callback query for either, so
# ``handle_callback`` never sees them.
#
#   ``copy:<text>``  → CopyTextButton (Bot API 7.11): copies <text> on tap.
#   ``x:<data>``     → DisabledButton (Bot API 10.2): greyed out, not tappable.
#                      <data> is what the button *would* have done, which is
#                      what the plain fallback below re-enables.
COPY_PREFIX = "copy:"
DISABLED_PREFIX = "x:"

# Destructive confirmations render red (Bot API 9.4 button styles). Keyed by the
# data head so the pure menu layer stays free of presentation concerns.
_DANGER_HEADS = frozenset({"rmchok", "rmadminok"})


# --- Optional newer button kinds ----------------------------------------------
#
# Dependencies on the production host are installed by hand (PythonAnywhere, no
# CI), so the kurigram actually running can lag what requirements.txt pins —
# that is the normal state between deploys, not an edge case. Every button kind
# added after Bot API 7.x is therefore treated as OPTIONAL: probed once here, and
# never referenced on a path that has to work without it.
#
# Two separate things can fail on an older kurigram, so both are checked: the
# type may not exist, *and* the constructor may not accept the keyword that
# carries it — `InlineKeyboardButton` imports fine on 2.2.23 while `style=` is
# still a TypeError there.


def _accepts_arg(func, param: str) -> bool:
    """True if the callable ``func`` takes ``param``."""
    try:
        return param in inspect.signature(func).parameters
    except (TypeError, ValueError):  # unintrospectable (C-implemented) callable
        return False


def _accepts(cls, param: str) -> bool:
    """True if ``cls.__init__`` takes ``param``."""
    return _accepts_arg(cls.__init__, param)


_CopyTextButton = getattr(pyro_types, "CopyTextButton", None)
_DisabledButton = getattr(pyro_types, "DisabledButton", None)
_RequestChat = getattr(pyro_types, "KeyboardButtonRequestChat", None)
_ButtonStyle = getattr(enums, "ButtonStyle", None)

HAS_COPY_BUTTON = _CopyTextButton is not None and _accepts(
    pyro_types.InlineKeyboardButton, "copy_text"
)
HAS_DISABLED_BUTTON = _DisabledButton is not None and _accepts(
    pyro_types.InlineKeyboardButton, "disabled"
)
HAS_BUTTON_STYLE = _ButtonStyle is not None and _accepts(
    pyro_types.InlineKeyboardButton, "style"
)
HAS_CHAT_PICKER = _RequestChat is not None and _accepts(
    pyro_types.KeyboardButton, "request_chat"
)
HAS_KEYBOARD_HINTS = _accepts(
    pyro_types.ReplyKeyboardMarkup, "is_persistent"
) and _accepts(pyro_types.ReplyKeyboardMarkup, "placeholder")

# Bot API 10.3 / Telegram 12.10: buttons *inside* the message body rather than on
# the keyboard strip below it. Needs a send path (`Message.reply_rich`) and an
# edit path (`rich_message=` on edit_message_text) — the menu tree navigates by
# editing one message in place, so without the latter this would be unusable.
HAS_RICH_MESSAGES = (
    hasattr(Client, "send_rich_message")
    and getattr(pyro_types, "InputRichMessage", None) is not None
    and getattr(pyro_types, "RichMessageButton", None) is not None
    and hasattr(pyro_types.Message, "reply_rich")
    and _accepts_arg(pyro_types.CallbackQuery.edit_message_text, "rich_message")
)

# Second gate, read live so it can be flipped with a `/reload` rather than a
# restart. Default OFF on purpose: the rich HTML dialect is validated only by
# Telegram's servers (kurigram passes `html=` straight through), and production
# has been running a kurigram older than the pin. Opt in once, deliberately.
RICH_MENUS_ENV = "ADMIN_RICH_MENUS"


def rich_menus_enabled() -> bool:
    """True when rich-message menus are both supported and switched on."""
    if not HAS_RICH_MESSAGES:
        return False
    return os.getenv(RICH_MENUS_ENV, "").strip().lower() in ("1", "true", "yes", "on")


def capability_summary() -> str:
    """Which optional button kinds this kurigram supports, for the startup log."""
    return " ".join(
        f"{name}={'yes' if ok else 'no'}"
        for name, ok in (
            ("copy", HAS_COPY_BUTTON),
            ("disabled", HAS_DISABLED_BUTTON),
            ("style", HAS_BUTTON_STYLE),
            ("chat_picker", HAS_CHAT_PICKER),
            ("kbd_hints", HAS_KEYBOARD_HINTS),
            ("rich", HAS_RICH_MESSAGES),
            ("rich_enabled", rich_menus_enabled()),
        )
    )


# --- Persistent reply keyboard ------------------------------------------------

# Each reply-keyboard button maps to a command (or a menu-bearing pseudo-command).
# Keyed by i18n string key so the *label* renders in any locale while the command
# it resolves to stays stable.
BUTTON_KEYS = {
    "btn_status": "/status",
    "btn_stats": "/stats",
    "btn_ai": "/aimenu",
    "btn_channels": "/channelsmenu",
    "btn_admins": "/adminsmenu",
    "btn_prompt": "/prompt",
    "btn_reload": "/reload",
    "btn_help": "/help",
    "btn_settings": "/settings",
    # Shown on the temporary "add admin" keyboard; resolves to /menu so tapping
    # it cancels the add-flow and restores the main keyboard.
    "btn_back_to_menu": "/menu",
    # Shown on the temporary channel-picker keyboard. Without this mapping the
    # tapped label would be read as the wizard's next answer instead of a cancel.
    "btn_cancel": "/cancel",
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
    """Spec for the persistent reply keyboard (rows of plain labels).

    🤖 AI Settings is a top-level entry (its own inline menu via /aimenu); the
    prompt template lives inside it (🤖 AI Settings → 📝 Prompt). 📡 Channels and
    👤 Admins are not top-level either — they now live under 🛠️ Settings (their
    labels stay resolvable via BUTTON_KEYS for typed/cached access).

    🔄 Reload is intentionally absent: ``/reload`` has a narrow operator use case
    (it only matters after an out-of-band ``.env`` edit, since the DM writers
    already reload live), so it stays a typed-only command — still resolvable via
    BUTTON_KEYS for typed flows / cached keyboards.

    📈 Stats is likewise absent from the keyboard (the dashboard charts cover the
    same ground), but ``/stats`` stays resolvable via BUTTON_KEYS.
    """
    return [
        [t("btn_status", lang), t("btn_settings", lang)],
        [t("btn_ai", lang), t("btn_help", lang)],
    ]


# --- Inline settings menu tree ------------------------------------------------

# Presets track the real defaults in ``translator/config.py`` — they went stale
# once before, when the default moved to Sonnet 5 but this list still advertised
# "Haiku 4.5 (default)". Which one is active is now derived at render time
# (see ``_preset_rows``) instead of being written into a label.
MODEL_PRESETS = [
    ("Haiku 4.5", "claude-haiku-4-5"),
    ("Sonnet 5", "claude-sonnet-5"),
    ("Opus 5", "claude-opus-5"),
]
TEMP_PRESETS = ["0", "0.3", "0.5", "0.7", "1.0"]
# max_tokens now covers thinking + response together and defaults to 8000, so
# the old 1500/2000/4000/8192 ladder no longer brackets the default at all.
TOKEN_PRESETS = ["4000", "8000", "16000", "32000"]
EFFORT_PRESETS = ["low", "medium", "high"]


def _back_to_settings(lang: str = "en") -> Row:
    return [(t("btn_back", lang), "nav:settings")]


def _back_to_ai(lang: str = "en") -> Row:
    return [(t("btn_back", lang), "nav:ai")]


def _back_to_channels(lang: str = "en") -> Row:
    return [(t("btn_back", lang), "nav:channels")]


# Identifier echoed back in ``users_shared.button_id`` for the add-admin picker.
ADD_ADMIN_BUTTON_ID = 1
# ...and in ``chat_shared.button_id`` for the add-channel picker.
REQUEST_CHANNEL_BUTTON_ID = 2


@dataclass
class CallbackResult:
    """What a button press should do: new message text + optional keyboard."""

    text: str
    rows: Optional[Rows] = None
    alert: Optional[str] = None  # short toast shown via callback_query.answer


def _settings_menu(lang: str = "en") -> Tuple[str, Rows]:
    title = t("settings_title", lang, summary=admin_commands._config_summary(lang))
    rows: Rows = [
        [(t("settings_btn_log", lang), "nav:log")],
        [(t("btn_channels", lang), "nav:channels")],
        [(t("btn_admins", lang), "nav:admins")],
        [(t("btn_language", lang), "nav:lang")],
        [(t("settings_btn_close", lang), "nav:close")],
    ]
    return title, rows


def _preset_rows(presets: List[Tuple[str, str]], kind: str, current) -> Rows:
    """One button per (label, value) preset, the active one rendered as disabled.

    Greying out the current value is the cheapest possible "you are here": the
    operator can see what is live without reading the title, and can't waste a
    round-trip re-selecting it. ``to_inline_markup`` re-enables these if the
    client/server rejects disabled buttons, so nothing becomes unreachable.
    """
    return [
        [
            (
                label,
                (DISABLED_PREFIX if str(current) == str(value) else "")
                + f"set:{kind}:{value}",
            )
        ]
        for label, value in presets
    ]


def _ai_menu(lang: str = "en") -> Tuple[str, Rows]:
    """The dedicated AI Settings submenu: model / temperature / tokens / effort.

    Temperature and effort are mutually exclusive in practice — each request
    surface takes one and rejects the other — so the summary flags whichever one
    the active model ignores rather than showing two knobs that look equal.
    """
    model = str(CONFIG.ANTHROPIC_MODEL)
    inert = t("ai_inert_flag", lang)
    title = t(
        "ai_title",
        lang,
        model=html.escape(model),
        temp=CONFIG.ANTHROPIC_TEMPERATURE,
        temp_flag="" if supports_sampling_params(model) else inert,
        tokens=CONFIG.ANTHROPIC_MAX_TOKENS,
        effort=html.escape(str(CONFIG.ANTHROPIC_EFFORT)),
        effort_flag="" if supports_effort(model) else inert,
    )
    rows: Rows = [
        [(t("settings_btn_model", lang), "nav:model")],
        [
            (t("settings_btn_temp", lang), "nav:temp"),
            (t("settings_btn_tokens", lang), "nav:tokens"),
        ],
        [(t("settings_btn_effort", lang), "nav:effort")],
        [(t("btn_prompt", lang), "nav:prompt")],
        # AI Settings is a top-level menu (peer of Settings), so it closes
        # rather than navigating "back" to a parent.
        [(t("settings_btn_close", lang), "nav:close")],
    ]
    return title, rows


def _prompt_menu(lang: str = "en") -> Tuple[str, Rows]:
    """Read-only view of the current prompt template + how to change it.

    Editing needs multi-line typed input, which inline buttons can't capture, so
    this shows the template (via the shared ``/prompt`` handler) and points at
    ``/setprompt``."""
    title = admin_commands._cmd_prompt(lang) + t("prompt_menu_hint", lang)
    rows: Rows = [_back_to_ai(lang)]
    return title, rows


def _model_menu(lang: str = "en") -> Tuple[str, Rows]:
    model = str(CONFIG.ANTHROPIC_MODEL)
    title = t("model_title", lang, current=html.escape(model))
    rows: Rows = _preset_rows(MODEL_PRESETS, "model", model)
    # The live id is often a value no preset covers (/setmodel takes anything),
    # and it's what an operator needs to paste when reporting or reverting.
    rows.append([(t("btn_copy_model", lang), COPY_PREFIX + model)])
    rows.append(_back_to_ai(lang))
    return title, rows


def _temp_menu(lang: str = "en") -> Tuple[str, Rows]:
    model = str(CONFIG.ANTHROPIC_MODEL)
    title = t("temp_title", lang, current=CONFIG.ANTHROPIC_TEMPERATURE)
    live = supports_sampling_params(model)
    if not live:
        title += t("temp_inert_note", lang, model=html.escape(model))
    # On the modern surface every value is equally ignored, so the whole row is
    # greyed out — showing five tappable presets that change nothing is worse
    # than showing none.
    row: Row = [
        (
            v,
            (DISABLED_PREFIX if not live else "") + f"set:temp:{v}",
        )
        for v in TEMP_PRESETS
    ]
    return title, [row, _back_to_ai(lang)]


def _tokens_menu(lang: str = "en") -> Tuple[str, Rows]:
    current = str(CONFIG.ANTHROPIC_MAX_TOKENS)
    title = t("tokens_title", lang, current=current)
    row: Row = [
        (v, (DISABLED_PREFIX if v == current else "") + f"set:tokens:{v}")
        for v in TOKEN_PRESETS
    ]
    return title, [row, _back_to_ai(lang)]


def _effort_menu(lang: str = "en") -> Tuple[str, Rows]:
    """Thinking effort — the modern surface's replacement for temperature."""
    model = str(CONFIG.ANTHROPIC_MODEL)
    current = str(CONFIG.ANTHROPIC_EFFORT)
    title = t("effort_title", lang, current=html.escape(current))
    live = supports_effort(model)
    if not live:
        title += t("effort_inert_note", lang, model=html.escape(model))
    row: Row = [
        (
            v,
            (DISABLED_PREFIX if (not live or v == current) else "")
            + f"set:effort:{v}",
        )
        for v in EFFORT_PRESETS
    ]
    return title, [row, _back_to_ai(lang)]


def _log_menu(lang: str = "en") -> Tuple[str, Rows]:
    title = t("log_title", lang, current=CONFIG.LOG_LEVEL)
    rows: Rows = [[(t("logs_btn_view", lang), "nav:logsview")]]
    levels = sorted(admin_commands._VALID_LOG_LEVELS)
    rows += [[(lvl, f"set:log:{lvl}")] for lvl in levels]
    rows.append(_back_to_settings(lang))
    return title, rows


def _logs_view(lang: str = "en") -> Tuple[str, Rows]:
    """Show the most recent bot.log tail with refresh / back-to-Logs buttons."""
    title = admin_commands._cmd_logs(lang)
    rows: Rows = [
        [(t("logs_btn_refresh", lang), "nav:logsview")],
        [(t("btn_back", lang), "nav:log")],
    ]
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
    rows: Rows = [[(t("btn_add_channel_pair", lang), "addch:start")]]
    # One copy button per pair, carrying the exact argument list /editchannel
    # wants. Selecting a -100… id out of a <code> block on a phone is the kind of
    # papercut that makes operators avoid the DM surface entirely.
    for name in admin_commands._logical_names():
        src = CONFIG.channels[name]
        dst = CONFIG.channels.get(name + "_en")
        dst_id = dst.channel_id if dst else ""
        rows.append([(f"📋 {name}", f"{COPY_PREFIX}{name} {src.channel_id} {dst_id}")])
    if len(rows) > 1:
        title += t("channels_copy_hint", lang)
    rows.append([(t("settings_btn_rmch", lang), "nav:rmch")])
    rows.append(_back_to_settings(lang))
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
        rows = [[(t("rmch_none", lang), "nav:channels")]]
    rows.append(_back_to_channels(lang))
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
    if menu_id == "ai":
        return _ai_menu(lang)
    if menu_id == "prompt":
        return _prompt_menu(lang)
    if menu_id == "model":
        return _model_menu(lang)
    if menu_id == "temp":
        return _temp_menu(lang)
    if menu_id == "tokens":
        return _tokens_menu(lang)
    if menu_id == "effort":
        return _effort_menu(lang)
    if menu_id == "log":
        return _log_menu(lang)
    if menu_id == "logsview":
        return _logs_view(lang)
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


def ai_entry(lang: str = "en") -> Tuple[str, Rows]:
    """Title + rows for the top-level AI Settings menu (the /aimenu button)."""
    return _ai_menu(lang)


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
            "effort": admin_commands._cmd_seteffort,
            "log": admin_commands._cmd_setloglevel,
        }
        fn = setters.get(kind)
        if fn is None:
            return _fallback(lang)
        text = fn([value], lang)
        alert = t("alert_saved", lang) if text.startswith("✅") else t("alert_error", lang)
        # model/temp/tokens now live under AI Settings; log stays in Settings.
        back = _back_to_settings(lang) if kind == "log" else _back_to_ai(lang)
        return CallbackResult(text, [back], alert)

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


def _to_button(label: str, data: str, *, plain: bool):
    """One (label, data) pair → an ``InlineKeyboardButton``, or None if dropped.

    Two independent reasons to fall back, both landing on the same branches:
    ``plain`` for a Telegram that refuses a button kind, and the ``HAS_*`` flags
    for a kurigram that does not have it. Nothing outside those guards touches an
    optional type or keyword — which is the bug this function shipped with, where
    the ``plain`` retry re-ran the same unconditional import and raised the
    *identical* ImportError it was meant to catch.
    """
    InlineKeyboardButton = pyro_types.InlineKeyboardButton

    if data.startswith(COPY_PREFIX):
        if plain or not HAS_COPY_BUTTON:
            return None  # "copy to clipboard" has no plain equivalent
        return InlineKeyboardButton(
            label, copy_text=_CopyTextButton(text=data[len(COPY_PREFIX) :])
        )

    if data.startswith(DISABLED_PREFIX):
        # `x:` carries the action the button would have performed, so degrading
        # re-enables it rather than making it unreachable.
        inner = data[len(DISABLED_PREFIX) :]
        if plain or not HAS_DISABLED_BUTTON:
            return InlineKeyboardButton(label, callback_data=inner)
        return InlineKeyboardButton(label, disabled=_DisabledButton())

    # Omitted rather than passed as DEFAULT: `style=` itself is unknown to older
    # constructors, and the parameter default is DEFAULT anyway.
    extra = {}
    if not plain and HAS_BUTTON_STYLE and data.split(":", 1)[0] in _DANGER_HEADS:
        extra["style"] = _ButtonStyle.DANGER
    return InlineKeyboardButton(label, callback_data=data, **extra)


def to_inline_markup(rows: Rows, *, plain: bool = False):
    """Convert a rows spec into a Pyrogram ``InlineKeyboardMarkup``.

    ``plain=True`` strips the Bot API 9.4/10.2 chrome (styles, disabled and copy
    buttons) and keeps only plain callback buttons. It is the retry shape used by
    :func:`send_with_markup` when the styled markup is refused. A kurigram that
    lacks a button kind outright is handled a layer down, in :func:`_to_button`,
    so this stays the same shape on every version.
    """
    keyboard = []
    for row in rows:
        buttons = [
            b
            for b in (_to_button(label, cd, plain=plain) for label, cd in row)
            if b is not None
        ]
        if buttons:  # a copy-only row disappears entirely in plain mode
            keyboard.append(buttons)
    return pyro_types.InlineKeyboardMarkup(keyboard)


def rows_to_rich_html(title_html: str, rows: Rows) -> Optional[str]:
    """Render a menu as rich-message HTML, or None if it can't be expressed.

    Buttons become ``<tg-button-row>`` blocks appended to the title HTML the
    menus already build — the rich dialect accepts the same inline tags the
    titles use (``b i u s code a tg-spoiler`` plus ``p pre blockquote``), so the
    titles need no second rendering path.

    Returns **None** when any button is a copy or disabled button. Only
    ``type="callback_data"`` is a confirmed spelling in this dialect; rather than
    guess an attribute name for the others, those menus skip the rich tier and
    render exactly as they do today. Menus are all-or-nothing here so a single
    unsupported button can never silently vanish from a row.
    """
    parts = [title_html]
    for row in rows:
        buttons = []
        for label, data in row:
            if data.startswith((COPY_PREFIX, DISABLED_PREFIX)):
                return None
            # Both go into HTML *attributes* or element text, and labels are
            # interpolated from channel names and admin labels, so neither is
            # trusted: escape both.
            buttons.append(
                f'<tg-button type="callback_data" data="{html.escape(data)}">'
                f"{html.escape(label)}</tg-button>"
            )
        if buttons:
            parts.append(f"<tg-button-row>{''.join(buttons)}</tg-button-row>")
    return "".join(parts)


async def send_with_markup(send, text: str, rows: Rows, *, send_rich=None, **kwargs):
    """``await send(text, reply_markup=…)``, degrading the markup, not the message.

    Three tiers: full chrome → plain callback buttons → **no markup at all**. The
    last one is the point. An admin surface exists to report state, so delivering
    the text without its buttons beats delivering nothing — and "the operator saw
    nothing" is exactly how the missing-``CopyTextButton`` bug presented.

    Markup is built outside the send so a construction failure (a kurigram that
    can't express the button) is logged separately from a Telegram rejection.
    ``MessageNotModified`` is a real outcome — identical content — not a markup
    problem, so it is re-raised untouched from any tier.

    ``send_rich`` is an optional separate callable taking an ``InputRichMessage``.
    It has to be separate rather than another kwarg on ``send``: the first send of
    a menu goes through ``Message.reply_text``, which does **not** accept
    ``rich_message`` — only ``reply_rich`` and the edit methods do. When it is
    given and rich menus are switched on, it becomes the top tier; a rejection
    there (the dialect is validated only by Telegram) falls through to the
    keyboard tiers below, which is what makes an unverifiable dialect safe.
    """
    from pyrogram.errors import MessageNotModified

    if send_rich is not None and rich_menus_enabled():
        rich_html = rows_to_rich_html(text, rows)
        if rich_html is not None:
            try:
                return await send_rich(pyro_types.InputRichMessage(html=rich_html))
            except MessageNotModified:
                raise
            except Exception:
                log.warning(
                    "send refused rich markup; falling back to a keyboard",
                    exc_info=True,
                )

    for plain in (False, True):
        shape = "plain" if plain else "styled"
        try:
            markup = to_inline_markup(rows, plain=plain)
        except Exception:
            log.warning("could not build %s markup", shape, exc_info=True)
            continue
        try:
            return await send(text, reply_markup=markup, **kwargs)
        except MessageNotModified:
            raise
        except Exception:
            log.warning("send refused %s markup", shape, exc_info=True)
    log.warning("falling back to a message with no buttons")
    return await send(text, reply_markup=None, **kwargs)


def to_reply_markup(spec: List[List[str]], lang: str = "en"):
    """Convert a label-row spec into a persistent ``ReplyKeyboardMarkup``."""
    extra = {}
    if HAS_KEYBOARD_HINTS:
        # Keep the menu open instead of collapsing to the "⌨" icon after a tap —
        # the admin surface is a control panel, not a one-shot prompt.
        extra["is_persistent"] = True
        extra["placeholder"] = t("kbd_placeholder", lang)
    return pyro_types.ReplyKeyboardMarkup(
        [[pyro_types.KeyboardButton(label) for label in row] for row in spec],
        resize_keyboard=True,
        **extra,
    )


def build_channel_picker_keyboard(lang: str = "en"):
    """Temporary reply keyboard whose first button opens Telegram's chat picker.

    ``chat_is_channel`` + ``bot_is_member`` mean Telegram only offers channels the
    bot can actually read, so the "add a channel the bot was never added to"
    mistake — which used to surface as a warning in the /addchannel reply and
    then as silence at runtime — can no longer be made.

    Returns ``None`` on a kurigram without the chat picker. The caller then sends
    no keyboard and suppresses the pick hint, leaving the wizard on typed ids —
    which is how it always worked and still does.
    """
    if not HAS_CHAT_PICKER:
        return None

    return pyro_types.ReplyKeyboardMarkup(
        [
            [
                pyro_types.KeyboardButton(
                    t("btn_pick_channel", lang),
                    request_chat=_RequestChat(
                        button_id=REQUEST_CHANNEL_BUTTON_ID,
                        chat_is_channel=True,
                        bot_is_member=True,
                        request_title=True,
                        request_username=True,
                    ),
                )
            ],
            [pyro_types.KeyboardButton(t("btn_cancel", lang))],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
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

    return ReplyKeyboardMarkup(  # request_users predates the pin; no probe needed
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
        async def _edit(text, **kw):
            return await cq.edit_message_text(
                text, parse_mode=enums.ParseMode.HTML, **kw
            )

        async def _edit_rich(rich):
            # `text` stays positional (it is required); `rich_message` supersedes
            # it, and parse_mode is omitted — the rich dialect carries its own.
            return await cq.edit_message_text(
                admin_commands._truncate(result.text), rich_message=rich
            )

        try:
            if result.rows:
                await send_with_markup(
                    _edit,
                    admin_commands._truncate(result.text),
                    result.rows,
                    send_rich=_edit_rich if HAS_RICH_MESSAGES else None,
                )
            else:
                await _edit(admin_commands._truncate(result.text), reply_markup=None)
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
                    reply_markup=to_reply_markup(build_reply_keyboard(new_lang), new_lang),
                )
            except Exception:
                log.exception("failed to refresh reply keyboard after setlang")
            # The "/" autocomplete is published per chat in a fixed language, so
            # it would otherwise stay in the old one until the next restart.
            if uid is not None:
                await admin_commands.publish_commands_for(pyro, uid)

    return _on_callback
