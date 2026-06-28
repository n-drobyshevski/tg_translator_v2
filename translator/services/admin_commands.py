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
from translator.services import env_store
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


HELP_TEXT = (
    "<b>Relay bot — admin commands</b>\n"
    "/menu — open the button menu (easiest)\n"
    "/help — this message\n"
    "/status — uptime, channels, queue depth\n"
    "/stats [days] — relay counts &amp; failures (default 7)\n"
    "/channels — configured channel pairs\n"
    "/prompt — current prompt template\n"
    "/setmodel &lt;model&gt;\n"
    "/settemp &lt;0..1&gt;\n"
    "/setmaxtokens &lt;1..8192&gt;\n"
    "/setloglevel &lt;DEBUG|INFO|WARNING|ERROR|CRITICAL&gt;\n"
    "/setprompt &lt;template&gt; (multi-line, or reply to a message)\n"
    "/addchannel &lt;name&gt; &lt;src_id&gt; &lt;dst_id&gt; [src_name] [dst_name]\n"
    "/editchannel &lt;name&gt; &lt;src_id&gt; &lt;dst_id&gt;\n"
    "/removechannel &lt;name&gt;\n"
    "/reload — re-read .env + prompt template\n"
    "(/setprompt, /addchannel, /editchannel need typed input)"
)


def _cmd_help() -> str:
    return HELP_TEXT


def _cmd_status(start_ts, query_queue, pyro) -> str:
    connected = getattr(pyro, "is_connected", None)
    qsize = query_queue.qsize() if query_queue is not None else "?"
    sources = CONFIG.get_source_channel_ids()
    lines = [
        "<b>Status</b>",
        f"Uptime: {_fmt_uptime(start_ts)}",
        f"Pyrogram connected: {connected}",
        f"Source channels: {len(sources)}",
        f"Metadata queue depth: {qsize}",
        f"Model: {html.escape(str(CONFIG.ANTHROPIC_MODEL))}",
    ]
    return "\n".join(lines)


def _cmd_stats(args: List[str]) -> str:
    days = 7
    if args:
        try:
            days = int(args[0])
        except ValueError:
            return "❌ Usage: /stats [days]"
        if not 1 <= days <= 30:
            return "❌ days must be 1..30"
    try:
        from translator.db import events_dao

        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        messages = events_dao.load_messages(since_iso=cutoff)
    except Exception as exc:  # pragma: no cover - defensive
        return f"❌ Stats unavailable: {html.escape(str(exc))}"

    total = len(messages)
    failures = sum(1 for m in messages if not m.get("posting_success"))
    by_channel = Counter(m.get("source_channel_name") or "?" for m in messages)
    lines = [
        f"<b>Stats — last {days}d</b>",
        f"Relayed events: {total}",
        f"Failures: {failures}",
        "",
        "<b>By source channel</b>",
    ]
    if by_channel:
        lines += [
            f"{html.escape(str(name))}: {count}"
            for name, count in by_channel.most_common()
        ]
    else:
        lines.append("(none)")
    return "\n".join(lines)


def _config_summary() -> str:
    """Current non-secret settings as value lines (no header).

    Rendered inside the Settings menu (see :mod:`translator.services.admin_menu`),
    which supplies its own ``⚙️ Settings`` title. Labels mirror the submenu wording.
    """
    d = CONFIG.as_dict()
    lines = [
        f"Model: {html.escape(str(d['ANTHROPIC_MODEL']))}",
        f"Temperature: {d['ANTHROPIC_TEMPERATURE']}",
        f"Max Tokens: {d['ANTHROPIC_MAX_TOKENS']}",
        f"Log Level: {html.escape(str(d['LOG_LEVEL']))}",
        f"Admin IDs: {d['ADMIN_CHAT_IDS']}",
        f"Channels: {html.escape(', '.join(d['LOGICAL_CHANNELS']))}",
    ]
    return "\n".join(lines)


def _cmd_channels() -> str:
    lines = ["<b>Channel pairs</b>"]
    for name in _logical_names():
        src = CONFIG.channels[name]
        dst = CONFIG.channels.get(name + "_en")
        dst_id = dst.channel_id if dst else "—"
        lines.append(
            f"{html.escape(name)}: src {src.channel_id} → dst {dst_id}"
        )
    if len(lines) == 1:
        lines.append("(none)")
    return "\n".join(lines)


def _cmd_prompt() -> str:
    if not PROMPT_TEMPLATE_PATH.exists():
        return "(no prompt template file)"
    text = PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")
    return "<b>Prompt template</b>\n<pre>" + html.escape(_truncate(text, 3500)) + "</pre>"


def _cmd_setmodel(args: List[str]) -> str:
    if len(args) != 1 or not args[0].strip():
        return "❌ Usage: /setmodel &lt;model&gt;"
    model = args[0].strip()
    _persist_and_reload("ANTHROPIC_MODEL", model)
    return f"✅ ANTHROPIC_MODEL = {html.escape(model)}"


def _cmd_settemp(args: List[str]) -> str:
    if len(args) != 1:
        return "❌ Usage: /settemp &lt;0..1&gt;"
    try:
        val = float(args[0])
    except ValueError:
        return "❌ Temperature must be a number 0..1"
    if not 0.0 <= val <= 1.0:
        return "❌ Temperature must be 0..1"
    _persist_and_reload("ANTHROPIC_TEMPERATURE", str(val))
    return f"✅ ANTHROPIC_TEMPERATURE = {val}"


def _cmd_setmaxtokens(args: List[str]) -> str:
    if len(args) != 1:
        return "❌ Usage: /setmaxtokens &lt;1..8192&gt;"
    try:
        val = int(args[0])
    except ValueError:
        return "❌ max_tokens must be an integer"
    if not 1 <= val <= 8192:
        return "❌ max_tokens must be 1..8192"
    _persist_and_reload("ANTHROPIC_MAX_TOKENS", str(val))
    return f"✅ ANTHROPIC_MAX_TOKENS = {val}"


def _cmd_setloglevel(args: List[str]) -> str:
    if len(args) != 1:
        return "❌ Usage: /setloglevel &lt;LEVEL&gt;"
    level_name = args[0].strip().upper()
    if level_name not in _VALID_LOG_LEVELS:
        return f"❌ level must be one of {', '.join(sorted(_VALID_LOG_LEVELS))}"
    _persist_and_reload("LOG_LEVEL", level_name)
    # Apply to the running process too.
    level = getattr(logging, level_name)
    root = logging.getLogger()
    root.setLevel(level)
    for h in root.handlers:
        h.setLevel(level)
    return f"✅ LOG_LEVEL = {level_name} (applied live)"


def _cmd_setprompt(msg) -> str:
    new_prompt = None
    reply = getattr(msg, "reply_to_message", None)
    if reply is not None and getattr(reply, "text", None):
        new_prompt = reply.text
    elif msg.text and "\n" in msg.text:
        new_prompt = msg.text.split("\n", 1)[1]
    if new_prompt is None:
        return (
            "❌ Send the template after the command on new lines, "
            "or reply to a message containing it."
        )
    err = validate_prompt(new_prompt)
    if err:
        return f"❌ {html.escape(err)}"
    # One-step rollback, mirroring the Flask admin app.
    if PROMPT_TEMPLATE_PATH.exists():
        backup = PROMPT_TEMPLATE_PATH.with_suffix(PROMPT_TEMPLATE_PATH.suffix + ".bak")
        backup.write_text(
            PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8"), encoding="utf-8"
        )
    PROMPT_TEMPLATE_PATH.write_text(new_prompt, encoding="utf-8")
    reload_prompt_template()
    return "✅ Prompt template updated and reloaded live."


def _reload_or_error(action: str) -> Optional[str]:
    """Run CONFIG.reload(); return an error string on failure, else None."""
    try:
        CONFIG.reload()
        return None
    except Exception as exc:
        return f"❌ {action} failed on reload: {html.escape(str(exc))}"


def _cmd_addchannel(args: List[str]) -> str:
    if len(args) < 3:
        return (
            "❌ Usage: /addchannel &lt;name&gt; &lt;src_id&gt; &lt;dst_id&gt; "
            "[src_name] [dst_name]"
        )
    name = args[0].strip().lower()
    if not _NAME_RE.fullmatch(name):
        return "❌ name must match [a-z0-9_]+"
    if name in _logical_names():
        return f"❌ channel '{html.escape(name)}' already exists (use /editchannel)"
    try:
        src_id = int(args[1])
        dst_id = int(args[2])
    except ValueError:
        return "❌ src_id and dst_id must be integers"

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

    err = _reload_or_error("add")
    if err:
        return err
    return (
        f"✅ Added channel '{html.escape(name)}': src {src_id} → dst {dst_id}\n"
        "⚠️ Make sure the bot is an admin/member of the source channel, "
        "or Telegram won't deliver its posts."
    )


def _cmd_editchannel(args: List[str]) -> str:
    if len(args) != 3:
        return "❌ Usage: /editchannel &lt;name&gt; &lt;src_id&gt; &lt;dst_id&gt;"
    name = args[0].strip().lower()
    if name not in _logical_names():
        return f"❌ unknown channel '{html.escape(name)}'"
    try:
        src_id = int(args[1])
        dst_id = int(args[2])
    except ValueError:
        return "❌ src_id and dst_id must be integers"
    up = name.upper()
    env_store.set_env_var(f"{up}_CHANNEL", str(src_id))
    env_store.set_env_var(f"{up}_EN_CHANNEL_ID", str(dst_id))
    err = _reload_or_error("edit")
    if err:
        return err
    return f"✅ Updated '{html.escape(name)}': src {src_id} → dst {dst_id}"


def _cmd_removechannel(args: List[str]) -> str:
    if len(args) != 1:
        return "❌ Usage: /removechannel &lt;name&gt;"
    name = args[0].strip().lower()
    if name in _PROTECTED_CHANNELS:
        return f"❌ '{html.escape(name)}' is protected and cannot be removed"
    if name not in _logical_names():
        return f"❌ unknown channel '{html.escape(name)}'"
    # Drop from LOGICAL_CHANNELS first so reload() no longer requires its vars,
    # then clean up the leaf vars.
    new_names = [n for n in _logical_names() if n != name]
    env_store.set_env_var("LOGICAL_CHANNELS", ",".join(new_names))
    up = name.upper()
    for suffix in ("_CHANNEL", "_EN_CHANNEL_ID", "_CHANNEL_NAME", "_EN_CHANNEL_NAME"):
        env_store.unset_env_var(f"{up}{suffix}")
    err = _reload_or_error("remove")
    if err:
        return err
    return f"✅ Removed channel '{html.escape(name)}'"


def _cmd_reload() -> str:
    err = _reload_or_error("reload")
    if err:
        return err
    reload_prompt_template()
    return "✅ Reloaded .env config and prompt template."


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

    text = (getattr(msg, "text", None) or "").strip()
    # A persistent reply-keyboard tap arrives as label text (e.g. "📊 Status");
    # map it back to the command it stands for.
    text = admin_menu.resolve_button_label(text) or text
    if not text.startswith("/"):
        return "Send /help for the command list, or /menu for buttons."
    first = text.split(maxsplit=1)[0]
    cmd = first.split("@", 1)[0].lower()  # tolerate /cmd@BotName
    args = text.split()[1:]

    if cmd == "/help" or cmd == "/start":
        return _cmd_help()
    if cmd == "/status":
        return _cmd_status(start_ts, query_queue, pyro)
    if cmd == "/stats":
        return _cmd_stats(args)
    if cmd == "/channels":
        return _cmd_channels()
    if cmd == "/prompt":
        return _cmd_prompt()
    if cmd == "/setmodel":
        return _cmd_setmodel(args)
    if cmd == "/settemp":
        return _cmd_settemp(args)
    if cmd == "/setmaxtokens":
        return _cmd_setmaxtokens(args)
    if cmd == "/setloglevel":
        return _cmd_setloglevel(args)
    if cmd == "/setprompt":
        return _cmd_setprompt(msg)
    if cmd == "/addchannel":
        return _cmd_addchannel(args)
    if cmd == "/editchannel":
        return _cmd_editchannel(args)
    if cmd == "/removechannel":
        return _cmd_removechannel(args)
    if cmd == "/reload":
        return _cmd_reload()
    return f"❓ Unknown command {html.escape(cmd)}. Send /help."


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
        text = (getattr(msg, "text", None) or "").strip()
        resolved = admin_menu.resolve_button_label(text) or text
        token = (
            resolved.split(maxsplit=1)[0].split("@", 1)[0].lower()
            if resolved.startswith("/")
            else ""
        )
        # Menu-bearing entrypoints attach a keyboard, so they bypass the plain
        # text-reply path of handle_command.
        if token in ("/menu", "/start"):
            try:
                await msg.reply_text(
                    admin_menu.MENU_GREETING,
                    parse_mode=enums.ParseMode.HTML,
                    reply_markup=admin_menu.to_reply_markup(
                        admin_menu.build_reply_keyboard()
                    ),
                )
            except Exception:
                log.exception("failed to send menu")
            return
        if token == "/settings":
            title, rows = admin_menu.settings_entry()
            try:
                await msg.reply_text(
                    title,
                    parse_mode=enums.ParseMode.HTML,
                    reply_markup=admin_menu.to_inline_markup(rows),
                )
            except Exception:
                log.exception("failed to send settings menu")
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
