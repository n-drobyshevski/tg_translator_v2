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
    # Greyed-out hint inside the message input box while the menu keyboard is up.
    "kbd_placeholder": "Pick a button, or type a command",
    # Menu chrome.
    "menu_greeting": (
        "<b>📋 Translator bot menu</b>\n"
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
    "settings_btn_log": "🪵 Logs",
    "settings_btn_rmch": "🗑️ Remove Channel",
    "settings_btn_close": "✖️ Close",
    # AI Settings submenu (model / temperature / max-tokens / cost).
    "ai_title": (
        "<b>🤖 AI Settings</b>\n"
        "Model: {model}\n"
        "Temperature: {temp}{temp_flag}\n"
        "Max tokens: {tokens}\n"
        "Effort: {effort}{effort_flag}\n\n"
        "Tune the translation model below."
    ),
    # Marks a knob the active model ignores, inline in the AI Settings summary.
    "ai_inert_flag": " (ignored)",
    "model_title": (
        "<b>🤖 Model</b>\n"
        "Current: {current}\n\n"
        "Capability vs. price (USD per 1M tokens, input / output):\n"
        "• Haiku 4.5 — $1 / $5 — fastest &amp; cheapest\n"
        "• Sonnet 5 — $2 / $10 — balanced (default)\n"
        "• Opus 5 — $5 / $25 — most capable, priciest\n"
        "Each post bills input (source + prompt) + output (translation) tokens, "
        "so a higher tier costs several× more per post.\n"
        "The greyed-out row is what's already active.\n"
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
    # Appended to temp_title when the active model is on the Opus 4.7+ surface,
    # which rejects sampling parameters outright — the value is still saved (it
    # applies if the model is switched back) but nothing is sent.
    "temp_inert_note": (
        "\n\n⚠️ <b>Not in use right now.</b> {model} rejects sampling "
        "parameters, so temperature is not sent at all. Tune ⚡ Effort instead, "
        "or /setmodel to a model that accepts it."
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
        "⚠️ On Sonnet 5 / Opus 4.7+ this budget covers <b>thinking + the "
        "translation together</b>, so it needs more headroom than the visible "
        "text alone suggests.\n"
        "Pick a value, or type <code>/setmaxtokens &lt;1..128000&gt;</code>."
    ),
    # ⚡ Effort — the modern-surface replacement for temperature as the "how hard
    # should it think" knob.
    "settings_btn_effort": "⚡ Effort",
    "effort_title": (
        "<b>⚡ Effort</b>\n"
        "Current: {current}\n\n"
        "How much thinking the model spends before answering:\n"
        "• low — least thinking, fastest, cheapest. Right for literal "
        "translation against a fixed prompt.\n"
        "• medium — more deliberation; use if translations read shallow.\n"
        "• high — most thorough; slowest and priciest.\n"
        "💲 Cost: thinking is billed as output tokens and shares the max-tokens "
        "budget, so raising this raises both price and truncation risk.\n"
        "Pick a value, or type <code>/seteffort &lt;low|medium|high&gt;</code>."
    ),
    "effort_inert_note": (
        "\n\n⚠️ <b>Not in use right now.</b> {model} does not take an effort "
        "setting, so it is not sent. It applies again on Sonnet 5 / Opus 4.7+."
    ),
    "seteffort_usage": "❌ Usage: /seteffort &lt;low|medium|high&gt;",
    "seteffort_invalid": "❌ effort must be one of {levels}",
    "seteffort_ok": "✅ ANTHROPIC_EFFORT = {val}",
    "seteffort_ignored": (
        "\n\n⚠️ Saved, but the current model ({model}) does not take an effort "
        "setting, so it is not sent. It applies again on Sonnet 5 / Opus 4.7+."
    ),
    "log_title": (
        "<b>🪵 Logs</b>\n"
        "View recent output, or change the level.\n"
        "Current level: {current}"
    ),
    "logs_btn_view": "📄 View recent logs",
    "logs_btn_refresh": "🔄 Refresh",
    "logs_body": "<b>📄 Recent logs</b>\n<pre>{body}</pre>",
    "logs_none": "(no log file yet)",
    "logs_empty": "(log file is empty)",
    "logs_error": "❌ Couldn't read logs: {err}",
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
        "<b>Translator bot — admin menu</b>\n"
        "Tap a button below; typed commands still work too.\n"
        "\n"
        "📊 Status — uptime, connection, model, recent events\n"
        "🤖 AI Settings — model, temperature, max tokens, prompt\n"
        "🛠️ Settings — logs, channels, admins, language"
    ),
    # /status.
    "status": (
        "<b>Status</b>\n"
        "Uptime: {uptime}\n"
        "Pyrogram connected: {connected}\n"
        "Model: {model}"
    ),
    # /status — latest events feed (pull-based; replaces push alerts). One unified
    # list where each line's leading ✅/❌ shows the outcome.
    "status_events_header": "<b>Recent events (last 7d) — {count}</b>",
    "status_events_none": "<b>Recent events</b>\nNone in the last 7 days",
    "status_event_ok": "✅ {time} UTC · {channel} · {media}",
    "status_event_fail": "❌ {time} UTC · {channel} · {reason}",
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
        "Log Level: {log}\n"
        "Admins: {admins}\n"
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
    "settemp_ignored": (
        "\n\n⚠️ Saved, but the current model ({model}) ignores temperature — "
        "Claude Opus 4.7+ and Sonnet 5 reject sampling parameters, so it is not "
        "sent. Use /setmodel to switch to a model that accepts it, or tune "
        "ANTHROPIC_EFFORT instead."
    ),
    # /setmaxtokens.
    "settokens_usage": "❌ Usage: /setmaxtokens &lt;1..128000&gt;",
    "settokens_nan": "❌ max_tokens must be an integer",
    "settokens_range": "❌ max_tokens must be 1..128000",
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
    # Native chat picker (KeyboardButtonRequestChat → chat_shared). The picker is
    # filtered to channels the bot is already a member of, which is exactly the
    # condition /addchannel could previously only warn about after the fact.
    "btn_pick_channel": "📡 Pick a channel…",
    "wiz_pick_hint": (
        "\n📡 Tap the button below to pick it from your channels — only ones the "
        "bot can already read are listed. Or paste the numeric id."
    ),
    "wiz_picked": "📡 {title} → <code>{id}</code>\n",
    # Copy-to-clipboard buttons (Bot API 7.11 CopyTextButton).
    "btn_copy_model": "📋 Copy model id",
    "channels_copy_hint": (
        "\n📋 Tap a channel below to copy its <code>name src dst</code> — paste "
        "it straight after <code>/editchannel</code>."
    ),
    # Native command menu (setMyCommands, scoped per admin chat).
    "cmd_desc_menu": "Open the button menu",
    "cmd_desc_status": "Uptime, connection, model, recent events",
    "cmd_desc_stats": "Relay counts for the last N days",
    "cmd_desc_channels": "List the configured channel pairs",
    "cmd_desc_logs": "Show the most recent bot log lines",
    "cmd_desc_prompt": "Show the current prompt template",
    "cmd_desc_setmodel": "Set the translation model",
    "cmd_desc_seteffort": "Set thinking effort (low/medium/high)",
    "cmd_desc_setmaxtokens": "Set the max output tokens per translation",
    "cmd_desc_settemp": "Set sampling temperature (older models only)",
    "cmd_desc_setloglevel": "Set the log level, live",
    "cmd_desc_setlang": "Switch the menu language",
    "cmd_desc_setprompt": "Replace the prompt template",
    "cmd_desc_addchannel": "Add a source/destination channel pair",
    "cmd_desc_editchannel": "Change an existing pair's channel ids",
    "cmd_desc_removechannel": "Stop relaying a channel pair",
    "cmd_desc_admins": "List the bot's admins",
    "cmd_desc_addadmin": "Grant admin access to a user",
    "cmd_desc_removeadmin": "Revoke a user's admin access",
    "cmd_desc_reload": "Re-read .env and the prompt template",
    "cmd_desc_cancel": "Abort the step-by-step flow in progress",
    "cmd_desc_help": "Show the command list",
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
    "kbd_placeholder": "Націсніце кнопку або ўвядзіце каманду",
    # Menu chrome.
    "menu_greeting": (
        "<b>📋 Меню бота-перакладчыка</b>\n"
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
    "settings_btn_log": "🪵 Логі",
    "settings_btn_rmch": "🗑️ Выдаліць канал",
    "settings_btn_close": "✖️ Закрыць",
    # AI Settings submenu.
    "ai_title": (
        "<b>🤖 Налады ІІ</b>\n"
        "Мадэль: {model}\n"
        "Тэмпература: {temp}{temp_flag}\n"
        "Макс. токенаў: {tokens}\n"
        "Намаганні: {effort}{effort_flag}\n\n"
        "Наладзьце мадэль перакладу ніжэй."
    ),
    "ai_inert_flag": " (ігнаруецца)",
    "model_title": (
        "<b>🤖 Мадэль</b>\n"
        "Бягучая: {current}\n\n"
        "Магчымасці і цана (USD за 1М токенаў, увод / вывад):\n"
        "• Haiku 4.5 — $1 / $5 — найхутчэйшая і таннейшая\n"
        "• Sonnet 5 — $2 / $10 — збалансаваная (па змаўчанні)\n"
        "• Opus 5 — $5 / $25 — найбольш магутная, найдаражэйшая\n"
        "Кожны пост білінгуецца за токены ўводу (крыніца + промпт) + вываду "
        "(пераклад), таму вышэйшы клас каштуе ў некалькі разоў больш за пост.\n"
        "Шэры радок — тое, што ўжо ўключана.\n"
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
    "temp_inert_note": (
        "\n\n⚠️ <b>Зараз не выкарыстоўваецца.</b> {model} адхіляе параметры "
        "сэмплавання, таму тэмпература не адпраўляецца. Наладзьце ⚡ Намаганні "
        "або /setmodel на мадэль, якая яе прымае."
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
        "⚠️ На Sonnet 5 / Opus 4.7+ гэты бюджэт пакрывае <b>развагі і пераклад "
        "разам</b>, таму патрабуе больш запасу, чым здаецца па бачным тэксце.\n"
        "Выберыце значэнне або ўвядзіце <code>/setmaxtokens &lt;1..128000&gt;</code>."
    ),
    "settings_btn_effort": "⚡ Намаганні",
    "effort_title": (
        "<b>⚡ Намаганні</b>\n"
        "Бягучыя: {current}\n\n"
        "Колькі мадэль разважае перад адказам:\n"
        "• low — найменш разваг, найхутчэй і танней. Тое, што трэба для "
        "літаральнага перакладу па фіксаваным промпце.\n"
        "• medium — больш разваг; калі пераклады выглядаюць павярхоўна.\n"
        "• high — найбольш дбайна; найпавольней і найдаражэй.\n"
        "💲 Кошт: развагі білінгуюцца як токены вываду і дзеляць бюджэт "
        "max-tokens, таму павышэнне падымае і цану, і рызыку абразання.\n"
        "Выберыце значэнне або ўвядзіце "
        "<code>/seteffort &lt;low|medium|high&gt;</code>."
    ),
    "effort_inert_note": (
        "\n\n⚠️ <b>Зараз не выкарыстоўваецца.</b> {model} не прымае наладу "
        "намаганняў, таму яна не адпраўляецца. Дзейнічае на Sonnet 5 / Opus 4.7+."
    ),
    "seteffort_usage": "❌ Ужыванне: /seteffort &lt;low|medium|high&gt;",
    "seteffort_invalid": "❌ намаганні мусяць быць адным з {levels}",
    "seteffort_ok": "✅ ANTHROPIC_EFFORT = {val}",
    "seteffort_ignored": (
        "\n\n⚠️ Захавана, але бягучая мадэль ({model}) не прымае наладу "
        "намаганняў, таму яна не адпраўляецца. Дзейнічае на Sonnet 5 / Opus 4.7+."
    ),
    "log_title": (
        "<b>🪵 Логі</b>\n"
        "Паглядзіце апошні вывад або змяніце ўзровень.\n"
        "Бягучы ўзровень: {current}"
    ),
    "logs_btn_view": "📄 Паказаць апошнія логі",
    "logs_btn_refresh": "🔄 Абнавіць",
    "logs_body": "<b>📄 Апошнія логі</b>\n<pre>{body}</pre>",
    "logs_none": "(файла логаў яшчэ няма)",
    "logs_empty": "(файл логаў пусты)",
    "logs_error": "❌ Не атрымалася прачытаць логі: {err}",
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
        "<b>Бот-перакладчык — адмінскае меню</b>\n"
        "Націсніце кнопку ніжэй; набраныя каманды таксама працуюць.\n"
        "\n"
        "📊 Стан — час працы, падключэнне, мадэль, нядаўнія падзеі\n"
        "🤖 Налады ІІ — мадэль, тэмпература, макс. токены, промпт\n"
        "🛠️ Налады — логі, каналы, адміны, мова"
    ),
    # /status.
    "status": (
        "<b>Стан</b>\n"
        "Час працы: {uptime}\n"
        "Pyrogram падключаны: {connected}\n"
        "Мадэль: {model}"
    ),
    # /status — нядаўнія збоі (без push-абвестак; глядзіце праз меню).
    "status_events_header": "<b>Нядаўнія падзеі (апошнія 7д) — {count}</b>",
    "status_events_none": "<b>Нядаўнія падзеі</b>\nНяма за апошнія 7 дзён",
    "status_event_ok": "✅ {time} UTC · {channel} · {media}",
    "status_event_fail": "❌ {time} UTC · {channel} · {reason}",
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
        "Узровень логаў: {log}\n"
        "Адміны: {admins}\n"
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
    "settemp_ignored": (
        "\n\n⚠️ Захавана, але бягучая мадэль ({model}) ігнаруе temperature — "
        "Claude Opus 4.7+ і Sonnet 5 адхіляюць параметры сэмплавання, таму ён не "
        "адпраўляецца. Выкарыстайце /setmodel, каб перайсці на мадэль, якая яго "
        "прымае, або наладзьце ANTHROPIC_EFFORT."
    ),
    # /setmaxtokens.
    "settokens_usage": "❌ Ужыванне: /setmaxtokens &lt;1..128000&gt;",
    "settokens_nan": "❌ max_tokens мусіць быць цэлым лікам",
    "settokens_range": "❌ max_tokens мусіць быць 1..128000",
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
    "btn_pick_channel": "📡 Выбраць канал…",
    "wiz_pick_hint": (
        "\n📡 Націсніце кнопку ніжэй, каб выбраць яго са сваіх каналаў — у спісе "
        "толькі тыя, якія бот ужо можа чытаць. Або ўстаўце лікавы id."
    ),
    "wiz_picked": "📡 {title} → <code>{id}</code>\n",
    "btn_copy_model": "📋 Скапіяваць id мадэлі",
    "channels_copy_hint": (
        "\n📋 Націсніце канал ніжэй, каб скапіяваць <code>name src dst</code> — "
        "устаўце адразу пасля <code>/editchannel</code>."
    ),
    "cmd_desc_menu": "Адкрыць меню кнопак",
    "cmd_desc_status": "Час працы, падключэнне, мадэль, нядаўнія падзеі",
    "cmd_desc_stats": "Лічыльнікі рэляў за апошнія N дзён",
    "cmd_desc_channels": "Спіс наладжаных пар каналаў",
    "cmd_desc_logs": "Апошнія радкі лога бота",
    "cmd_desc_prompt": "Паказаць бягучы шаблон промпта",
    "cmd_desc_setmodel": "Задаць мадэль перакладу",
    "cmd_desc_seteffort": "Задаць намаганні разваг (low/medium/high)",
    "cmd_desc_setmaxtokens": "Задаць макс. токенаў вываду на пераклад",
    "cmd_desc_settemp": "Задаць тэмпературу (толькі старыя мадэлі)",
    "cmd_desc_setloglevel": "Задаць узровень лагавання, наўпрост",
    "cmd_desc_setlang": "Пераключыць мову меню",
    "cmd_desc_setprompt": "Замяніць шаблон промпта",
    "cmd_desc_addchannel": "Дадаць пару крыніца/прызначэнне",
    "cmd_desc_editchannel": "Змяніць id каналаў існуючай пары",
    "cmd_desc_removechannel": "Спыніць рэляй пары каналаў",
    "cmd_desc_admins": "Спіс адмінаў бота",
    "cmd_desc_addadmin": "Даць карыстальніку доступ адміна",
    "cmd_desc_removeadmin": "Адабраць доступ адміна",
    "cmd_desc_reload": "Перачытаць .env і шаблон промпта",
    "cmd_desc_cancel": "Спыніць пакрокавы працэс",
    "cmd_desc_help": "Паказаць спіс камандаў",
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
