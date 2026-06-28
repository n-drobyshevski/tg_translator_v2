"""Localized strings for the admin DM interface (menu chrome + command replies).

The bot's operator surface (``admin_commands`` + ``admin_menu``) was English-only
with every label inlined. This module is the single string catalog plus a lookup
helper :func:`t`, so the menu can render in either English (``en``, the default)
or Belarusian (``be``). A per-admin language preference is stored separately in
:mod:`translator.services.admin_prefs`; callers resolve it at the two Pyrogram
entry points and pass ``lang`` down.

Design rules baked in here:

* The ``en`` table is **byte-identical** to the literals that used to live in the
  command/menu code — existing tests assert on exact English substrings and on
  the ``✅`` / ``❌`` prefixes (kept *inside* the strings so the alert-detection
  ``text.startswith("✅")`` logic is unaffected).
* The ``be`` table may be **partial**: :func:`t` falls back to ``en`` for any
  missing key, then to the raw key, and never raises — so a half-translated
  locale always renders something sensible.
* Interpolation uses **named** placeholders only (``{name}``, ``{src}`` …) so a
  bad/extra placeholder degrades to the un-formatted string instead of crashing.
* Technical tokens are intentionally *not* translated: command names, env-var
  keys (``ANTHROPIC_MODEL`` …), model ids, HTML tags, and ``{placeholders}``.

This module imports nothing from the rest of the package, so it is trivially
unit-testable and free of import cycles.
"""

from __future__ import annotations

from typing import Dict

LOCALES = ("en", "be")
DEFAULT_LANG = "en"


# --- English (authoritative; mirrors the original literals verbatim) ----------

_EN: Dict[str, str] = {
    # Persistent reply-keyboard labels.
    "btn_status": "📊 Status",
    "btn_stats": "📈 Stats",
    "btn_channels": "📡 Channels",
    "btn_admins": "👤 Admins",
    "btn_prompt": "📝 Prompt",
    "btn_reload": "🔄 Reload",
    "btn_help": "❓ Help",
    "btn_settings": "🛠️ Settings",
    "btn_back_to_menu": "🔙 Back to menu",
    "btn_pick_user": "👤 Pick a user…",
    "btn_add_channel_pair": "➕ Add channel pair",
    "btn_language": "🌐 Language",
    "btn_back": "◀️ Back",
    "btn_yes_remove": "✅ Yes, remove",
    "btn_no_back": "◀️ No, back",
    "btn_add_admin": "➕ Add admin",
    "btn_cancel": "🚫 Cancel",
    # Menu chrome.
    "menu_greeting": (
        "<b>📋 Relay bot menu</b>\n"
        "Tap a button below, or open 🛠️ Settings to view and change configuration.\n"
        "Typed commands still work — tap ❓ Help to see them."
    ),
    "add_admin_prompt": (
        "<b>➕ Add admin</b>\n"
        "Tap “👤 Pick a user…” to choose someone from your chats — I'll capture their "
        "id and name automatically.\n"
        "Or type <code>/addadmin &lt;user_id&gt;</code> or "
        "<code>/addadmin @username</code> [label]."
    ),
    # Inline Settings tree.
    "settings_title": "<b>⚙️ Settings</b>\n\n{summary}\n\nPick a setting to change.",
    "btn_ai": "🤖 AI Settings",
    "settings_btn_model": "🤖 Set Model",
    "settings_btn_temp": "🌡️ Temperature",
    "settings_btn_tokens": "🔢 Max Tokens",
    "settings_btn_cost": "💰 Cost & billing",
    "settings_btn_log": "🪵 Log Level",
    "settings_btn_rmch": "🗑️ Remove Channel",
    "settings_btn_close": "✖️ Close",
    # AI Settings submenu (model / temperature / max-tokens / cost).
    "ai_title": (
        "<b>🤖 AI Settings</b>\n"
        "Model: {model}\n"
        "Temperature: {temp}\n"
        "Max tokens: {tokens}\n\n"
        "Tune the translation model and review cost below."
    ),
    "model_title": (
        "<b>🤖 Model</b>\n"
        "Current: {current}\n\n"
        "Capability vs. price (USD per 1M tokens, input / output):\n"
        "• Haiku 4.5 — $1 / $5 — fastest &amp; cheapest (default)\n"
        "• Sonnet 4.6 — $3 / $15 — balanced\n"
        "• Opus 4.8 — $5 / $25 — most capable, priciest\n"
        "Each post bills input (source + prompt) + output (translation) tokens, "
        "so a higher tier costs several× more per post.\n"
        "Pick a preset, or type <code>/setmodel &lt;id&gt;</code> for any other."
    ),
    "temp_title": (
        "<b>🌡️ Temperature</b>\n"
        "Current: {current}\n\n"
        "Controls randomness in word choice:\n"
        "• 0 — deterministic &amp; literal. Best for faithful translation — same "
        "input gives the same output, least drift from the source.\n"
        "• 0.3–0.7 — light variation; more natural phrasing but may stray.\n"
        "• 1.0 — most creative/varied; highest risk of rewording or drift.\n"
        "💲 Cost: none — temperature changes wording, not token usage or price.\n"
        "Pick a value, or type <code>/settemp &lt;0..1&gt;</code>."
    ),
    "tokens_title": (
        "<b>🔢 Max Tokens</b>\n"
        "Current: {current}\n\n"
        "Hard ceiling on the <b>output</b> length of one translation "
        "(≈ ¾ of a word per token):\n"
        "• Too low → long posts get cut off mid-sentence.\n"
        "• Higher → no downside; it's a cap, not a reservation.\n"
        "💲 Cost: you pay only for output tokens actually generated, at the "
        "model's output rate — so set it a little above your longest post, not "
        "arbitrarily high.\n"
        "Pick a value, or type <code>/setmaxtokens &lt;1..8192&gt;</code>."
    ),
    # Cost / billing view (rendered by services/cost_report.render).
    "cost_title": "<b>💰 Cost &amp; billing</b>",
    "cost_mtd_admin": "Month-to-date ({month}): <b>${amount}</b> (Anthropic billing)",
    "cost_mtd_local": "Month-to-date ({month}): <b>~${amount}</b> (local estimate)",
    "cost_billing_next": "Next invoice: ~{date} (API usage is billed monthly)",
    "cost_breakdown_header": "<b>By model (this month)</b>",
    "cost_model_row": "{model}: {in_tok} in / {out_tok} out → ~${cost}",
    "cost_none": "(no token usage recorded yet this month)",
    "cost_caveat": (
        "ℹ️ Local estimates price recorded token usage and cover only posts "
        "translated since cost tracking was enabled. The Anthropic figure, when "
        "shown, is authoritative."
    ),
    "btn_cost_refresh": "🔄 Refresh",
    "log_title": (
        "<b>🪵 Log Level</b>\n"
        "Current: {current}\nPick a level."
    ),
    "rmch_menu_title": "<b>🗑️ Remove Channel</b>\nPick a channel to stop relaying.",
    "rmch_none": "(no removable channels)",
    "rmch_confirm_title": "<b>🗑️ Remove '{name}'?</b>\nThis stops the relay for that pair.",
    "admins_menu_title": "<b>👤 Admins</b>",
    "admins_menu_help": "Tap an admin to remove. Add via <code>/addadmin &lt;id&gt; [label]</code>.",
    "admin_confirm_title": (
        "<b>👤 Remove admin <code>{uid}</code>?</b>\n"
        "They lose DM control and stop receiving alerts."
    ),
    "lang_title": "<b>🌐 Language</b>\nPick the menu language.",
    "lang_en": "English",
    "lang_be": "Беларуская",
    "lang_switched": "✅ Menu language updated.",
    "channels_menu_hint": "\n\nTap ➕ to add a new pair step by step.",
    "menu_closed": "✅ Menu closed. Send /menu to reopen.",
    "menu_expired": "This menu expired. Tap 🛠️ Settings or send /menu to reopen.",
    # Alert toasts (callback_query.answer).
    "alert_saved": "Saved",
    "alert_removed": "Removed",
    "alert_error": "Error",
    "alert_closed": "Closed",
    "alert_expired": "Expired",
    "alert_lang": "Language",
    # Common fragments.
    "common_none": "(none)",
    # Help.
    "help_text": (
        "<b>Relay bot — admin commands</b>\n"
        "/menu — open the button menu (easiest)\n"
        "/help — this message\n"
        "/status — uptime, channels, queue depth, recent failures\n"
        "/stats [days] — relay counts &amp; failures (default 7)\n"
        "/cost — token usage, estimated cost &amp; next invoice\n"
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
        "/admins — list admins\n"
        "/addadmin &lt;user_id|@username&gt; [label]\n"
        "/removeadmin &lt;user_id&gt;\n"
        "/reload — re-read .env + prompt template\n"
        "(/setprompt, /addchannel, /editchannel need typed input)"
    ),
    # /status.
    "status": (
        "<b>Status</b>\n"
        "Uptime: {uptime}\n"
        "Pyrogram connected: {connected}\n"
        "Source channels: {sources}\n"
        "Metadata queue depth: {queue}\n"
        "Model: {model}"
    ),
    # /status — recent failures section (pull-based; replaces push alerts).
    "status_fail_header": "<b>Recent failures (last 7d) — {count}</b>",
    "status_fail_none": "<b>Recent failures</b>\nNone in the last 7 days ✅",
    "status_fail_line": "{time} UTC · {channel} · {reason}",
    # /stats.
    "stats_usage": "❌ Usage: /stats [days]",
    "stats_days_range": "❌ days must be 1..30",
    "stats_unavailable": "❌ Stats unavailable: {err}",
    "stats_header": (
        "<b>Stats — last {days}d</b>\n"
        "Relayed events: {total}\n"
        "Failures: {failures}\n"
        "\n"
        "<b>By source channel</b>"
    ),
    # /config (the summary block embedded in Settings).
    "cfg_summary": (
        "Model: {model}\n"
        "Temperature: {temp}\n"
        "Max Tokens: {tokens}\n"
        "Log Level: {log}\n"
        "Admin IDs: {admins}\n"
        "Channels: {channels}"
    ),
    # /channels.
    "channels_title": "<b>Channel pairs</b>",
    "channels_line": "{name}: src {src} → dst {dst}",
    # /prompt.
    "prompt_none": "(no prompt template file)",
    "prompt_body": "<b>Prompt template</b>\n<pre>{body}</pre>",
    "prompt_menu_hint": (
        "\n\nTo change it, send <code>/setprompt</code> followed by the new "
        "template on new lines, or reply to a message containing it."
    ),
    # /setmodel.
    "setmodel_usage": "❌ Usage: /setmodel &lt;model&gt;",
    "setmodel_ok": "✅ ANTHROPIC_MODEL = {model}",
    # /settemp.
    "settemp_usage": "❌ Usage: /settemp &lt;0..1&gt;",
    "settemp_nan": "❌ Temperature must be a number 0..1",
    "settemp_range": "❌ Temperature must be 0..1",
    "settemp_ok": "✅ ANTHROPIC_TEMPERATURE = {val}",
    # /setmaxtokens.
    "settokens_usage": "❌ Usage: /setmaxtokens &lt;1..8192&gt;",
    "settokens_nan": "❌ max_tokens must be an integer",
    "settokens_range": "❌ max_tokens must be 1..8192",
    "settokens_ok": "✅ ANTHROPIC_MAX_TOKENS = {val}",
    # /setloglevel.
    "setlog_usage": "❌ Usage: /setloglevel &lt;LEVEL&gt;",
    "setlog_invalid": "❌ level must be one of {levels}",
    "setlog_ok": "✅ LOG_LEVEL = {level} (applied live)",
    # /setprompt.
    "setprompt_usage": (
        "❌ Send the template after the command on new lines, "
        "or reply to a message containing it."
    ),
    "setprompt_invalid": "❌ {err}",
    "setprompt_ok": "✅ Prompt template updated and reloaded live.",
    # Reload wrapper (shared).
    "reload_failed": "❌ {action} failed on reload: {err}",
    # /addchannel.
    "addch_usage": (
        "❌ Usage: /addchannel &lt;name&gt; &lt;src_id&gt; &lt;dst_id&gt; "
        "[src_name] [dst_name]"
    ),
    "addch_bad_name": "❌ name must match [a-z0-9_]+",
    "addch_dup": "❌ channel '{name}' already exists (use /editchannel)",
    "addch_bad_int": "❌ src_id and dst_id must be integers",
    "addch_ok": (
        "✅ Added channel '{name}': src {src} → dst {dst}\n"
        "⚠️ Make sure the bot is an admin/member of the source channel, "
        "or Telegram won't deliver its posts."
    ),
    # /editchannel.
    "editch_usage": "❌ Usage: /editchannel &lt;name&gt; &lt;src_id&gt; &lt;dst_id&gt;",
    "editch_unknown": "❌ unknown channel '{name}'",
    "editch_ok": "✅ Updated '{name}': src {src} → dst {dst}",
    # /removechannel.
    "rmch_usage": "❌ Usage: /removechannel &lt;name&gt;",
    "rmch_protected": "❌ '{name}' is protected and cannot be removed",
    "rmch_ok": "✅ Removed channel '{name}'",
    # /admins.
    "admins_title": "<b>Admins</b>",
    "admins_help": (
        "Add: /addadmin &lt;user_id&gt; [label] · Remove: /removeadmin &lt;user_id&gt;"
    ),
    "admins_note": "ℹ️ A name resolves only if that user has DM'd the bot.",
    # /reload.
    "reload_ok": "✅ Reloaded .env config and prompt template.",
    # handle_command fallbacks.
    "prompt_for_help": "Send /help for the command list, or /menu for buttons.",
    "unknown_cmd": "❓ Unknown command {cmd}. Send /help.",
    # Add-channel wizard.
    "wiz_prompt_name": (
        "<b>➕ Add channel pair (1/3)</b>\n"
        "Send the channel <b>name</b> (letters, digits, underscore), or 🚫 Cancel."
    ),
    "wiz_prompt_src": (
        "<b>➕ Add channel pair (2/3)</b>\n"
        "Send the <b>source</b> channel id (e.g. <code>-1001234567890</code>)."
    ),
    "wiz_prompt_dst": (
        "<b>➕ Add channel pair (3/3)</b>\n"
        "Send the <b>destination</b> (English) channel id."
    ),
    "wiz_bad_name": "❌ name must match [a-z0-9_]+. Send a valid name, or /cancel.",
    "wiz_bad_int": "❌ That must be an integer channel id. Try again, or /cancel.",
    "wiz_dup_name": "❌ channel '{name}' already exists. Send a different name, or /cancel.",
    "wiz_cancelled": "✅ Cancelled. No channel was added.",
}


# --- Belarusian ---------------------------------------------------------------
# Partial-by-design is allowed (missing keys fall back to English). These cover
# the whole menu chrome and command replies; a native-fluency review is still
# recommended before considering `be` final (see the plan / PR notes).

_BE: Dict[str, str] = {
    # Persistent reply-keyboard labels.
    "btn_status": "📊 Стан",
    "btn_stats": "📈 Статыстыка",
    "btn_channels": "📡 Каналы",
    "btn_admins": "👤 Адміны",
    "btn_prompt": "📝 Промпт",
    "btn_reload": "🔄 Перазагрузка",
    "btn_help": "❓ Дапамога",
    "btn_settings": "🛠️ Налады",
    "btn_back_to_menu": "🔙 Назад у меню",
    "btn_pick_user": "👤 Выбраць карыстальніка…",
    "btn_add_channel_pair": "➕ Дадаць пару каналаў",
    "btn_language": "🌐 Мова",
    "btn_back": "◀️ Назад",
    "btn_yes_remove": "✅ Так, выдаліць",
    "btn_no_back": "◀️ Не, назад",
    "btn_add_admin": "➕ Дадаць адміна",
    "btn_cancel": "🚫 Скасаваць",
    # Menu chrome.
    "menu_greeting": (
        "<b>📋 Меню рэлэй-бота</b>\n"
        "Націсніце кнопку ніжэй або адкрыйце 🛠️ Налады, каб прагледзець і змяніць "
        "канфігурацыю.\n"
        "Тэкставыя каманды таксама працуюць — націсніце ❓ Дапамога."
    ),
    "add_admin_prompt": (
        "<b>➕ Дадаць адміна</b>\n"
        "Націсніце «👤 Выбраць карыстальніка…», каб выбраць кагосьці са сваіх чатаў — "
        "я аўтаматычна вазьму яго id і імя.\n"
        "Або ўвядзіце <code>/addadmin &lt;user_id&gt;</code> ці "
        "<code>/addadmin @username</code> [метка]."
    ),
    # Inline Settings tree.
    "settings_title": "<b>⚙️ Налады</b>\n\n{summary}\n\nВыберыце налада для змены.",
    "btn_ai": "🤖 Налады ІІ",
    "settings_btn_model": "🤖 Задаць мадэль",
    "settings_btn_temp": "🌡️ Тэмпература",
    "settings_btn_tokens": "🔢 Макс. токенаў",
    "settings_btn_cost": "💰 Кошт і білінг",
    "settings_btn_log": "🪵 Узровень логаў",
    "settings_btn_rmch": "🗑️ Выдаліць канал",
    "settings_btn_close": "✖️ Закрыць",
    # AI Settings submenu.
    "ai_title": (
        "<b>🤖 Налады ІІ</b>\n"
        "Мадэль: {model}\n"
        "Тэмпература: {temp}\n"
        "Макс. токенаў: {tokens}\n\n"
        "Наладзьце мадэль перакладу і прагледзьце кошт ніжэй."
    ),
    "model_title": (
        "<b>🤖 Мадэль</b>\n"
        "Бягучая: {current}\n\n"
        "Магчымасці і цана (USD за 1М токенаў, увод / вывад):\n"
        "• Haiku 4.5 — $1 / $5 — найхутчэйшая і таннейшая (па змаўчанні)\n"
        "• Sonnet 4.6 — $3 / $15 — збалансаваная\n"
        "• Opus 4.8 — $5 / $25 — найбольш магутная, найдаражэйшая\n"
        "Кожны пост білінгуецца за токены ўводу (крыніца + промпт) + вываду "
        "(пераклад), таму вышэйшы клас каштуе ў некалькі разоў больш за пост.\n"
        "Выберыце прэсет або ўвядзіце <code>/setmodel &lt;id&gt;</code> для іншай."
    ),
    "temp_title": (
        "<b>🌡️ Тэмпература</b>\n"
        "Бягучая: {current}\n\n"
        "Кіруе выпадковасцю ў выбары слоў:\n"
        "• 0 — дэтэрмінавана і літаральна. Найлепш для дакладнага перакладу — "
        "аднолькавы ўвод дае аднолькавы вывад, найменшае адхіленне ад крыніцы.\n"
        "• 0.3–0.7 — лёгкая варыяцыя; больш натуральна, але можа адхіляцца.\n"
        "• 1.0 — найбольш творча/зменліва; найвышэйшая рызыка адхілення.\n"
        "💲 Кошт: няма — тэмпература змяняе фармулёўку, а не колькасць токенаў.\n"
        "Выберыце значэнне або ўвядзіце <code>/settemp &lt;0..1&gt;</code>."
    ),
    "tokens_title": (
        "<b>🔢 Макс. токенаў</b>\n"
        "Бягучае: {current}\n\n"
        "Жорсткая мяжа на даўжыню <b>вываду</b> аднаго перакладу "
        "(≈ ¾ слова на токен):\n"
        "• Занадта мала → доўгія пасты абразаюцца на сярэдзіне сказа.\n"
        "• Больш → без мінусаў; гэта мяжа, а не рэзерв.\n"
        "💲 Кошт: вы плаціце толькі за фактычна згенераваныя токены вываду па "
        "стаўцы вываду мадэлі — стаўце крыху вышэй за самы доўгі пост, а не "
        "адвольна шмат.\n"
        "Выберыце значэнне або ўвядзіце <code>/setmaxtokens &lt;1..8192&gt;</code>."
    ),
    # Cost / billing view.
    "cost_title": "<b>💰 Кошт і білінг</b>",
    "cost_mtd_admin": "З пачатку месяца ({month}): <b>${amount}</b> (білінг Anthropic)",
    "cost_mtd_local": "З пачатку месяца ({month}): <b>~${amount}</b> (лакальная ацэнка)",
    "cost_billing_next": "Наступны рахунак: ~{date} (API білінгуецца штомесяц)",
    "cost_breakdown_header": "<b>Па мадэлях (гэты месяц)</b>",
    "cost_model_row": "{model}: {in_tok} увод / {out_tok} вывад → ~${cost}",
    "cost_none": "(пакуль няма выкарыстання токенаў у гэтым месяцы)",
    "cost_caveat": (
        "ℹ️ Лакальныя ацэнкі разлічваюць запісанае выкарыстанне токенаў і "
        "ахопліваюць толькі пасты, перакладзеныя пасля ўключэння ўліку кошту. "
        "Лічба Anthropic, калі паказана, дакладная."
    ),
    "btn_cost_refresh": "🔄 Абнавіць",
    "log_title": (
        "<b>🪵 Узровень логаў</b>\n"
        "Бягучы: {current}\nВыберыце ўзровень."
    ),
    "rmch_menu_title": "<b>🗑️ Выдаліць канал</b>\nВыберыце канал, каб спыніць рэтрансляцыю.",
    "rmch_none": "(няма каналаў для выдалення)",
    "rmch_confirm_title": "<b>🗑️ Выдаліць '{name}'?</b>\nГэта спыніць рэтрансляцыю гэтай пары.",
    "admins_menu_title": "<b>👤 Адміны</b>",
    "admins_menu_help": "Націсніце на адміна, каб выдаліць. Дадаць праз <code>/addadmin &lt;id&gt; [метка]</code>.",
    "admin_confirm_title": (
        "<b>👤 Выдаліць адміна <code>{uid}</code>?</b>\n"
        "Ён страціць кіраванне праз DM і перастане атрымліваць абвесткі."
    ),
    "lang_title": "<b>🌐 Мова</b>\nВыберыце мову меню.",
    "lang_en": "English",
    "lang_be": "Беларуская",
    "lang_switched": "✅ Мову меню зменена.",
    "channels_menu_hint": "\n\nНацісніце ➕, каб дадаць новую пару пакрокава.",
    "menu_closed": "✅ Меню закрыта. Дашліце /menu, каб адкрыць зноў.",
    "menu_expired": "Гэта меню састарэла. Націсніце 🛠️ Налады або дашліце /menu.",
    # Alert toasts.
    "alert_saved": "Захавана",
    "alert_removed": "Выдалена",
    "alert_error": "Памылка",
    "alert_closed": "Закрыта",
    "alert_expired": "Састарэла",
    "alert_lang": "Мова",
    # Common fragments.
    "common_none": "(няма)",
    # Help.
    "help_text": (
        "<b>Рэлэй-бот — адмінскія каманды</b>\n"
        "/menu — адкрыць меню з кнопкамі (найпрасцей)\n"
        "/help — гэта паведамленне\n"
        "/status — час працы, каналы, чарга, нядаўнія збоі\n"
        "/stats [дні] — лік рэтрансляцый і збояў (па змаўчанні 7)\n"
        "/cost — выкарыстанне токенаў, ацэнка кошту і наступны рахунак\n"
        "/channels — наладжаныя пары каналаў\n"
        "/prompt — бягучы шаблон промпта\n"
        "/setmodel &lt;model&gt;\n"
        "/settemp &lt;0..1&gt;\n"
        "/setmaxtokens &lt;1..8192&gt;\n"
        "/setloglevel &lt;DEBUG|INFO|WARNING|ERROR|CRITICAL&gt;\n"
        "/setprompt &lt;шаблон&gt; (некалькі радкоў або адказам на паведамленне)\n"
        "/addchannel &lt;name&gt; &lt;src_id&gt; &lt;dst_id&gt; [src_name] [dst_name]\n"
        "/editchannel &lt;name&gt; &lt;src_id&gt; &lt;dst_id&gt;\n"
        "/removechannel &lt;name&gt;\n"
        "/admins — спіс адмінаў\n"
        "/addadmin &lt;user_id|@username&gt; [метка]\n"
        "/removeadmin &lt;user_id&gt;\n"
        "/reload — перачытаць .env + шаблон промпта\n"
        "(/setprompt, /addchannel, /editchannel патрабуюць уводу тэксту)"
    ),
    # /status.
    "status": (
        "<b>Стан</b>\n"
        "Час працы: {uptime}\n"
        "Pyrogram падключаны: {connected}\n"
        "Зыходныя каналы: {sources}\n"
        "Глыбіня чаргі метададзеных: {queue}\n"
        "Мадэль: {model}"
    ),
    # /status — нядаўнія збоі (без push-абвестак; глядзіце праз меню).
    "status_fail_header": "<b>Нядаўнія збоі (апошнія 7д) — {count}</b>",
    "status_fail_none": "<b>Нядаўнія збоі</b>\nНяма за апошнія 7 дзён ✅",
    "status_fail_line": "{time} UTC · {channel} · {reason}",
    # /stats.
    "stats_usage": "❌ Ужыванне: /stats [дні]",
    "stats_days_range": "❌ дні мусяць быць 1..30",
    "stats_unavailable": "❌ Статыстыка недаступная: {err}",
    "stats_header": (
        "<b>Статыстыка — апошнія {days}д</b>\n"
        "Рэтрансляваных падзей: {total}\n"
        "Збояў: {failures}\n"
        "\n"
        "<b>Па зыходных каналах</b>"
    ),
    # /config summary.
    "cfg_summary": (
        "Мадэль: {model}\n"
        "Тэмпература: {temp}\n"
        "Макс. токенаў: {tokens}\n"
        "Узровень логаў: {log}\n"
        "ID адмінаў: {admins}\n"
        "Каналы: {channels}"
    ),
    # /channels.
    "channels_title": "<b>Пары каналаў</b>",
    "channels_line": "{name}: зых {src} → прызн {dst}",
    # /prompt.
    "prompt_none": "(няма файла шаблона промпта)",
    "prompt_body": "<b>Шаблон промпта</b>\n<pre>{body}</pre>",
    "prompt_menu_hint": (
        "\n\nКаб змяніць, дашліце <code>/setprompt</code> з новым шаблонам на "
        "новых радках або адкажыце на паведамленне з ім."
    ),
    # /setmodel.
    "setmodel_usage": "❌ Ужыванне: /setmodel &lt;model&gt;",
    "setmodel_ok": "✅ ANTHROPIC_MODEL = {model}",
    # /settemp.
    "settemp_usage": "❌ Ужыванне: /settemp &lt;0..1&gt;",
    "settemp_nan": "❌ Тэмпература мусіць быць лікам 0..1",
    "settemp_range": "❌ Тэмпература мусіць быць 0..1",
    "settemp_ok": "✅ ANTHROPIC_TEMPERATURE = {val}",
    # /setmaxtokens.
    "settokens_usage": "❌ Ужыванне: /setmaxtokens &lt;1..8192&gt;",
    "settokens_nan": "❌ max_tokens мусіць быць цэлым лікам",
    "settokens_range": "❌ max_tokens мусіць быць 1..8192",
    "settokens_ok": "✅ ANTHROPIC_MAX_TOKENS = {val}",
    # /setloglevel.
    "setlog_usage": "❌ Ужыванне: /setloglevel &lt;LEVEL&gt;",
    "setlog_invalid": "❌ узровень мусіць быць адным з {levels}",
    "setlog_ok": "✅ LOG_LEVEL = {level} (ужыта ў рэальным часе)",
    # /setprompt.
    "setprompt_usage": (
        "❌ Дашліце шаблон пасля каманды на новых радках "
        "або адкажыце на паведамленне з ім."
    ),
    "setprompt_invalid": "❌ {err}",
    "setprompt_ok": "✅ Шаблон промпта абноўлены і перазагружаны.",
    # Reload wrapper.
    "reload_failed": "❌ {action}: збой пры перазагрузцы: {err}",
    # /addchannel.
    "addch_usage": (
        "❌ Ужыванне: /addchannel &lt;name&gt; &lt;src_id&gt; &lt;dst_id&gt; "
        "[src_name] [dst_name]"
    ),
    "addch_bad_name": "❌ name мусіць адпавядаць [a-z0-9_]+",
    "addch_dup": "❌ канал '{name}' ужо існуе (ужыйце /editchannel)",
    "addch_bad_int": "❌ src_id і dst_id мусяць быць цэлымі лікамі",
    "addch_ok": (
        "✅ Дададзены канал '{name}': зых {src} → прызн {dst}\n"
        "⚠️ Пераканайцеся, што бот — адмін/удзельнік зыходнага канала, "
        "інакш Telegram не будзе дастаўляць яго пасты."
    ),
    # /editchannel.
    "editch_usage": "❌ Ужыванне: /editchannel &lt;name&gt; &lt;src_id&gt; &lt;dst_id&gt;",
    "editch_unknown": "❌ невядомы канал '{name}'",
    "editch_ok": "✅ Абноўлены '{name}': зых {src} → прызн {dst}",
    # /removechannel.
    "rmch_usage": "❌ Ужыванне: /removechannel &lt;name&gt;",
    "rmch_protected": "❌ '{name}' абаронены і не можа быць выдалены",
    "rmch_ok": "✅ Выдалены канал '{name}'",
    # /admins.
    "admins_title": "<b>Адміны</b>",
    "admins_help": (
        "Дадаць: /addadmin &lt;user_id&gt; [метка] · Выдаліць: /removeadmin &lt;user_id&gt;"
    ),
    "admins_note": "ℹ️ Імя вызначаецца, толькі калі гэты карыстальнік пісаў боту ў DM.",
    # /reload.
    "reload_ok": "✅ Перачытана канфігурацыя .env і шаблон промпта.",
    # handle_command fallbacks.
    "prompt_for_help": "Дашліце /help для спісу каманд або /menu для кнопак.",
    "unknown_cmd": "❓ Невядомая каманда {cmd}. Дашліце /help.",
    # Add-channel wizard.
    "wiz_prompt_name": (
        "<b>➕ Дадаць пару каналаў (1/3)</b>\n"
        "Дашліце <b>назву</b> канала (літары, лічбы, падкрэсліванне) або 🚫 Скасаваць."
    ),
    "wiz_prompt_src": (
        "<b>➕ Дадаць пару каналаў (2/3)</b>\n"
        "Дашліце id <b>зыходнага</b> канала (напр. <code>-1001234567890</code>)."
    ),
    "wiz_prompt_dst": (
        "<b>➕ Дадаць пару каналаў (3/3)</b>\n"
        "Дашліце id <b>прызначэння</b> (англійскага) канала."
    ),
    "wiz_bad_name": "❌ name мусіць адпавядаць [a-z0-9_]+. Дашліце правільную назву або /cancel.",
    "wiz_bad_int": "❌ Гэта мусіць быць цэлы id канала. Паспрабуйце зноў або /cancel.",
    "wiz_dup_name": "❌ канал '{name}' ужо існуе. Дашліце іншую назву або /cancel.",
    "wiz_cancelled": "✅ Скасавана. Канал не дададзены.",
}


STRINGS: Dict[str, Dict[str, str]] = {"en": _EN, "be": _BE}


def t(key: str, lang: str = DEFAULT_LANG, **kwargs) -> str:
    """Return the localized string for ``key`` in ``lang``.

    Falls back to English when the locale or key is missing, then to the raw
    ``key``. Named ``kwargs`` are interpolated via ``str.format``; a bad or
    missing placeholder degrades to the un-formatted string rather than raising.
    """
    table = STRINGS.get(lang) or STRINGS[DEFAULT_LANG]
    s = table.get(key)
    if s is None:
        s = STRINGS[DEFAULT_LANG].get(key, key)
    if kwargs:
        try:
            return s.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return s
    return s
