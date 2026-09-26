"""Admin control of the relay bot from a private Telegram DM.

The bot's Pyrogram client is a *bot* account, so it already receives private
messages. This module registers a ``filters.private`` handler, gated to
``CONFIG.ADMIN_CHAT_IDS``, that exposes a small command surface to query status
and change a whitelist of operational settings live, plus a defense-in-depth
group-1 guard that explicitly logs and drops private DMs from non-admins.

Writable settings are persisted to the shared root ``.env`` via
``env_store.set_env_var`` and applied immediately with ``CONFIG.reload()`` —
``translate_html`` reads model/temp/max-tokens fresh per call, the source-channel
filter reads channels live, and ``/setprompt`` calls ``reload_prompt_template``.
No secrets are editable from the DM.

Every reply is a rich message (Bot API 10.3) built from
:mod:`translator.services.rich_html` blocks: the ``_cmd_*`` helpers return a
:class:`~translator.services.rich_html.RichText` — a ``str`` of the classic-HTML
fallback that also carries the rich rendering — and everything is sent through
:mod:`translator.services.admin_send`.

The dispatch entry point ``handle_command`` is intentionally free of Pyrogram
plumbing so it can be unit-tested with a fake message object.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Sequence

from pyrogram import filters

from translator.config import CONFIG, LOG_FILE_PATH, PROMPT_TEMPLATE_PATH
from translator.services import (
    admin_i18n,
    admin_prefs,
    admin_send,
    admin_store,
    admin_wizard,
    env_store,
    rich_html,
)
from translator.services.admin_i18n import t
from translator.services.rich_html import (
    KV,
    Bullets,
    Details,
    Doc,
    Footer,
    Heading,
    Note,
    Para,
    Pre,
    RichText,
    Setting,
    Status,
    Table,
    esc,
)
from translator.utils.error_format import humanize_text
from translator.utils.model_capabilities import supports_effort, supports_sampling_params
from translator.utils.model_pricing import PRICES_AS_OF, canonical_id, estimate_cost
from translator.utils.prompt_validation import validate_prompt
from translator.utils.translation_utils import reload_prompt_template

log = logging.getLogger("ADMIN")

_NAME_RE = re.compile(r"[a-z0-9_]+")
# Logical channels backed by independently-required env vars: refuse to remove
# them from a DM (e.g. TEST_CHANNEL is _require()'d by Config regardless of
# LOGICAL_CHANNELS, so unsetting it would break reload()).
_PROTECTED_CHANNELS = {"test"}
_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
# output_config.effort values accepted on the Opus 4.7+ surface. Ordered
# low→high so the menu and the error message agree on presentation order.
_VALID_EFFORTS = ("low", "medium", "high")

_REPLY_LIMIT = rich_html.CLASSIC_LIMIT  # stay under Telegram's 4096 hard cap

# /logs reads this many lines for the rich message; the classic fallback shows
# the newest ``lines`` (30 by default) of them.
_RICH_LOG_LINES = 150


def _truncate(text: str, limit: int = _REPLY_LIMIT) -> str:
    # Returns ``text`` itself when it fits, so a RichText keeps its rich half.
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


# --- Reply building blocks ----------------------------------------------------


def _ok(title_html: str, *blocks) -> RichText:
    return Doc(Status(True, title_html), *blocks).render()


def _err(title_html: str, *blocks) -> RichText:
    return Doc(Status(False, title_html), *blocks).render()


def _usage(syntax_html: str, lang: str = "en") -> RichText:
    """``❌ Usage`` + the command syntax (technical, so not translated)."""
    return _err(t("err_usage", lang), Para(f"<code>{syntax_html}</code>"))


def _outcome(ok: bool, message: str) -> RichText:
    """A ✅/❌ line for a plain-text result message (e.g. from admin_store)."""
    return Doc(Status(ok, esc(message))).render()


def _now_hm() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M")


def _on_off(flag: bool, lang: str = "en") -> str:
    return t("val_on" if flag else "val_off", lang)


def _rich_active() -> bool:
    """Rich messages supported by this kurigram *and* switched on in the env."""
    from translator.services import admin_menu  # lazy: avoid import cycle

    return admin_menu.HAS_RICH_MESSAGES and rich_html.rich_env_enabled()


def compose(content, *, before: Sequence = (), after: Sequence = ()) -> RichText:
    """Wrap an existing reply with extra blocks, keeping its rich rendering.

    ``content + "…"`` would silently drop ``.rich``; this rebuilds the doc
    instead. A legacy plain ``str`` is kept as one paragraph.
    """
    c = rich_html.as_content(content)
    if not before and not after:
        return c
    doc = Doc(*before)
    if c.doc is not None:
        doc.extend(c.doc)
    else:
        doc.add(Para(str(c)))
    doc.add(*after)
    return doc.render()


def _fmt_uptime(start_ts: Optional[float], lang: str = "en") -> str:
    if start_ts is None:
        return t("val_unknown", lang)
    secs = int(time.monotonic() - start_ts)
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m}m {s}s"


# --- /help & /menu ------------------------------------------------------------

# /help groups every published command. Kept next to COMMAND_SPECS' consumers
# (a test asserts each spec lands in exactly one group) so a new command can't
# be published without also being documented.
COMMAND_GROUPS = (
    ("grp_monitoring", ("status", "stats", "logs")),
    ("grp_ai", ("setmodel", "seteffort", "setmaxtokens", "settemp", "prompt", "setprompt", "cost")),
    ("grp_channels", ("channels", "addchannel", "editchannel", "removechannel")),
    ("grp_admins", ("admins", "addadmin", "removeadmin")),
    (
        "grp_system",
        ("menu", "setlang", "setrich", "richcheck", "setloglevel", "reload", "cancel", "help"),
    ),
)


def _surface_bullets(lang: str) -> Bullets:
    return Bullets(
        [t("txt_help_status", lang), t("txt_help_ai", lang), t("txt_help_settings", lang)]
    )


def _help_doc(lang: str = "en") -> Doc:
    descs = dict(COMMAND_SPECS)
    doc = Doc(
        Heading(t("h_help", lang)),
        Para(t("txt_help_intro", lang)),
        _surface_bullets(lang),
        Heading(t("h_commands", lang), 4),
    )
    for group_key, names in COMMAND_GROUPS:
        rows = [[f"<code>/{n}</code>", t(descs[n], lang)] for n in names if n in descs]
        doc.add(
            Details(
                t(group_key, lang),
                Table(
                    [t("col_command", lang), t("col_description", lang)],
                    rows,
                    classic_row=lambda r: f"{r[0]} — {r[1]}",
                ),
            )
        )
    return doc.add(Footer(t("hint_help", lang)))


def _cmd_help(lang: str = "en") -> RichText:
    return _help_doc(lang).render()


def menu_greeting(lang: str = "en") -> RichText:
    """The /menu and /start reply (sent with the persistent reply keyboard)."""
    return Doc(
        Heading(t("h_menu", lang)),
        Para(t("txt_menu_intro", lang)),
        _surface_bullets(lang),
        Footer(t("hint_menu_typed", lang)),
    ).render()


# --- /status & /stats ---------------------------------------------------------


def _recent_events(lang: str = "en", lookback_days: int = 7, limit: int = 6) -> list:
    """The latest relay events (success or failure) as '/status' blocks.

    One feed where each row carries its own ✅/❌, since operators usually just
    want "what happened last". Pull-based; no push alerts. Returns no blocks if
    the event store can't be read — /status must never break on a DB hiccup.
    """
    try:
        from translator.db import events_dao

        cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()
        msgs = events_dao.load_messages(since_iso=cutoff)
    except Exception:  # pragma: no cover - defensive
        return []
    if not msgs:
        return [Heading(t("h_events_none", lang), 4), Para(t("txt_events_none", lang))]
    rows = []
    for m in reversed(msgs[-limit:]):  # newest first (load_messages is oldest-first)
        ts = (m.get("timestamp") or "")[5:16].replace("T", " ")  # MM-DD HH:MM (UTC)
        chan = esc(m.get("source_channel_name") or "?")
        if m.get("posting_success"):
            rows.append(["✅", ts, chan, esc(m.get("media_type") or "text")])
        else:
            # humanize_text cleans up legacy events whose exception_message is a raw
            # SDK dump; it is idempotent on already-humanized (new) events.
            reason = humanize_text(str(m.get("exception_message") or ""))[:160]
            rows.append(["❌", ts, chan, esc(reason)])
    return [
        Heading(t("h_events", lang, count=len(msgs)), 4),
        Table(
            ["", t("col_time", lang), t("col_channel", lang), t("col_detail", lang)],
            rows,
            classic_row=lambda r: f"{r[0]} {r[1]} UTC · {r[2]} · {r[3]}",
        ),
    ]


def _cmd_status(start_ts, query_queue, pyro, lang: str = "en") -> RichText:
    # query_queue is retained in the signature for call-site stability; the queue
    # depth is no longer surfaced in /status.
    connected = getattr(pyro, "is_connected", None)
    if connected is None:
        conn = t("val_unknown", lang)
    else:
        conn = ("✅ " + t("val_yes", lang)) if connected else ("❌ " + t("val_no", lang))
    return Doc(
        Heading(t("h_status", lang)),
        KV(
            [
                (t("lbl_uptime", lang), _fmt_uptime(start_ts, lang)),
                (t("lbl_connected", lang), conn),
                (t("lbl_model", lang), f"<code>{esc(CONFIG.ANTHROPIC_MODEL)}</code>"),
                (t("lbl_rich", lang), _on_off(_rich_active(), lang)),
            ]
        ),
        *_recent_events(lang),
        Footer(t("hint_status", lang, time=_now_hm())),
    ).render()


def _pct(part: int, whole: int) -> str:
    return f"{part / whole * 100:.0f}%" if whole else "—"


def _cmd_stats(args: List[str], lang: str = "en") -> RichText:
    days = 7
    if args:
        try:
            days = int(args[0])
        except ValueError:
            return _usage("/stats [days]", lang)
        if not 1 <= days <= 30:
            return _err(t("err_stats_days", lang))
    try:
        from translator.db import events_dao

        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        messages = events_dao.load_messages(since_iso=cutoff)
    except Exception as exc:  # pragma: no cover - defensive
        return _err(t("err_stats_unavailable", lang), Para(esc(exc)))

    total = len(messages)
    failures = sum(1 for m in messages if not m.get("posting_success"))
    by_channel = Counter(m.get("source_channel_name") or "?" for m in messages)
    failed_by = Counter(
        m.get("source_channel_name") or "?" for m in messages if not m.get("posting_success")
    )
    rows = [
        [esc(name), str(count), str(failed_by[name]), _pct(count, total)]
        for name, count in by_channel.most_common()
    ]
    usage = _usage_summary(messages)
    return Doc(
        Heading(t("h_stats", lang, days=days)),
        KV(
            [
                (t("lbl_relayed", lang), total),
                (t("lbl_failures", lang), failures),
                (t("lbl_success_rate", lang), _pct(total - failures, total)),
                (t("lbl_est_cost", lang), f"{_money(usage['cost'])} · /cost"),
            ]
        ),
        Heading(t("h_by_channel", lang), 4),
        Table(
            [t("col_channel", lang), t("col_posts", lang), t("col_failures", lang), t("col_share", lang)],
            rows,
            classic_row=lambda r: f"{r[0]}: {r[1]}",
            empty=t("common_none", lang),
        ),
        Footer(t("hint_stats", lang)),
    ).render()


# --- /cost -------------------------------------------------------------------

_COST_MAX_DAYS = 90
_TOKEN_FIELDS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens")


def _int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _usage_summary(events) -> dict:
    """Token and cost totals over event dicts (as ``events_dao.load_messages``).

    Only rows that carry token usage are translations; the rest (sends without a
    translation, and rows written before the token columns existed) are counted
    as ``untracked``. Cost is summed over rows whose model has a list price;
    the others still count their tokens and are reported as ``unpriced``.
    """
    totals = dict.fromkeys(_TOKEN_FIELDS, 0)
    by_model: dict = {}
    by_channel: dict = {}
    summary = {
        "translations": 0,
        "untracked": 0,
        "unpriced": 0,
        "cost": 0.0,
        "tokens": totals,
        "by_model": by_model,
        "by_channel": by_channel,
    }
    for event in events:
        tokens = {f: _int(event.get(f)) for f in _TOKEN_FIELDS}
        if not any(tokens.values()):
            summary["untracked"] += 1
            continue
        model = canonical_id(event.get("model_used")) or "?"
        cost = estimate_cost(
            model,
            input_tokens=tokens["input_tokens"],
            output_tokens=tokens["output_tokens"],
            cache_read_tokens=tokens["cache_read_tokens"],
            cache_write_tokens=tokens["cache_creation_tokens"],
        )
        summary["translations"] += 1
        for f in _TOKEN_FIELDS:
            totals[f] += tokens[f]
        if cost is None:
            summary["unpriced"] += 1
        else:
            summary["cost"] += cost

        m = by_model.setdefault(
            model,
            {"posts": 0, "cost": 0.0, "priced": cost is not None, **dict.fromkeys(_TOKEN_FIELDS, 0)},
        )
        m["posts"] += 1
        m["cost"] += cost or 0.0
        for f in _TOKEN_FIELDS:
            m[f] += tokens[f]

        channel = str(event.get("source_channel_name") or "?")
        c = by_channel.setdefault(channel, {"posts": 0, "cost": 0.0})
        c["posts"] += 1
        c["cost"] += cost or 0.0

    prompt = _prompt_tokens(totals)
    summary["cache_hit"] = totals["cache_read_tokens"] / prompt if prompt else None
    n = summary["translations"]
    priced = n - summary["unpriced"]
    summary["cost_per"] = summary["cost"] / priced if priced else None
    return summary


def _prompt_tokens(counts: dict) -> int:
    """All prompt-side tokens: uncached input plus cache reads and writes."""
    return counts["input_tokens"] + counts["cache_read_tokens"] + counts["cache_creation_tokens"]


def _money(value: Optional[float]) -> str:
    """USD for a report: cents from $0.10 up, two significant figures below.

    A single translation costs a fraction of a cent, which "$0.00" would hide.
    """
    if value is None:
        return "—"
    if value == 0 or value >= 0.1:
        return f"${value:,.2f}"
    if value < 0.0001:
        return "<$0.0001"
    return "$" + f"{value:.2g}"


def _tokens(value: int) -> str:
    return f"{value:,}"


def _cost_doc(days: int = 7, lang: str = "en") -> Doc:
    try:
        from translator.db import events_dao

        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        events = events_dao.load_messages(since_iso=cutoff)
    except Exception as exc:  # pragma: no cover - defensive
        return Doc(Status(False, t("err_stats_unavailable", lang)), Para(esc(exc)))

    usage = _usage_summary(events)
    tokens = usage["tokens"]
    hit = usage["cache_hit"]
    model_rows = [
        [
            f"<code>{esc(model)}</code>",
            str(m["posts"]),
            _tokens(_prompt_tokens(m)),
            _tokens(m["output_tokens"]),
            _money(m["cost"]) if m["priced"] else "—",
        ]
        for model, m in sorted(usage["by_model"].items(), key=lambda kv: -kv[1]["posts"])
    ]
    channel_rows = [
        [esc(name), str(c["posts"]), _money(c["cost"])]
        for name, c in sorted(usage["by_channel"].items(), key=lambda kv: -kv[1]["cost"])
    ]
    return Doc(
        Heading(t("h_cost_report", lang, days=days)),
        KV(
            [
                (t("lbl_translations", lang), usage["translations"]),
                (t("lbl_est_cost", lang), f"<b>{_money(usage['cost'])}</b>"),
                (t("lbl_per_translation", lang), _money(usage["cost_per"])),
                (t("lbl_cache_hit", lang), "—" if hit is None else f"{hit * 100:.0f}%"),
                (
                    t("lbl_tokens_in_out", lang),
                    f"{_tokens(_prompt_tokens(tokens))} / {_tokens(tokens['output_tokens'])}",
                ),
            ]
        ),
        Note(t("txt_cost_unpriced", lang, count=usage["unpriced"]), icon="ℹ️")
        if usage["unpriced"]
        else None,
        Heading(t("h_by_model", lang), 4),
        Table(
            [t("col_model", lang), t("col_posts", lang), t("col_in", lang),
             t("col_out", lang), t("col_cost", lang)],
            model_rows,
            classic_row=lambda r: f"{r[0]}: {r[1]} · {r[4]}",
            empty=t("common_none", lang),
        ),
        Heading(t("h_by_channel", lang), 4),
        Table(
            [t("col_channel", lang), t("col_posts", lang), t("col_cost", lang)],
            channel_rows,
            classic_row=lambda r: f"{r[0]}: {r[1]} · {r[2]}",
            empty=t("common_none", lang),
        ),
        Footer(t("hint_cost", lang, as_of=PRICES_AS_OF)),
    )


def _cmd_cost(args: List[str], lang: str = "en") -> RichText:
    days = 7
    if args:
        try:
            days = int(args[0])
        except ValueError:
            return _usage("/cost [days]", lang)
        if not 1 <= days <= _COST_MAX_DAYS:
            return _err(t("err_cost_days", lang, max=_COST_MAX_DAYS))
    return _cost_doc(days, lang).render()


# --- Settings summary, channels, prompt, logs --------------------------------


def _config_pairs(lang: str = "en") -> list:
    """Current non-secret settings as (label, value) rows for the Settings menu.

    Rendered inside the Settings menu (see :mod:`translator.services.admin_menu`),
    which supplies its own ``⚙️ Settings`` heading. Labels mirror the submenus.
    """
    d = CONFIG.as_dict()
    # Show admins by name (manual label → resolved @username → raw id fallback),
    # reusing the same best-effort resolution as /admins.
    admins = ", ".join(esc(a["display"]) for a in admin_store.list_admins()) or t(
        "common_none", lang
    )
    return [
        (t("lbl_log_level", lang), esc(d["LOG_LEVEL"])),
        (t("lbl_admins", lang), admins),
        (t("lbl_channels", lang), esc(", ".join(d["LOGICAL_CHANNELS"]))),
        (t("lbl_rich", lang), _on_off(_rich_active(), lang)),
    ]


def _channel_rows() -> List[List[str]]:
    rows = []
    for name in _logical_names():
        src = CONFIG.channels[name]
        dst = CONFIG.channels.get(name + "_en")
        rows.append([esc(name), str(src.channel_id), str(dst.channel_id if dst else "—")])
    return rows


def _channels_doc(lang: str = "en") -> Doc:
    return Doc(
        Heading(t("h_channels", lang)),
        Table(
            [t("col_name", lang), t("col_source", lang), t("col_destination", lang)],
            _channel_rows(),
            classic_row=lambda r: t("channels_line", lang, name=r[0], src=r[1], dst=r[2]),
            empty=t("common_none", lang),
        ),
    )


def _cmd_channels(lang: str = "en") -> RichText:
    return _channels_doc(lang).render()


def _prompt_doc(lang: str = "en") -> Doc:
    doc = Doc(Heading(t("h_prompt", lang)))
    if not PROMPT_TEMPLATE_PATH.exists():
        return doc.add(Para(t("txt_prompt_none", lang)))
    text = PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")
    return doc.add(
        KV(
            [
                (t("lbl_chars", lang), len(text)),
                (t("lbl_lines", lang), len(text.splitlines())),
            ]
        ),
        # The whole template fits a rich message; the classic fallback is cut
        # (keeping the start) to whatever the heading and footer leave.
        Pre(text, keep="head"),
        Footer(t("hint_setprompt", lang)),
    )


def _cmd_prompt(lang: str = "en") -> RichText:
    return _prompt_doc(lang).render()


def _tail_lines(path: str, n: int, *, max_bytes: int = 64_000) -> str:
    """Return the last ``n`` lines of ``path``, reading at most ``max_bytes``.

    Seeks from the end so a large ``bot.log`` never gets read whole. When the
    read starts mid-file the (possibly partial) first line is dropped.
    """
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        start = max(0, size - max_bytes)
        f.seek(start)
        data = f.read()
    text = data.decode("utf-8", errors="replace")
    if start > 0:
        text = text.split("\n", 1)[-1]
    return "\n".join(text.splitlines()[-n:])


def _logs_doc(lang: str = "en", *, lines: int = 30) -> Doc:
    """Most recent ``bot.log`` tail (newest at the bottom).

    The rich message shows up to ``_RICH_LOG_LINES``; the classic fallback the
    newest ``lines``. Truncation keeps the *tail* — the newest lines are what an
    operator opens this for.
    """
    doc = Doc(Heading(t("h_logs", lang)))
    if not os.path.exists(LOG_FILE_PATH):
        return doc.add(Para(t("txt_logs_none", lang)))
    try:
        tail = _tail_lines(LOG_FILE_PATH, max(lines, _RICH_LOG_LINES))
    except OSError as exc:  # pragma: no cover - defensive
        return Doc(Status(False, t("err_logs_read", lang)), Para(esc(exc)))
    if not tail.strip():
        return doc.add(Para(t("txt_logs_empty", lang)))
    return doc.add(
        Pre(tail, keep="tail", classic_max_lines=lines),
        Footer(t("hint_logs", lang, time=_now_hm())),
    )


def _cmd_logs(lang: str = "en", *, lines: int = 30) -> RichText:
    return _logs_doc(lang, lines=lines).render()


# --- Writable settings --------------------------------------------------------


def _cmd_setmodel(args: List[str], lang: str = "en") -> RichText:
    if len(args) != 1 or not args[0].strip():
        return _usage("/setmodel &lt;model&gt;", lang)
    model = args[0].strip()
    _persist_and_reload("ANTHROPIC_MODEL", model)
    return _ok(t("ok_model", lang), Setting("ANTHROPIC_MODEL", esc(model)))


def _cmd_settemp(args: List[str], lang: str = "en") -> RichText:
    if len(args) != 1:
        return _usage("/settemp &lt;0..1&gt;", lang)
    try:
        val = float(args[0])
    except ValueError:
        return _err(t("err_temp_nan", lang))
    if not 0.0 <= val <= 1.0:
        return _err(t("err_temp_range", lang))
    _persist_and_reload("ANTHROPIC_TEMPERATURE", str(val))
    # Saving is still correct (it applies if the model is switched back), but
    # say so rather than let the operator think they changed something.
    note = None
    if not supports_sampling_params(CONFIG.ANTHROPIC_MODEL):
        note = Note(t("txt_temp_ignored", lang, model=esc(CONFIG.ANTHROPIC_MODEL)))
    return _ok(t("ok_temp", lang), Setting("ANTHROPIC_TEMPERATURE", val), note)


def _cmd_setmaxtokens(args: List[str], lang: str = "en") -> RichText:
    if len(args) != 1:
        return _usage("/setmaxtokens &lt;1..128000&gt;", lang)
    try:
        val = int(args[0])
    except ValueError:
        return _err(t("err_tokens_nan", lang))
    # Ceiling raised from 8192 alongside the Sonnet 5 default: max_tokens now
    # covers thinking + response together, and the default itself is 8000, which
    # left almost no headroom. 128000 is the current models' real output cap.
    if not 1 <= val <= 128000:
        return _err(t("err_tokens_range", lang))
    _persist_and_reload("ANTHROPIC_MAX_TOKENS", str(val))
    return _ok(t("ok_tokens", lang), Setting("ANTHROPIC_MAX_TOKENS", val))


def _cmd_seteffort(args: List[str], lang: str = "en") -> RichText:
    """Set ``ANTHROPIC_EFFORT`` — thinking depth on the Opus 4.7+ surface.

    The modern counterpart to /settemp: each request surface takes one of the two
    and rejects the other, so this warns in exactly the same shape when the
    active model won't use it.
    """
    if len(args) != 1:
        return _usage("/seteffort &lt;low|medium|high&gt;", lang)
    val = args[0].strip().lower()
    if val not in _VALID_EFFORTS:
        return _err(t("err_effort_invalid", lang, levels=", ".join(_VALID_EFFORTS)))
    _persist_and_reload("ANTHROPIC_EFFORT", val)
    note = None
    if not supports_effort(CONFIG.ANTHROPIC_MODEL):
        note = Note(t("txt_effort_ignored", lang, model=esc(CONFIG.ANTHROPIC_MODEL)))
    return _ok(t("ok_effort", lang), Setting("ANTHROPIC_EFFORT", val), note)


def _cmd_setloglevel(args: List[str], lang: str = "en") -> RichText:
    if len(args) != 1:
        return _usage("/setloglevel &lt;LEVEL&gt;", lang)
    level_name = args[0].strip().upper()
    if level_name not in _VALID_LOG_LEVELS:
        return _err(
            t("err_log_invalid", lang, levels=", ".join(sorted(_VALID_LOG_LEVELS)))
        )
    _persist_and_reload("LOG_LEVEL", level_name)
    # Apply to the running process too.
    level = getattr(logging, level_name)
    root = logging.getLogger()
    root.setLevel(level)
    for h in root.handlers:
        h.setLevel(level)
    return _ok(
        t("ok_log", lang), Setting("LOG_LEVEL", level_name), Para(t("txt_applied_live", lang))
    )


def _cmd_setrich(args: List[str], lang: str = "en") -> RichText:
    """``/setrich on|off`` — the live kill switch for rich admin messages.

    Persisted like every other setting, so it survives a restart and applies to
    the very next reply (this one included when switching on).
    """
    from translator.services import admin_menu  # lazy: avoid import cycle

    value = args[0].strip().lower() if len(args) == 1 else ""
    if value not in ("on", "off"):
        return _usage("/setrich &lt;on|off&gt;", lang)
    on = value == "on"
    _persist_and_reload(rich_html.RICH_ENV, "1" if on else "0")
    if on:
        admin_menu._breaker.reset()  # an explicit "on" deserves a fresh try
    doc = Doc(
        Status(True, t("ok_rich", lang, state=_on_off(on, lang))),
        Setting(rich_html.RICH_ENV, "1" if on else "0"),
        Para(t("txt_rich_on" if on else "txt_rich_off", lang)),
    )
    if on and not admin_menu.HAS_RICH_MESSAGES:
        doc.add(Note(t("txt_rich_unsupported", lang)))
    return doc.render()


def _cmd_setprompt(msg, lang: str = "en") -> RichText:
    new_prompt = None
    reply = getattr(msg, "reply_to_message", None)
    if reply is not None and getattr(reply, "text", None):
        new_prompt = reply.text
    elif msg.text and "\n" in msg.text:
        new_prompt = msg.text.split("\n", 1)[1]
    if new_prompt is None:
        return _err(t("err_setprompt", lang), Para(t("txt_setprompt_how", lang)))
    err = validate_prompt(new_prompt)
    if err:
        return _err(t("err_prompt_invalid", lang), Para(esc(err)))
    # One-step rollback, mirroring the Flask admin app.
    if PROMPT_TEMPLATE_PATH.exists():
        backup = PROMPT_TEMPLATE_PATH.with_suffix(PROMPT_TEMPLATE_PATH.suffix + ".bak")
        backup.write_text(
            PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8"), encoding="utf-8"
        )
    PROMPT_TEMPLATE_PATH.write_text(new_prompt, encoding="utf-8")
    reload_prompt_template()
    return _ok(t("ok_prompt", lang), Para(t("txt_prompt_reloaded", lang)))


def _reload_or_error(action: str, lang: str = "en") -> Optional[RichText]:
    """Run CONFIG.reload(); return an error reply on failure, else None."""
    try:
        CONFIG.reload()
        return None
    except Exception as exc:
        return _err(t("err_reload", lang, action=action), Para(esc(exc)))


# --- Channels -----------------------------------------------------------------


def _pair_kv(src, dst, lang: str) -> KV:
    return KV(
        [
            (t("lbl_source", lang), f"<code>{esc(src)}</code>"),
            (t("lbl_destination", lang), f"<code>{esc(dst)}</code>"),
        ]
    )


def _cmd_addchannel(args: List[str], lang: str = "en") -> RichText:
    if len(args) < 3:
        return _usage(
            "/addchannel &lt;name&gt; &lt;src_id&gt; &lt;dst_id&gt; [src_name] [dst_name]",
            lang,
        )
    name = args[0].strip().lower()
    if not _NAME_RE.fullmatch(name):
        return _err(t("err_addch_name", lang))
    if name in _logical_names():
        return _err(t("err_addch_dup", lang, name=esc(name)))
    try:
        src_id = int(args[1])
        dst_id = int(args[2])
    except ValueError:
        return _err(t("err_addch_int", lang))

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
    return _ok(
        t("ok_addch", lang, name=esc(name)),
        _pair_kv(src_id, dst_id, lang),
        Note(t("txt_addch_member", lang)),
    )


def _cmd_editchannel(args: List[str], lang: str = "en") -> RichText:
    if len(args) != 3:
        return _usage("/editchannel &lt;name&gt; &lt;src_id&gt; &lt;dst_id&gt;", lang)
    name = args[0].strip().lower()
    if name not in _logical_names():
        return _err(t("err_unknown_channel", lang, name=esc(name)))
    try:
        src_id = int(args[1])
        dst_id = int(args[2])
    except ValueError:
        return _err(t("err_addch_int", lang))
    up = name.upper()
    env_store.set_env_var(f"{up}_CHANNEL", str(src_id))
    env_store.set_env_var(f"{up}_EN_CHANNEL_ID", str(dst_id))
    err = _reload_or_error("edit", lang)
    if err:
        return err
    return _ok(t("ok_editch", lang, name=esc(name)), _pair_kv(src_id, dst_id, lang))


def _cmd_removechannel(args: List[str], lang: str = "en") -> RichText:
    if len(args) != 1:
        return _usage("/removechannel &lt;name&gt;", lang)
    name = args[0].strip().lower()
    if name in _PROTECTED_CHANNELS:
        return _err(t("err_protected", lang, name=esc(name)))
    if name not in _logical_names():
        return _err(t("err_unknown_channel", lang, name=esc(name)))
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
    return _ok(t("ok_rmch", lang, name=esc(name)))


# --- Admins -------------------------------------------------------------------


def admins_table(admins, lang: str = "en") -> Table:
    """The admin list as a Name / ID table (classic: ``Name (<code>id</code>)``)."""
    rows = []
    for a in admins:
        name = a["label"] or a["resolved"] or ""
        rows.append([esc(name), f"<code>{esc(a['id'])}</code>"])
    return Table(
        [t("col_name", lang), t("col_id", lang)],
        rows,
        classic_row=lambda r: f"{r[0]} ({r[1]})" if r[0] else r[1],
        empty=t("common_none", lang),
    )


def _cmd_admins(lang: str = "en") -> RichText:
    return Doc(
        Heading(t("h_admins", lang)),
        admins_table(admin_store.list_admins(), lang),
        Para(t("hint_admins_cmds", lang)),
        Footer("ℹ️ " + t("txt_admins_note", lang)),
    ).render()


def _derive_label(user) -> Optional[str]:
    """Best human label for a resolved/shared user: real name, else @username."""
    name = " ".join(
        p
        for p in (getattr(user, "first_name", None), getattr(user, "last_name", None))
        if p
    )
    uname = getattr(user, "username", None)
    return name or (f"@{uname}" if uname else None)


def _add_shared_users(users, lang: str = "en") -> RichText:
    """Add admins picked via the request_users keyboard (a list of User-likes)."""
    if not users:
        return _err(t("err_no_user_picked", lang))
    doc = Doc()
    for u in users:
        uid = getattr(u, "id", None)
        if uid is None:
            continue
        ok, msg = admin_store.add_admin(str(uid), _derive_label(u))
        doc.add(Status(ok, esc(msg)))
    if not doc.blocks:
        return _err(t("err_no_valid_user", lang))
    return doc.render()


async def _cmd_addadmin(args: List[str], pyro=None, lang: str = "en") -> RichText:
    if not args:
        return _usage("/addadmin &lt;user_id|@username&gt; [label]", lang)
    target = args[0].strip()
    label = " ".join(args[1:]).strip() or None

    # Numeric id (incl. negative) → add directly.
    if target and target != "-" and target.lstrip("-").isdigit():
        return _outcome(*admin_store.add_admin(target, label))

    # Otherwise treat it as a username, resolved best-effort via the live client.
    if pyro is None:
        return _err(t("err_username_lookup", lang))
    uname = target.lstrip("@")
    try:
        user = await pyro.get_users(uname)
    except Exception as exc:
        return _err(
            t("err_resolve", lang, target=esc(target)),
            Para(esc(exc)),
            Para(t("txt_resolve_hint", lang)),
        )
    uid = getattr(user, "id", None)
    if uid is None:
        return _err(t("err_resolve", lang, target=esc(target)))
    return _outcome(*admin_store.add_admin(str(uid), label or _derive_label(user)))


def _cmd_removeadmin(args: List[str], lang: str = "en") -> RichText:
    if len(args) != 1:
        return _usage("/removeadmin &lt;user_id&gt;", lang)
    return _outcome(*admin_store.remove_admin(args[0]))


# --- System -------------------------------------------------------------------


def _refresh_rich_env() -> None:
    """Copy the rich-message switches from ``.env`` into ``os.environ``.

    ``load_dotenv`` runs once at import, so ``CONFIG.reload()`` alone never sees
    an out-of-band ``.env`` edit. /reload is where an operator expects such an
    edit to land, and the kill switch is the one setting that has to be
    flippable that way (e.g. if rich replies stop arriving at all). Only these
    keys are copied, and only when present — never removed.
    """
    try:
        from dotenv import dotenv_values

        values = dotenv_values(env_store._root_env_path())
    except Exception:  # pragma: no cover - defensive
        log.warning("could not re-read .env for the rich-message switch", exc_info=True)
        return
    for key in (rich_html.RICH_ENV, rich_html.LEGACY_RICH_ENV):
        value = values.get(key)
        if value is not None:
            os.environ[key] = value


def _cmd_reload(lang: str = "en") -> RichText:
    _refresh_rich_env()
    err = _reload_or_error("reload", lang)
    if err:
        return err
    reload_prompt_template()
    return _ok(t("ok_reload", lang))


def _cmd_setlang(args: List[str], msg, lang: str = "en") -> RichText:
    """Set the caller's per-admin menu language (text-command parity with the menu)."""
    uid = getattr(getattr(msg, "from_user", None), "id", None)
    if uid is None:
        return _err(t("alert_error", lang))
    if len(args) != 1 or args[0].strip().lower() not in admin_i18n.LOCALES:
        return _usage("/setlang &lt;" + esc(" | ".join(admin_i18n.LOCALES)) + "&gt;", lang)
    new_lang = args[0].strip().lower()
    admin_prefs.set_lang(uid, new_lang)
    return _ok(t("ok_lang", new_lang))


def _unknown_reply(cmd: str, lang: str = "en") -> RichText:
    return Doc(
        Status(None, t("err_unknown_cmd", lang)),
        Para(f"<code>{esc(cmd)}</code>") if cmd else None,
        Footer(t("hint_unknown", lang)),
    ).render()


async def _run_richcheck(client, msg, lang: str = "en") -> None:
    """Send every ``rich_html.PROBES`` document and report which ones Telegram takes.

    The rich dialect is validated only server-side, so this is the one way to
    check it for real: each probe goes to this chat as a real rich message and
    is deleted again. Bypasses the circuit breaker on purpose.
    """
    from pyrogram import types as pyro_types

    from translator.services import admin_menu  # lazy: avoid import cycle

    if not admin_menu.HAS_RICH_MESSAGES:
        await admin_send.reply(
            msg, _err(t("err_richcheck", lang), Para(t("txt_rich_unsupported", lang)))
        )
        return
    chat_id = getattr(getattr(msg, "chat", None), "id", None)
    rows = []
    for name, probe in rich_html.PROBES:
        try:
            sent = await client.send_rich_message(
                chat_id, pyro_types.InputRichMessage(html=probe)
            )
        except Exception as exc:
            rows.append(["❌", f"<code>{esc(name)}</code>", esc(str(exc)[:200])])
        else:
            rows.append(["✅", f"<code>{esc(name)}</code>", ""])
            if sent is not None:
                try:
                    await client.delete_messages(chat_id, sent.id)
                except Exception:
                    pass
        await asyncio.sleep(0.3)  # stay well clear of flood limits
    doc = Doc(
        Heading(t("h_richcheck", lang)),
        Table(
            ["", t("col_feature", lang), t("col_result", lang)],
            rows,
            classic_row=lambda r: " ".join(c for c in r if c),
        ),
        Footer(t("hint_richcheck", lang)),
    )
    await admin_send.reply(msg, doc)


async def _reply_for_wizard(msg, uid, reply, lang: str, *, before: Sequence = ()) -> None:
    """Send a wizard reply with the keyboard that step needs.

    The two id steps get Telegram's native channel picker; finishing (or
    cancelling) puts the main menu keyboard back, because the picker keyboard is
    one-shot and would otherwise leave the admin with no buttons at all.
    """
    from translator.services import admin_menu  # lazy: avoid import cycle

    after = []
    step = admin_wizard.current_step(uid)
    if step in ("src", "dst"):
        markup = admin_menu.build_channel_picker_keyboard(lang)
        # No picker on this kurigram → don't advertise a button that isn't there.
        if markup is not None:
            after.append(Para(t("wiz_pick_hint", lang)))
    elif step is None:
        markup = admin_menu.to_reply_markup(admin_menu.build_reply_keyboard(lang), lang)
    else:
        markup = None
    try:
        await admin_send.reply(
            msg, compose(reply, before=before, after=after), reply_markup=markup
        )
    except Exception:
        log.exception("failed to send wizard reply")


async def handle_command(
    msg,
    *,
    anthropic=None,
    sender=None,
    recorder=None,
    query_queue=None,
    start_ts=None,
    pyro=None,
) -> RichText:
    """Parse one admin DM and return the reply (a RichText). Never raises."""
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
        return Doc(Para(t("prompt_for_help", lang))).render()
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
    if cmd == "/logs":
        return _cmd_logs(lang)
    if cmd == "/setmodel":
        return _cmd_setmodel(args, lang)
    if cmd == "/settemp":
        return _cmd_settemp(args, lang)
    if cmd == "/setmaxtokens":
        return _cmd_setmaxtokens(args, lang)
    if cmd == "/seteffort":
        return _cmd_seteffort(args, lang)
    if cmd == "/setloglevel":
        return _cmd_setloglevel(args, lang)
    if cmd == "/setlang":
        return _cmd_setlang(args, msg, lang)
    if cmd == "/setrich":
        return _cmd_setrich(args, lang)
    if cmd == "/richcheck":
        # Needs the live client; the Pyrogram dispatcher serves it before here.
        return _err(t("err_richcheck", lang))
    if cmd == "/cancel":
        if uid is not None:
            admin_wizard.cancel(uid)
        return admin_wizard.cancelled(lang)
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
        return await _cmd_addadmin(args, pyro=pyro, lang=lang)
    if cmd == "/removeadmin":
        return _cmd_removeadmin(args, lang)
    if cmd == "/reload":
        return _cmd_reload(lang)
    return _unknown_reply(cmd, lang)


# --- Native command menu (setMyCommands) --------------------------------------

# The commands published to Telegram's "/" autocomplete and the ☰ menu button,
# in the order operators actually reach for them. Each entry is
# (command, i18n key for its one-line description).
#
# These are published with BotCommandScopeChat per admin, never globally: the
# command list is the map of the whole control surface, and a non-admin who can
# DM the bot should not be handed it. That matches the group-1 reject handler
# below, which keeps the surface silent for everyone else.
COMMAND_SPECS = (
    ("menu", "cmd_desc_menu"),
    ("status", "cmd_desc_status"),
    ("stats", "cmd_desc_stats"),
    ("channels", "cmd_desc_channels"),
    ("logs", "cmd_desc_logs"),
    ("prompt", "cmd_desc_prompt"),
    ("setmodel", "cmd_desc_setmodel"),
    ("seteffort", "cmd_desc_seteffort"),
    ("setmaxtokens", "cmd_desc_setmaxtokens"),
    ("settemp", "cmd_desc_settemp"),
    ("setprompt", "cmd_desc_setprompt"),
    ("cost", "cmd_desc_cost"),
    ("setloglevel", "cmd_desc_setloglevel"),
    ("setlang", "cmd_desc_setlang"),
    ("setrich", "cmd_desc_setrich"),
    ("richcheck", "cmd_desc_richcheck"),
    ("addchannel", "cmd_desc_addchannel"),
    ("editchannel", "cmd_desc_editchannel"),
    ("removechannel", "cmd_desc_removechannel"),
    ("admins", "cmd_desc_admins"),
    ("addadmin", "cmd_desc_addadmin"),
    ("removeadmin", "cmd_desc_removeadmin"),
    ("reload", "cmd_desc_reload"),
    ("cancel", "cmd_desc_cancel"),
    ("help", "cmd_desc_help"),
)


def build_bot_commands(lang: str = "en"):
    """``COMMAND_SPECS`` as Pyrogram ``BotCommand`` objects in ``lang``."""
    from pyrogram.types import BotCommand

    return [BotCommand(name, t(key, lang)) for name, key in COMMAND_SPECS]


async def publish_commands_for(pyro, uid) -> bool:
    """Publish the admin command list into one admin's private chat.

    Scoped to that chat, in that admin's own menu language. Returns True on
    success; **never raises** — this runs at startup right after ``pyro.start()``,
    so anything that escapes here stops the bot from starting at all. The imports
    are deliberately inside the try: an older kurigram that lacks either name
    raises ImportError, and that has to be the logged warning this docstring
    promises rather than a silent relay outage.
    """
    lang = admin_prefs.get_lang(uid) or admin_i18n.DEFAULT_LANG
    try:
        from pyrogram.types import BotCommandScopeChat, MenuButtonCommands

        await pyro.set_bot_commands(
            build_bot_commands(lang), scope=BotCommandScopeChat(chat_id=uid)
        )
        # Point the ☰ button at that list instead of the default "what can this
        # bot do?" blurb.
        await pyro.set_chat_menu_button(chat_id=uid, menu_button=MenuButtonCommands())
        return True
    except Exception:
        log.warning("could not publish command menu for admin %s", uid, exc_info=True)
        return False


async def publish_admin_commands(pyro) -> int:
    """Publish the command menu to every configured admin. Returns the count.

    Called once after ``pyro.start()`` (the client must be connected) and again
    whenever an admin switches menu language, so the "/" list follows the menu.
    """
    published = 0
    for uid in CONFIG.ADMIN_CHAT_IDS:
        if await publish_commands_for(pyro, uid):
            published += 1
    log.info("published command menu to %d/%d admins", published, len(CONFIG.ADMIN_CHAT_IDS))
    return published


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

    # Pseudo-commands that answer with an inline menu instead of plain text.
    _MENU_ENTRIES = {
        "/settings": admin_menu.settings_entry,
        "/aimenu": admin_menu.ai_entry,
        "/adminsmenu": admin_menu.admins_entry,
        "/channelsmenu": admin_menu.channels_entry,
    }

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
                reply = _add_shared_users(getattr(shared, "users", None) or [], lang)
            except Exception as exc:
                log.exception("add admin via picker failed")
                reply = _err(t("err_command", lang), Para(esc(exc)))
            try:
                await admin_send.reply(
                    msg,
                    reply,
                    reply_markup=admin_menu.to_reply_markup(
                        admin_menu.build_reply_keyboard(lang), lang
                    ),
                )
            except Exception:
                log.exception("failed to send add-admin reply")
            return

        # A channel picked via the "📡 Pick a channel…" keyboard likewise arrives
        # as a service message carrying chat_shared. Feed its id into the wizard
        # exactly as if the admin had typed it, so both routes commit through the
        # same validation and the same _cmd_addchannel.
        picked = getattr(msg, "chat_shared", None)
        if picked is not None:
            chat = getattr(picked, "chat", None)
            chat_id = getattr(chat, "id", None)
            if chat_id is None or uid is None or not admin_wizard.is_active(uid):
                # Nothing is waiting for it, so acting would write a channel pair
                # nobody asked for. Stay silent rather than guess.
                log.info("ignoring chat_shared with no wizard pending (uid=%s)", uid)
                return
            title = getattr(chat, "title", None) or str(chat_id)
            picked_line = Para(t("wiz_picked", lang, title=esc(title), id=chat_id))
            reply = admin_wizard.feed(uid, str(chat_id), lang)
            await _reply_for_wizard(msg, uid, reply, lang, before=[picked_line])
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
                await admin_send.reply(
                    msg,
                    menu_greeting(lang),
                    reply_markup=admin_menu.to_reply_markup(
                        admin_menu.build_reply_keyboard(lang), lang
                    ),
                )
            except Exception:
                log.exception("failed to send menu")
            return
        if token == "/richcheck":
            try:
                await _run_richcheck(client, msg, lang)
            except Exception:
                log.exception("rich check failed")
            return
        # Inline-menu entrypoints: same shape, so they share one path rather than
        # four copies that have to be kept in step.
        entry = _MENU_ENTRIES.get(token)
        if entry is not None:
            title, rows = entry(lang)
            try:
                await admin_send.reply(msg, title, rows=rows)
            except Exception:
                log.exception("failed to send %s menu", token)
            return

        # Is this message a typed answer to an in-progress wizard? Captured
        # *before* handle_command, which advances (or ends) the wizard — the reply
        # needs that step's keyboard, so it can't take the plain path below.
        answering_wizard = (
            uid is not None
            and not resolved.startswith("/")
            and admin_wizard.is_active(uid)
        )

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
            reply = _err(t("err_command", lang), Para(esc(exc)))

        if answering_wizard or token == "/cancel":
            await _reply_for_wizard(msg, uid, reply, lang)
            return
        # A typed /setlang has to re-skin the persistent keyboard and republish
        # the "/" list, the same way the inline Language button already does —
        # otherwise the two routes leave the surface in different languages.
        if token == "/setlang":
            new_lang = admin_prefs.get_lang(uid) if uid is not None else lang
            try:
                await admin_send.reply(
                    msg,
                    reply,
                    reply_markup=admin_menu.to_reply_markup(
                        admin_menu.build_reply_keyboard(new_lang), new_lang
                    ),
                )
            except Exception:
                log.exception("failed to send setlang reply")
            if uid is not None:
                await publish_commands_for(pyro, uid)
            return
        try:
            await admin_send.reply(msg, reply)
        except Exception:
            log.exception("failed to send admin reply")

    # Defense-in-depth: any private DM that is NOT from an admin is explicitly
    # logged and dropped here (group 1 runs independently of the group-0 admin
    # dispatcher). No reply is sent — the admin surface stays invisible to
    # non-admins. This makes the rejection intentional rather than "no handler
    # happened to match".
    @pyro.on_message(filters.private, group=1)
    async def _reject_unauthorized(client, msg):  # noqa: ANN001
        uid = getattr(getattr(msg, "from_user", None), "id", None)
        if uid is not None and uid in CONFIG.ADMIN_CHAT_IDS:
            return  # admin — already served by the group-0 dispatcher
        log.warning("Ignoring admin DM from unauthorized user_id=%s", uid)

    # Inline-button presses (the Settings tree) arrive as callback queries.
    admin_menu.register_callback_handler(
        pyro, start_ts=start_ts, query_queue=query_queue
    )

    return _dispatch
