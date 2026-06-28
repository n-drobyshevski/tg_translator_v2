"""Button-driven admin surface layered on top of the typed DM commands.

Non-technical operators get two Telegram keyboards instead of having to
remember slash commands:

* a **persistent reply keyboard** (always-visible buttons above the text box)
  whose taps send a label such as ``📊 Status`` — :func:`resolve_button_label`
  maps that label back to the existing ``/status`` command, and
* an **inline keyboard** for the Settings tree (model / temperature / max-tokens
  / log level / remove-channel), navigated in place via ``on_callback_query``.

Every action ultimately routes back through the ``_cmd_*`` helpers in
:mod:`translator.services.admin_commands` — no business logic is duplicated.
The pure menu logic (:func:`resolve_button_label`, :func:`handle_callback`,
:func:`build_menu`) is deliberately free of Pyrogram plumbing so it can be
unit-tested with plain strings; the Pyrogram-aware glue lives at the bottom.
"""

from __future__ import annotations

import html
import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

from pyrogram import enums

from translator.config import CONFIG
from translator.services import admin_commands, admin_store

log = logging.getLogger("ADMIN.MENU")

# A button row is a list of (label, callback_data) pairs; a menu is a list of
# rows. Reply-keyboard specs are just lists of rows of plain labels.
Row = List[Tuple[str, str]]
Rows = List[Row]


# --- Persistent reply keyboard ------------------------------------------------

# Reply-keyboard taps arrive as ordinary text messages, so map each label back
# to the command (or the menu-bearing pseudo-command) it stands for.
BUTTON_COMMANDS = {
    "📊 Status": "/status",
    "📈 Stats": "/stats",
    "📡 Channels": "/channels",
    # Opens the inline Admins menu (add/remove buttons), not the text list — this
    # menu-bearing pseudo-command is intercepted in admin_commands._dispatch.
    "👤 Admins": "/adminsmenu",
    "📝 Prompt": "/prompt",
    "🔄 Reload": "/reload",
    "❓ Help": "/help",
    "🛠️ Settings": "/settings",
    # Shown on the temporary "add admin" keyboard; resolves to /menu so tapping
    # it cancels the add-flow and restores the main keyboard.
    "🔙 Back to menu": "/menu",
}

MENU_GREETING = (
    "<b>📋 Relay bot menu</b>\n"
    "Tap a button below, or open 🛠️ Settings to view and change configuration.\n"
    "Typed commands still work — tap ❓ Help to see them."
)


def resolve_button_label(text: Optional[str]) -> Optional[str]:
    """Map a persistent-keyboard label to its command, else ``None``."""
    if not text:
        return None
    return BUTTON_COMMANDS.get(text.strip())


def build_reply_keyboard() -> List[List[str]]:
    """Spec for the persistent reply keyboard (rows of plain labels)."""
    return [
        ["📊 Status", "📈 Stats"],
        ["📡 Channels", "👤 Admins"],
        ["📝 Prompt", "🔄 Reload"],
        ["❓ Help", "🛠️ Settings"],
    ]


# --- Inline settings menu tree ------------------------------------------------

MODEL_PRESETS = [
    ("Haiku 4.5 (default)", "claude-haiku-4-5"),
    ("Sonnet 4.6", "claude-sonnet-4-6"),
    ("Opus 4.8", "claude-opus-4-8"),
]
TEMP_PRESETS = ["0", "0.3", "0.5", "0.7", "1.0"]
TOKEN_PRESETS = ["1500", "2000", "4000", "8192"]

_BACK_TO_SETTINGS: Row = [("◀️ Back", "nav:settings")]

# Identifier echoed back in ``users_shared.button_id`` for the add-admin picker.
ADD_ADMIN_BUTTON_ID = 1
ADD_ADMIN_PROMPT = (
    "<b>➕ Add admin</b>\n"
    "Tap “👤 Pick a user…” to choose someone from your chats — I'll capture their "
    "id and name automatically.\n"
    "Or type <code>/addadmin &lt;user_id&gt;</code> or "
    "<code>/addadmin @username</code> [label]."
)


@dataclass
class CallbackResult:
    """What a button press should do: new message text + optional keyboard."""

    text: str
    rows: Optional[Rows] = None
    alert: Optional[str] = None  # short toast shown via callback_query.answer


def _settings_menu() -> Tuple[str, Rows]:
    title = (
        "<b>⚙️ Settings</b>\n\n"
        f"{admin_commands._config_summary()}\n\n"
        "Pick a setting to change."
    )
    rows: Rows = [
        [("🤖 Set Model", "nav:model")],
        [("🌡️ Temperature", "nav:temp"), ("🔢 Max Tokens", "nav:tokens")],
        [("🪵 Log Level", "nav:log")],
        [("🗑️ Remove Channel", "nav:rmch")],
        [("👤 Admins", "nav:admins")],
        [("✖️ Close", "nav:close")],
    ]
    return title, rows


def _model_menu() -> Tuple[str, Rows]:
    title = (
        "<b>🤖 Model</b>\n"
        f"Current: {CONFIG.ANTHROPIC_MODEL}\n"
        "Pick a preset, or type <code>/setmodel &lt;id&gt;</code> for any other."
    )
    rows: Rows = [[(label, f"set:model:{value}")] for label, value in MODEL_PRESETS]
    rows.append(_BACK_TO_SETTINGS)
    return title, rows


def _temp_menu() -> Tuple[str, Rows]:
    title = (
        "<b>🌡️ Temperature</b>\n"
        f"Current: {CONFIG.ANTHROPIC_TEMPERATURE}\nPick a value (0 = literal)."
    )
    rows: Rows = [[(v, f"set:temp:{v}") for v in TEMP_PRESETS], list(_BACK_TO_SETTINGS)]
    return title, rows


def _tokens_menu() -> Tuple[str, Rows]:
    title = (
        "<b>🔢 Max Tokens</b>\n"
        f"Current: {CONFIG.ANTHROPIC_MAX_TOKENS}\nPick a value."
    )
    rows: Rows = [
        [(v, f"set:tokens:{v}") for v in TOKEN_PRESETS],
        list(_BACK_TO_SETTINGS),
    ]
    return title, rows


def _log_menu() -> Tuple[str, Rows]:
    title = (
        "<b>🪵 Log Level</b>\n"
        f"Current: {CONFIG.LOG_LEVEL}\nPick a level."
    )
    levels = sorted(admin_commands._VALID_LOG_LEVELS)
    rows: Rows = [[(lvl, f"set:log:{lvl}")] for lvl in levels]
    rows.append(_BACK_TO_SETTINGS)
    return title, rows


def _rmch_menu() -> Tuple[str, Rows]:
    title = "<b>🗑️ Remove Channel</b>\nPick a channel to stop relaying."
    removable = [
        n
        for n in admin_commands._logical_names()
        if n not in admin_commands._PROTECTED_CHANNELS
    ]
    if removable:
        rows: Rows = [[(name, f"rmch:{name}")] for name in removable]
    else:
        rows = [[("(no removable channels)", "nav:settings")]]
    rows.append(_BACK_TO_SETTINGS)
    return title, rows


def _rmch_confirm(name: str) -> Tuple[str, Rows]:
    title = (
        f"<b>🗑️ Remove '{name}'?</b>\nThis stops the relay for that pair."
    )
    rows: Rows = [
        [("✅ Yes, remove", f"rmchok:{name}"), ("◀️ No, back", "nav:rmch")]
    ]
    return title, rows


def _admins_menu() -> Tuple[str, Rows]:
    admins = admin_store.list_admins()
    lines = ["<b>👤 Admins</b>"]
    for a in admins:
        if a["label"]:
            lines.append(f"{html.escape(a['label'])} (<code>{a['id']}</code>)")
        elif a["resolved"]:
            lines.append(f"{html.escape(a['resolved'])} (<code>{a['id']}</code>)")
        else:
            lines.append(f"<code>{a['id']}</code>")
    if not admins:
        lines.append("(none)")
    lines += [
        "",
        "Tap an admin to remove. Add via <code>/addadmin &lt;id&gt; [label]</code>.",
    ]
    title = "\n".join(lines)
    rows: Rows = [
        [(f"🗑️ {a['display']}", f"rmadmin:{a['id']}")] for a in admins
    ]
    rows.append([("➕ Add admin", "admin:add")])
    rows.append(list(_BACK_TO_SETTINGS))
    return title, rows


def _admin_confirm(uid: str) -> Tuple[str, Rows]:
    title = (
        f"<b>👤 Remove admin <code>{html.escape(uid)}</code>?</b>\n"
        "They lose DM control and stop receiving alerts."
    )
    rows: Rows = [
        [("✅ Yes, remove", f"rmadminok:{uid}"), ("◀️ No, back", "nav:admins")]
    ]
    return title, rows


def build_menu(menu_id: str) -> Tuple[str, Rows]:
    """Return ``(title_html, rows)`` for a navigation target."""
    if menu_id == "model":
        return _model_menu()
    if menu_id == "temp":
        return _temp_menu()
    if menu_id == "tokens":
        return _tokens_menu()
    if menu_id == "log":
        return _log_menu()
    if menu_id == "rmch":
        return _rmch_menu()
    if menu_id == "admins":
        return _admins_menu()
    # Default / "settings".
    return _settings_menu()


def settings_entry() -> Tuple[str, Rows]:
    """Title + rows for the top-level Settings menu (used by the DM wrapper)."""
    return _settings_menu()


def admins_entry() -> Tuple[str, Rows]:
    """Title + rows for the Admins menu (used by the DM wrapper / reply button)."""
    return _admins_menu()


def _fallback() -> CallbackResult:
    return CallbackResult(
        "This menu expired. Tap 🛠️ Settings or send /menu to reopen.",
        None,
        "Expired",
    )


def handle_callback(
    data: str,
    *,
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
                "✅ Menu closed. Send /menu to reopen.", None, "Closed"
            )
        title, rows = build_menu(target)
        return CallbackResult(title, rows)

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
            return _fallback()
        text = fn([value])
        alert = "Saved" if text.startswith("✅") else "Error"
        return CallbackResult(text, [list(_BACK_TO_SETTINGS)], alert)

    if head == "rmch" and len(parts) >= 2:
        title, rows = _rmch_confirm(parts[1])
        return CallbackResult(title, rows)

    if head == "rmchok" and len(parts) >= 2:
        text = admin_commands._cmd_removechannel([parts[1]])
        alert = "Removed" if text.startswith("✅") else "Error"
        return CallbackResult(text, [list(_BACK_TO_SETTINGS)], alert)

    if head == "rmadmin" and len(parts) >= 2:
        title, rows = _admin_confirm(parts[1])
        return CallbackResult(title, rows)

    if head == "rmadminok" and len(parts) >= 2:
        ok, msg = admin_store.remove_admin(parts[1])
        text = ("✅ " if ok else "❌ ") + html.escape(msg)
        alert = "Removed" if ok else "Error"
        return CallbackResult(text, [list(_BACK_TO_SETTINGS)], alert)

    return _fallback()


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


def build_add_admin_keyboard():
    """Temporary reply keyboard whose first button opens Telegram's user picker.

    Selecting a user makes Telegram send a ``users_shared`` service message
    (handled in ``admin_commands``); the second button cancels and restores the
    main menu (its label maps to ``/menu`` via ``BUTTON_COMMANDS``).
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
                    "👤 Pick a user…",
                    request_users=KeyboardButtonRequestUsers(
                        button_id=ADD_ADMIN_BUTTON_ID,
                        max_quantity=1,
                        request_name=True,
                        request_username=True,
                    ),
                )
            ],
            [KeyboardButton("🔙 Back to menu")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def register_callback_handler(pyro, *, start_ts=None, query_queue=None):
    """Register the admin-gated ``on_callback_query`` handler on ``pyro``."""
    from pyrogram.errors import MessageNotModified

    @pyro.on_callback_query(admin_commands._admin_filter())
    async def _on_callback(client, cq):  # noqa: ANN001
        # The user picker needs a *reply* keyboard, which can't be attached to an
        # edited inline message — so send a fresh message instead of editing.
        if (cq.data or "") == "admin:add":
            try:
                await cq.answer()
            except Exception:
                pass
            try:
                await cq.message.reply_text(
                    ADD_ADMIN_PROMPT,
                    parse_mode=enums.ParseMode.HTML,
                    reply_markup=build_add_admin_keyboard(),
                )
            except Exception:
                log.exception("failed to start add-admin flow")
            return
        try:
            result = handle_callback(
                cq.data or "",
                start_ts=start_ts,
                query_queue=query_queue,
                pyro=pyro,
            )
        except Exception:  # never let a button press crash the handler
            log.exception("admin callback failed")
            try:
                await cq.answer("Error")
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

    return _on_callback
