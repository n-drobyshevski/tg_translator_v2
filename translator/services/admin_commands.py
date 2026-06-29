"""Admin control of the relay bot from a private Telegram DM.

The bot's Pyrogram client is a *bot* account, so it already receives private
messages. This module registers a single ``filters.private`` handler, gated to
``CONFIG.ADMIN_CHAT_IDS``, that exposes a small command surface to query status
and change a whitelist of operational settings live.

Writable settings are persisted to the shared root ``.env`` via
``env_store.set_env_var`` and applied immediately with ``CONFIG.reload()`` —
``translate_html`` reads model/temp/max-tokens fresh per call, the source-channel
filter reads channels live, and ``/setprompt`` calls ``reload_prompt_template``.
No secrets are editable from the DM.

The dispatch entry point ``handle_command`` is intentionally free of Pyrogram
plumbing so it can be unit-tested with a fake message object.
"""

from __future__ import annotations

import html
import logging
import re
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from pyrogram import enums, filters

from translator.config import CONFIG, PROMPT_TEMPLATE_PATH
from translator.services import (
    admin_i18n,
    admin_prefs,
    admin_store,
    admin_wizard,
    env_store,
)
from translator.services.admin_i18n import t
from translator.utils.error_format import humanize_text
from translator.utils.prompt_validation import validate_prompt
from translator.utils.translation_utils import reload_prompt_template

log = logging.getLogger("ADMIN")

_NAME_RE = re.compile(r"[a-z0-9_]+")
# Logical channels backed by independently-required env vars: refuse to remove
# them from a DM (e.g. TEST_CHANNEL is _require()'d by Config regardless of
# LOGICAL_CHANNELS, so unsetting it would break reload()).
_PROTECTED_CHANNELS = {"test"}
_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}

_REPLY_LIMIT = 4000  # stay under Telegram's 4096 hard cap


def _truncate(text: str, limit: int = _REPLY_LIMIT) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _lang_of(msg) -> str:
    """Resolve the per-admin menu language for an incoming message.

    The unit-test ``Msg`` has no ``from_user``, so this returns the default
    (English) for every existing test, keeping their exact-substring assertions.
    """
    uid = getattr(getattr(msg, "from_user", None), "id", None)
    return admin_prefs.get_lang(uid) if uid is not None else admin_i18n.DEFAULT_LANG


def _logical_names() -> List[str]:
    """Current source-side logical channel names (what LOGICAL_CHANNELS holds)."""
    return [n for n, i in CONFIG.channels.items() if i.channel_type == "source"]


def _persist_and_reload(key: str, value: str) -> None:
    env_store.set_env_var(key, value)
    CONFIG.reload()


def _fmt_uptime(start_ts: Optional[float]) -> str:
    if start_ts is None:
        return "unknown"
    secs = int(time.monotonic() - start_ts)
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m}m {s}s"


def _cmd_help(lang: str = "en") -> str:
    return t("help_text", lang)


def _recent_events(lang: str = "en", lookback_days: int = 7, limit: int = 6) -> str:
    """The latest relay events (success or failure) as a '/status' section.

    Replaces the old split successes/failures blocks: operators usually just want
    a quick "what happened last" feed where each line carries its own ✅/❌ status.
    Pull-based; no push alerts. Returns a leading-blank-line block, or "" if the
    event store can't be read — /status must never break on a DB hiccup.
    """
    try:
        from translator.db import events_dao

        cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()
        msgs = events_dao.load_messages(since_iso=cutoff)
    except Exception:  # pragma: no cover - defensive
        return ""
    if not msgs:
        return "\n\n" + t("status_events_none", lang)
    lines = [t("status_events_header", lang, count=len(msgs))]
    for m in reversed(msgs[-limit:]):  # newest first (load_messages is oldest-first)
        ts = (m.get("timestamp") or "")[5:16].replace("T", " ")  # MM-DD HH:MM (UTC)
        chan = html.escape(str(m.get("source_channel_name") or "?"))
        if m.get("posting_success"):
            media = html.escape(str(m.get("media_type") or "text"))
            lines.append(t("status_event_ok", lang, time=ts, channel=chan, media=media))
        else:
            # humanize_text cleans up legacy events whose exception_message is a raw
            # SDK dump; it is idempotent on already-humanized (new) events.
            reason = html.escape(humanize_text(str(m.get("exception_message") or ""))[:90])
            lines.append(t("status_event_fail", lang, time=ts, channel=chan, reason=reason))
    return "\n\n" + "\n".join(lines)


def _cmd_status(start_ts, query_queue, pyro, lang: str = "en") -> str:
    connected = getattr(pyro, "is_connected", None)
    qsize = query_queue.qsize() if query_queue is not None else "?"
    sources = CONFIG.get_source_channel_ids()
    status = t(
        "status",
        lang,
        uptime=_fmt_uptime(start_ts),
        connected=connected,
        sources=len(sources),
        queue=qsize,
        model=html.escape(str(CONFIG.ANTHROPIC_MODEL)),
    )
    return status + _recent_events(lang)


def _cmd_stats(args: List[str], lang: str = "en") -> str:
    days = 7
    if args:
        try:
            days = int(args[0])
        except ValueError:
            return t("stats_usage", lang)
        if not 1 <= days <= 30:
            return t("stats_days_range", lang)
    try:
        from translator.db import events_dao

        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        messages = events_dao.load_messages(since_iso=cutoff)
    except Exception as exc:  # pragma: no cover - defensive
        return t("stats_unavailable", lang, err=html.escape(str(exc)))

    total = len(messages)
    failures = sum(1 for m in messages if not m.get("posting_success"))
    by_channel = Counter(m.get("source_channel_name") or "?" for m in messages)
    lines = [t("stats_header", lang, days=days, total=total, failures=failures)]
    if by_channel:
        lines += [
            f"{html.escape(str(name))}: {count}"
            for name, count in by_channel.most_common()
        ]
    else:
        lines.append(t("common_none", lang))
    return "\n".join(lines)


def _cmd_cost(args: List[str], lang: str = "en") -> str:
    """Cost / billing report (typed-command parity with the menu Cost view)."""
    from translator.services import cost_report

    return cost_report.render(lang)


def _config_summary(lang: str = "en") -> str:
    """Current non-secret settings as value lines (no header).

    Rendered inside the Settings menu (see :mod:`translator.services.admin_menu`),
    which supplies its own ``⚙️ Settings`` title. Labels mirror the submenu wording.
    """
    d = CONFIG.as_dict()
    return t(
        "cfg_summary",
        lang,
        model=html.escape(str(d["ANTHROPIC_MODEL"])),
        temp=d["ANTHROPIC_TEMPERATURE"],
        tokens=d["ANTHROPIC_MAX_TOKENS"],
        log=html.escape(str(d["LOG_LEVEL"])),
        admins=d["ADMIN_CHAT_IDS"],
        channels=html.escape(", ".join(d["LOGICAL_CHANNELS"])),
    )


def _cmd_channels(lang: str = "en") -> str:
    lines = [t("channels_title", lang)]
    for name in _logical_names():
        src = CONFIG.channels[name]
        dst = CONFIG.channels.get(name + "_en")
        dst_id = dst.channel_id if dst else "—"
        lines.append(
            t("channels_line", lang, name=html.escape(name), src=src.channel_id, dst=dst_id)
        )
    if len(lines) == 1:
        lines.append(t("common_none", lang))
    return "\n".join(lines)


def _cmd_prompt(lang: str = "en") -> str:
    if not PROMPT_TEMPLATE_PATH.exists():
        return t("prompt_none", lang)
    text = PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")
    return t("prompt_body", lang, body=html.escape(_truncate(text, 3500)))


def _cmd_setmodel(args: List[str], lang: str = "en") -> str:
    if len(args) != 1 or not args[0].strip():
        return t("setmodel_usage", lang)
    model = args[0].strip()
    _persist_and_reload("ANTHROPIC_MODEL", model)
    return t("setmodel_ok", lang, model=html.escape(model))


def _cmd_settemp(args: List[str], lang: str = "en") -> str:
    if len(args) != 1:
        return t("settemp_usage", lang)
    try:
        val = float(args[0])
    except ValueError:
        return t("settemp_nan", lang)
    if not 0.0 <= val <= 1.0:
        return t("settemp_range", lang)
    _persist_and_reload("ANTHROPIC_TEMPERATURE", str(val))
    return t("settemp_ok", lang, val=val)


def _cmd_setmaxtokens(args: List[str], lang: str = "en") -> str:
    if len(args) != 1:
        return t("settokens_usage", lang)
    try:
        val = int(args[0])
    except ValueError:
        return t("settokens_nan", lang)
    if not 1 <= val <= 8192:
        return t("settokens_range", lang)
    _persist_and_reload("ANTHROPIC_MAX_TOKENS", str(val))
    return t("settokens_ok", lang, val=val)


def _cmd_setloglevel(args: List[str], lang: str = "en") -> str:
    if len(args) != 1:
        return t("setlog_usage", lang)
    level_name = args[0].strip().upper()
    if level_name not in _VALID_LOG_LEVELS:
        return t("setlog_invalid", lang, levels=", ".join(sorted(_VALID_LOG_LEVELS)))
    _persist_and_reload("LOG_LEVEL", level_name)
    # Apply to the running process too.
    level = getattr(logging, level_name)
    root = logging.getLogger()
    root.setLevel(level)
    for h in root.handlers:
        h.setLevel(level)
    return t("setlog_ok", lang, level=level_name)


def _cmd_setprompt(msg, lang: str = "en") -> str:
    new_prompt = None
    reply = getattr(msg, "reply_to_message", None)
    if reply is not None and getattr(reply, "text", None):
        new_prompt = reply.text
    elif msg.text and "\n" in msg.text:
        new_prompt = msg.text.split("\n", 1)[1]
    if new_prompt is None:
        return t("setprompt_usage", lang)
    err = validate_prompt(new_prompt)
    if err:
        return t("setprompt_invalid", lang, err=html.escape(err))
    # One-step rollback, mirroring the Flask admin app.
    if PROMPT_TEMPLATE_PATH.exists():
        backup = PROMPT_TEMPLATE_PATH.with_suffix(PROMPT_TEMPLATE_PATH.suffix + ".bak")
        backup.write_text(
            PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8"), encoding="utf-8"
        )
    PROMPT_TEMPLATE_PATH.write_text(new_prompt, encoding="utf-8")
    reload_prompt_template()
    return t("setprompt_ok", lang)


def _reload_or_error(action: str, lang: str = "en") -> Optional[str]:
    """Run CONFIG.reload(); return an error string on failure, else None."""
    try:
        CONFIG.reload()
        return None
    except Exception as exc:
        return t("reload_failed", lang, action=action, err=html.escape(str(exc)))


def _cmd_addchannel(args: List[str], lang: str = "en") -> str:
    if len(args) < 3:
        return t("addch_usage", lang)
    name = args[0].strip().lower()
    if not _NAME_RE.fullmatch(name):
        return t("addch_bad_name", lang)
    if name in _logical_names():
        return t("addch_dup", lang, name=html.escape(name))
    try:
        src_id = int(args[1])
        dst_id = int(args[2])
    except ValueError:
        return t("addch_bad_int", lang)

    up = name.upper()
    # Write leaf vars first; append the name to LOGICAL_CHANNELS LAST so a
    # half-written pair can never make reload() raise.
    env_store.set_env_var(f"{up}_CHANNEL", str(src_id))
    env_store.set_env_var(f"{up}_EN_CHANNEL_ID", str(dst_id))
    if len(args) >= 4:
        env_store.set_env_var(f"{up}_CHANNEL_NAME", args[3])
    if len(args) >= 5:
        env_store.set_env_var(f"{up}_EN_CHANNEL_NAME", args[4])
    new_names = _logical_names() + [name]
    env_store.set_env_var("LOGICAL_CHANNELS", ",".join(new_names))

    err = _reload_or_error("add", lang)
    if err:
        return err
    return t("addch_ok", lang, name=html.escape(name), src=src_id, dst=dst_id)


def _cmd_editchannel(args: List[str], lang: str = "en") -> str:
    if len(args) != 3:
        return t("editch_usage", lang)
    name = args[0].strip().lower()
    if name not in _logical_names():
        return t("editch_unknown", lang, name=html.escape(name))
    try:
        src_id = int(args[1])
        dst_id = int(args[2])
    except ValueError:
        return t("addch_bad_int", lang)
    up = name.upper()
    env_store.set_env_var(f"{up}_CHANNEL", str(src_id))
    env_store.set_env_var(f"{up}_EN_CHANNEL_ID", str(dst_id))
    err = _reload_or_error("edit", lang)
    if err:
        return err
    return t("editch_ok", lang, name=html.escape(name), src=src_id, dst=dst_id)


def _cmd_removechannel(args: List[str], lang: str = "en") -> str:
    if len(args) != 1:
        return t("rmch_usage", lang)
    name = args[0].strip().lower()
    if name in _PROTECTED_CHANNELS:
        return t("rmch_protected", lang, name=html.escape(name))
    if name not in _logical_names():
        return t("editch_unknown", lang, name=html.escape(name))
    # Drop from LOGICAL_CHANNELS first so reload() no longer requires its vars,
    # then clean up the leaf vars.
    new_names = [n for n in _logical_names() if n != name]
    env_store.set_env_var("LOGICAL_CHANNELS", ",".join(new_names))
    up = name.upper()
    for suffix in ("_CHANNEL", "_EN_CHANNEL_ID", "_CHANNEL_NAME", "_EN_CHANNEL_NAME"):
        env_store.unset_env_var(f"{up}{suffix}")
    err = _reload_or_error("remove", lang)
    if err:
        return err
    return t("rmch_ok", lang, name=html.escape(name))


def _cmd_admins(lang: str = "en") -> str:
    lines = [t("admins_title", lang)]
    admins = admin_store.list_admins()
    for a in admins:
        if a["label"]:
            lines.append(f"{html.escape(a['label'])} (<code>{a['id']}</code>)")
        elif a["resolved"]:
            lines.append(f"{html.escape(a['resolved'])} (<code>{a['id']}</code>)")
        else:
            lines.append(f"<code>{a['id']}</code>")
    if len(lines) == 1:
        lines.append(t("common_none", lang))
    lines += [
        "",
        t("admins_help", lang),
        t("admins_note", lang),
    ]
    return "\n".join(lines)


def _derive_label(user) -> Optional[str]:
    """Best human label for a resolved/shared user: real name, else @username."""
    name = " ".join(
        p
        for p in (getattr(user, "first_name", None), getattr(user, "last_name", None))
        if p
    )
    uname = getattr(user, "username", None)
    return name or (f"@{uname}" if uname else None)


def _add_shared_users(users) -> str:
    """Add admins picked via the request_users keyboard (a list of User-likes)."""
    if not users:
        return "❌ No user received from the picker."
    lines: List[str] = []
    for u in users:
        uid = getattr(u, "id", None)
        if uid is None:
            continue
        ok, msg = admin_store.add_admin(str(uid), _derive_label(u))
        lines.append(("✅ " if ok else "❌ ") + html.escape(msg))
    return "\n".join(lines) if lines else "❌ No valid user received."


async def _cmd_addadmin(args: List[str], pyro=None) -> str:
    if not args:
        return "❌ Usage: /addadmin &lt;user_id|@username&gt; [label]"
    target = args[0].strip()
    label = " ".join(args[1:]).strip() or None

    # Numeric id (incl. negative) → add directly.
    if target and target != "-" and target.lstrip("-").isdigit():
        ok, msg = admin_store.add_admin(target, label)
        return ("✅ " if ok else "❌ ") + html.escape(msg)

    # Otherwise treat it as a username, resolved best-effort via the live client.
    if pyro is None:
        return "❌ Username lookup unavailable here — use a numeric user id."
    uname = target.lstrip("@")
    try:
        user = await pyro.get_users(uname)
    except Exception as exc:
        return (
            f"❌ Couldn't resolve {html.escape(target)} ({html.escape(str(exc))}). "
            "The bot can only resolve users/usernames it can see."
        )
    uid = getattr(user, "id", None)
    if uid is None:
        return f"❌ Couldn't resolve {html.escape(target)}."
    ok, msg = admin_store.add_admin(str(uid), label or _derive_label(user))
    return ("✅ " if ok else "❌ ") + html.escape(msg)


def _cmd_removeadmin(args: List[str]) -> str:
    if len(args) != 1:
        return "❌ Usage: /removeadmin &lt;user_id&gt;"
    ok, msg = admin_store.remove_admin(args[0])
    return ("✅ " if ok else "❌ ") + html.escape(msg)


def _cmd_reload(lang: str = "en") -> str:
    err = _reload_or_error("reload", lang)
    if err:
        return err
    reload_prompt_template()
    return t("reload_ok", lang)


def _cmd_setlang(args: List[str], msg, lang: str = "en") -> str:
    """Set the caller's per-admin menu language (text-command parity with the menu)."""
    uid = getattr(getattr(msg, "from_user", None), "id", None)
    if uid is None:
        return t("alert_error", lang)
    if len(args) != 1 or args[0].strip().lower() not in admin_i18n.LOCALES:
        langs = " | ".join(admin_i18n.LOCALES)
        return f"❌ Usage: /setlang &lt;{html.escape(langs)}&gt;"
    new_lang = args[0].strip().lower()
    admin_prefs.set_lang(uid, new_lang)
    return t("lang_switched", new_lang)


async def handle_command(
    msg,
    *,
    anthropic=None,
    sender=None,
    recorder=None,
    query_queue=None,
    start_ts=None,
    pyro=None,
) -> str:
    """Parse one admin DM and return the reply text (HTML). Never raises."""
    from translator.services import admin_menu  # lazy: avoid import cycle

    lang = _lang_of(msg)
    uid = getattr(getattr(msg, "from_user", None), "id", None)

    raw = (getattr(msg, "text", None) or "").strip()
    # A persistent reply-keyboard tap arrives as label text (e.g. "📊 Status");
    # map it back to the command it stands for.
    resolved = admin_menu.resolve_button_label(raw) or raw

    # If an add-channel wizard is in progress for this admin, capture their reply
    # — unless they tapped a button / typed a command, which escapes the wizard.
    if uid is not None and admin_wizard.is_active(uid):
        if resolved.startswith("/"):
            admin_wizard.cancel(uid)
        else:
            return admin_wizard.feed(uid, raw, lang)

    text = resolved
    if not text.startswith("/"):
        return t("prompt_for_help", lang)
    first = text.split(maxsplit=1)[0]
    cmd = first.split("@", 1)[0].lower()  # tolerate /cmd@BotName
    args = text.split()[1:]

    if cmd == "/help" or cmd == "/start":
        return _cmd_help(lang)
    if cmd == "/status":
        return _cmd_status(start_ts, query_queue, pyro, lang)
    if cmd == "/stats":
        return _cmd_stats(args, lang)
    if cmd == "/cost":
        return _cmd_cost(args, lang)
    if cmd == "/channels":
        return _cmd_channels(lang)
    if cmd == "/prompt":
        return _cmd_prompt(lang)
    if cmd == "/setmodel":
        return _cmd_setmodel(args, lang)
    if cmd == "/settemp":
        return _cmd_settemp(args, lang)
    if cmd == "/setmaxtokens":
        return _cmd_setmaxtokens(args, lang)
    if cmd == "/setloglevel":
        return _cmd_setloglevel(args, lang)
    if cmd == "/setlang":
        return _cmd_setlang(args, msg, lang)
    if cmd == "/cancel":
        if uid is not None:
            admin_wizard.cancel(uid)
        return t("wiz_cancelled", lang)
    if cmd == "/setprompt":
        return _cmd_setprompt(msg, lang)
    if cmd == "/addchannel":
        return _cmd_addchannel(args, lang)
    if cmd == "/editchannel":
        return _cmd_editchannel(args, lang)
    if cmd == "/removechannel":
        return _cmd_removechannel(args, lang)
    if cmd == "/admins":
        return _cmd_admins(lang)
    if cmd == "/addadmin":
        return await _cmd_addadmin(args, pyro=pyro)
    if cmd == "/removeadmin":
        return _cmd_removeadmin(args)
    if cmd == "/reload":
        return _cmd_reload(lang)
    return t("unknown_cmd", lang, cmd=html.escape(cmd))


def _is_admin(_f, _c, m) -> bool:
    """Predicate for the admin filter; logs each private DM for observability."""
    uid = getattr(getattr(m, "from_user", None), "id", None)
    ok = uid is not None and uid in CONFIG.ADMIN_CHAT_IDS
    log.info(
        "DM private message: from_user_id=%s authorized=%s (admins=%s)",
        uid,
        ok,
        CONFIG.ADMIN_CHAT_IDS,
    )
    return ok


def _admin_filter():
    """Pyrogram filter matching DMs from any configured admin (read live)."""
    return filters.create(_is_admin)


def register_admin_handlers(
    pyro,
    anthropic=None,
    sender=None,
    recorder=None,
    *,
    query_queue=None,
    start_ts=None,
):
    """Register the private-DM admin command handler on the Pyrogram client."""
    from translator.services import admin_menu  # lazy: avoid import cycle

    @pyro.on_message(filters.private & _admin_filter())
    async def _dispatch(client, msg):  # noqa: ANN001
        uid = getattr(getattr(msg, "from_user", None), "id", None)
        lang = admin_prefs.get_lang(uid) if uid is not None else admin_i18n.DEFAULT_LANG

        # A user picked via the "➕ Add admin" keyboard arrives as a service
        # message (no text) carrying users_shared — handle it before the text path
        # and restore the main keyboard.
        shared = getattr(msg, "users_shared", None)
        if shared is not None:
            if uid is not None:
                admin_wizard.cancel(uid)  # picking a user leaves any wizard
            try:
                reply = _add_shared_users(getattr(shared, "users", None) or [])
            except Exception as exc:
                log.exception("add admin via picker failed")
                reply = f"❌ Error: {html.escape(str(exc))}"
            try:
                await msg.reply_text(
                    _truncate(reply),
                    parse_mode=enums.ParseMode.HTML,
                    reply_markup=admin_menu.to_reply_markup(
                        admin_menu.build_reply_keyboard(lang)
                    ),
                )
            except Exception:
                log.exception("failed to send add-admin reply")
            return

        text = (getattr(msg, "text", None) or "").strip()
        resolved = admin_menu.resolve_button_label(text) or text
        token = (
            resolved.split(maxsplit=1)[0].split("@", 1)[0].lower()
            if resolved.startswith("/")
            else ""
        )
        # Tapping a menu-bearing button abandons any in-progress add-channel
        # wizard cleanly (otherwise the next typed message would be captured).
        if uid is not None and token in (
            "/menu",
            "/start",
            "/settings",
            "/aimenu",
            "/adminsmenu",
            "/channelsmenu",
        ):
            admin_wizard.cancel(uid)
        # Menu-bearing entrypoints attach a keyboard, so they bypass the plain
        # text-reply path of handle_command.
        if token in ("/menu", "/start"):
            try:
                await msg.reply_text(
                    admin_i18n.t("menu_greeting", lang),
                    parse_mode=enums.ParseMode.HTML,
                    reply_markup=admin_menu.to_reply_markup(
                        admin_menu.build_reply_keyboard(lang)
                    ),
                )
            except Exception:
                log.exception("failed to send menu")
            return
        if token == "/settings":
            title, rows = admin_menu.settings_entry(lang)
            try:
                await msg.reply_text(
                    title,
                    parse_mode=enums.ParseMode.HTML,
                    reply_markup=admin_menu.to_inline_markup(rows),
                )
            except Exception:
                log.exception("failed to send settings menu")
            return
        if token == "/aimenu":
            title, rows = admin_menu.ai_entry(lang)
            try:
                await msg.reply_text(
                    title,
                    parse_mode=enums.ParseMode.HTML,
                    reply_markup=admin_menu.to_inline_markup(rows),
                )
            except Exception:
                log.exception("failed to send AI settings menu")
            return
        if token == "/adminsmenu":
            title, rows = admin_menu.admins_entry(lang)
            try:
                await msg.reply_text(
                    title,
                    parse_mode=enums.ParseMode.HTML,
                    reply_markup=admin_menu.to_inline_markup(rows),
                )
            except Exception:
                log.exception("failed to send admins menu")
            return
        if token == "/channelsmenu":
            title, rows = admin_menu.channels_entry(lang)
            try:
                await msg.reply_text(
                    title,
                    parse_mode=enums.ParseMode.HTML,
                    reply_markup=admin_menu.to_inline_markup(rows),
                )
            except Exception:
                log.exception("failed to send channels menu")
            return

        try:
            reply = await handle_command(
                msg,
                anthropic=anthropic,
                sender=sender,
                recorder=recorder,
                query_queue=query_queue,
                start_ts=start_ts,
                pyro=pyro,
            )
        except Exception as exc:  # never let an admin command crash the handler
            log.exception("admin command failed")
            reply = f"❌ Error: {html.escape(str(exc))}"
        try:
            await msg.reply_text(
                _truncate(reply), parse_mode=enums.ParseMode.HTML
            )
        except Exception:
            log.exception("failed to send admin reply")

    # Inline-button presses (the Settings tree) arrive as callback queries.
    admin_menu.register_callback_handler(
        pyro, start_ts=start_ts, query_queue=query_queue
    )

    return _dispatch
