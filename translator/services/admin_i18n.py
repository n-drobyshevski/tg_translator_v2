"""Localized strings for the admin DM interface (menu chrome + command replies).

The bot's operator surface (``admin_commands`` + ``admin_menu``) was English-only
with every label inlined. This module is the single string catalog plus a lookup
helper :func:`t`, so the menu can render in either English (``en``, the default)
or Belarusian (``be``). A per-admin language preference is stored separately in
:mod:`translator.services.admin_prefs`; callers resolve it at the two Pyrogram
entry points and pass ``lang`` down.

Design rules baked in here:

* Strings are **fragments, not layouts.** Every admin message is a rich message
  built from blocks (:mod:`translator.services.rich_html`), so headings
  (``h_*``), labels and table columns (``lbl_*`` / ``col_*``), sentences
  (``txt_*``), footers (``hint_*``), outcome titles (``ok_*`` / ``err_*``) and
  values (``val_*``) are separate keys, and the builders own the layout. No
  value contains a newline: how the rich dialect treats a bare ``"\n"`` is
  undocumented, so line structure always comes from blocks. The ✅ / ❌ / ❓
  outcome icons are added by the ``Status`` block, not stored here.
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




# --- English (authoritative) --------------------------------------------------

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
    "btn_ai": "🤖 AI Settings",
    "btn_pick_channel": "📡 Pick a channel…",
    # Copy-to-clipboard buttons (Bot API 7.11 CopyTextButton).
    "btn_copy_model": "📋 Copy model id",
    # Greyed-out hint inside the message input box while the menu keyboard is up.
    "kbd_placeholder": "Pick a button, or type a command",
    # Inline menu buttons.
    "settings_btn_model": "🤖 Set Model",
    "settings_btn_temp": "🌡️ Temperature",
    "settings_btn_tokens": "🔢 Max Tokens",
    "settings_btn_effort": "⚡ Effort",
    "settings_btn_log": "🪵 Logs",
    "settings_btn_rmch": "🗑️ Remove Channel",
    "settings_btn_close": "✖️ Close",
    "settings_btn_rich": "✨ Rich messages: {state}",
    "logs_btn_view": "📄 View recent logs",
    "logs_btn_refresh": "🔄 Refresh",
    "rmch_none": "(no removable channels)",
    "lang_en": "English",
    "lang_be": "Беларуская",
    # Alert toasts (callback_query.answer).
    "alert_saved": "Saved",
    "alert_removed": "Removed",
    "alert_error": "Error",
    "alert_closed": "Closed",
    "alert_expired": "Expired",
    "alert_lang": "Language",
    # Shared values.
    "common_none": "(none)",
    "val_yes": "yes",
    "val_no": "no",
    "val_unknown": "unknown",
    "val_on": "On",
    "val_off": "Off",
    "val_ignored": "ignored",
    # Shared labels (KV rows) and table columns.
    "lbl_uptime": "Uptime",
    "lbl_connected": "Pyrogram connected",
    "lbl_model": "Model",
    "lbl_temp": "Temperature",
    "lbl_tokens": "Max tokens",
    "lbl_effort": "Effort",
    "lbl_log_level": "Log Level",
    "lbl_admins": "Admins",
    "lbl_channels": "Channels",
    "lbl_rich": "Rich messages",
    "lbl_current": "Current",
    "lbl_relayed": "Relayed events",
    "lbl_failures": "Failures",
    "lbl_success_rate": "Success rate",
    "lbl_chars": "Characters",
    "lbl_lines": "Lines",
    "lbl_source": "Source",
    "lbl_destination": "Destination",
    "col_time": "Time (UTC)",
    "col_channel": "Channel",
    "col_detail": "Detail",
    "col_posts": "Posts",
    "col_failures": "Failures",
    "col_share": "Share",
    "col_name": "Name",
    "col_source": "Source",
    "col_destination": "Destination",
    "col_id": "ID",
    "col_command": "Command",
    "col_description": "What it does",
    "col_model": "Model",
    "col_input": "Input $/1M",
    "col_output": "Output $/1M",
    "col_notes": "Notes",
    "col_feature": "Feature",
    "col_result": "Result",
    # Outcome titles (rendered after ✅ / ❌ / ❓ by the Status block).
    "err_usage": "Usage",
    "err_command": "Something went wrong",
    "err_unknown_cmd": "Unknown command",
    "ok_model": "Model saved",
    "ok_temp": "Temperature saved",
    "ok_tokens": "Max tokens saved",
    "ok_effort": "Effort saved",
    "ok_log": "Log level saved",
    "ok_prompt": "Prompt template updated",
    "ok_reload": "Reloaded .env config and prompt template.",
    "ok_lang": "Menu language updated.",
    "ok_menu_closed": "Menu closed",
    "ok_cancelled": "Cancelled",
    "ok_rich": "Rich messages: {state}",
    "ok_addch": "Added channel '{name}'",
    "ok_editch": "Updated '{name}'",
    "ok_rmch": "Removed channel '{name}'",
    "err_stats_days": "days must be 1..30",
    "err_stats_unavailable": "Stats unavailable",
    "err_temp_nan": "Temperature must be a number 0..1",
    "err_temp_range": "Temperature must be 0..1",
    "err_tokens_nan": "max_tokens must be an integer",
    "err_tokens_range": "max_tokens must be 1..128000",
    "err_effort_invalid": "effort must be one of {levels}",
    "err_log_invalid": "level must be one of {levels}",
    "err_setprompt": "No template found",
    "err_prompt_invalid": "Prompt rejected",
    "err_reload": "{action} failed on reload",
    "err_addch_name": "name must match [a-z0-9_]+",
    "err_addch_dup": "channel '{name}' already exists (use /editchannel)",
    "err_addch_int": "src_id and dst_id must be integers",
    "err_unknown_channel": "unknown channel '{name}'",
    "err_protected": "'{name}' is protected and cannot be removed",
    "err_logs_read": "Couldn't read logs",
    "err_no_user_picked": "No user received from the picker.",
    "err_no_valid_user": "No valid user received.",
    "err_username_lookup": "Username lookup unavailable here — use a numeric user id.",
    "err_resolve": "Couldn't resolve {target}",
    "err_rich_value": "value must be on or off",
    "err_richcheck": "Rich messages aren't available",
    "txt_menu_expired": "This menu expired",
    # Shared sentences.
    "txt_applied_live": "Applied to the running bot.",
    "txt_retry": "Try again, or /cancel.",
    "txt_resolve_hint": "The bot can only resolve users/usernames it can see.",
    # /menu greeting.
    "h_menu": "📋 Translator bot menu",
    "txt_menu_intro": "Tap a button below, or open 🛠️ Settings to view and change configuration.",
    "hint_menu_typed": "Typed commands still work — tap ❓ Help to see them.",
    "txt_menu_reopen": "Send /menu to reopen.",
    "txt_menu_expired_body": "Tap 🛠️ Settings or send /menu to reopen.",
    # /help.
    "h_help": "Translator bot — admin menu",
    "txt_help_intro": "Tap a button below; typed commands still work too.",
    "txt_help_status": "📊 Status — uptime, connection, model, recent events",
    "txt_help_ai": "🤖 AI Settings — model, temperature, max tokens, prompt",
    "txt_help_settings": "🛠️ Settings — logs, channels, admins, language",
    "h_commands": "⌨️ Typed commands",
    "grp_monitoring": "📊 Monitoring",
    "grp_ai": "🤖 AI",
    "grp_channels": "📡 Channels",
    "grp_admins": "👤 Admins",
    "grp_system": "⚙️ System",
    "hint_help": "Send /menu to bring the buttons back.",
    "prompt_for_help": "Send /help for the command list, or /menu for buttons.",
    "hint_unknown": "Send /help for the command list.",
    # Add admin (user picker).
    "h_add_admin": "➕ Add admin",
    "txt_add_admin_pick": (
        "Tap “👤 Pick a user…” to choose someone from your chats — I'll capture "
        "their id and name automatically."
    ),
    "txt_add_admin_typed": (
        "Or type <code>/addadmin &lt;user_id&gt;</code> or "
        "<code>/addadmin @username</code> [label]."
    ),
    # Settings.
    "h_settings": "⚙️ Settings",
    "hint_settings": "Pick a setting to change.",
    # AI Settings.
    "h_ai": "🤖 AI Settings",
    "hint_ai": "Tune the translation model below.",
    # Model.
    "h_model": "🤖 Model",
    "txt_model_pricing": "Capability vs. price (USD per 1M tokens):",
    "txt_model_note_haiku": "fastest &amp; cheapest",
    "txt_model_note_sonnet": "balanced (default)",
    "txt_model_note_opus": "most capable, priciest",
    "h_billing": "💲 How billing works",
    "txt_model_billing": (
        "Each post bills input (source + prompt) + output (translation) tokens, "
        "so a higher tier costs several× more per post."
    ),
    "txt_model_active": "The greyed-out button is what's already active.",
    "hint_setmodel": "Pick a preset, or type <code>/setmodel &lt;id&gt;</code> for any other.",
    # Temperature.
    "h_temp": "🌡️ Temperature",
    "txt_temp_intro": "Controls randomness in word choice:",
    "txt_temp_opt_0": (
        "<b>0</b> — deterministic &amp; literal. Best for faithful translation — "
        "same input gives the same output, least drift from the source."
    ),
    "txt_temp_opt_mid": "<b>0.3–0.7</b> — light variation; more natural phrasing but may stray.",
    "txt_temp_opt_1": "<b>1.0</b> — most creative/varied; highest risk of rewording or drift.",
    "h_cost": "💲 Cost",
    "txt_temp_cost": "None — temperature changes wording, not token usage or price.",
    "txt_temp_inert": (
        "<b>Not in use right now.</b> {model} rejects sampling parameters, so "
        "temperature is not sent at all. Tune ⚡ Effort instead, or /setmodel to a "
        "model that accepts it."
    ),
    "txt_temp_ignored": (
        "Saved, but the current model ({model}) ignores temperature — Claude Opus "
        "4.7+ and Sonnet 5 reject sampling parameters, so it is not sent. Use "
        "/setmodel to switch to a model that accepts it, or tune ANTHROPIC_EFFORT "
        "instead."
    ),
    "hint_settemp": "Pick a value, or type <code>/settemp &lt;0..1&gt;</code>.",
    # Max tokens.
    "h_tokens": "🔢 Max Tokens",
    "txt_tokens_intro": (
        "Hard ceiling on the <b>output</b> length of one translation "
        "(≈ ¾ of a word per token):"
    ),
    "txt_tokens_opt_low": "Too low → long posts get cut off mid-sentence.",
    "txt_tokens_opt_high": "Higher → no downside; it's a cap, not a reservation.",
    "txt_tokens_cost": (
        "You pay only for output tokens actually generated, at the model's output "
        "rate — so set it a little above your longest post, not arbitrarily high."
    ),
    "txt_tokens_thinking": (
        "On Sonnet 5 / Opus 4.7+ this budget covers <b>thinking + the translation "
        "together</b>, so it needs more headroom than the visible text alone suggests."
    ),
    "hint_settokens": "Pick a value, or type <code>/setmaxtokens &lt;1..128000&gt;</code>.",
    # Effort.
    "h_effort": "⚡ Effort",
    "txt_effort_intro": "How much thinking the model spends before answering:",
    "txt_effort_opt_low": (
        "<b>low</b> — least thinking, fastest, cheapest. Right for literal "
        "translation against a fixed prompt."
    ),
    "txt_effort_opt_medium": "<b>medium</b> — more deliberation; use if translations read shallow.",
    "txt_effort_opt_high": "<b>high</b> — most thorough; slowest and priciest.",
    "txt_effort_cost": (
        "Thinking is billed as output tokens and shares the max-tokens budget, so "
        "raising this raises both price and truncation risk."
    ),
    "txt_effort_inert": (
        "<b>Not in use right now.</b> {model} does not take an effort setting, so "
        "it is not sent. It applies again on Sonnet 5 / Opus 4.7+."
    ),
    "txt_effort_ignored": (
        "Saved, but the current model ({model}) does not take an effort setting, so "
        "it is not sent. It applies again on Sonnet 5 / Opus 4.7+."
    ),
    "hint_seteffort": "Pick a value, or type <code>/seteffort &lt;low|medium|high&gt;</code>.",
    # Logs.
    "h_log": "🪵 Logs",
    "txt_log_intro": "View recent output, or change the level.",
    "h_logs": "📄 Recent logs",
    "txt_logs_none": "(no log file yet)",
    "txt_logs_empty": "(log file is empty)",
    "hint_logs": "Newest at the bottom · {time} UTC",
    # Channels.
    "h_channels": "📡 Channel pairs",
    "channels_line": "{name}: src {src} → dst {dst}",
    "hint_channels_add": "Tap ➕ to add a new pair step by step.",
    "hint_channels_copy": (
        "📋 Tap a channel below to copy its <code>name src dst</code> — paste it "
        "straight after <code>/editchannel</code>."
    ),
    "h_rmch": "🗑️ Remove Channel",
    "txt_rmch_intro": "Pick a channel to stop relaying.",
    "h_rmch_confirm": "🗑️ Remove '{name}'?",
    "txt_rmch_confirm": "This stops the relay for that pair.",
    "txt_addch_member": (
        "Make sure the bot is an admin/member of the source channel, or Telegram "
        "won't deliver its posts."
    ),
    # Admins.
    "h_admins": "👤 Admins",
    "hint_admins_menu": "Tap an admin to remove. Add via <code>/addadmin &lt;id&gt; [label]</code>.",
    "hint_admins_cmds": (
        "Add: /addadmin &lt;user_id&gt; [label] · Remove: /removeadmin &lt;user_id&gt;"
    ),
    "txt_admins_note": "A name resolves only if that user has DM'd the bot.",
    "h_admin_confirm": "👤 Remove admin <code>{uid}</code>?",
    "txt_admin_confirm": "They lose DM control and stop receiving alerts.",
    # Language.
    "h_lang": "🌐 Language",
    "txt_lang_intro": "Pick the menu language.",
    # Status.
    "h_status": "📊 Status",
    "h_events": "Recent events (last 7d) — {count}",
    "h_events_none": "Recent events",
    "txt_events_none": "None in the last 7 days",
    "hint_status": "Snapshot {time} UTC · /stats for totals",
    # Stats.
    "h_stats": "📈 Stats — last {days}d",
    "h_by_channel": "By source channel",
    "hint_stats": "<code>/stats &lt;days&gt;</code> — any window from 1 to 30 days.",
    # Prompt.
    "h_prompt": "📝 Prompt template",
    "txt_prompt_none": "(no prompt template file)",
    "txt_prompt_reloaded": "Reloaded live — the next translation uses it.",
    "txt_setprompt_how": (
        "Send the template after the command on new lines, or reply to a message "
        "containing it."
    ),
    "hint_setprompt": (
        "To change it, send <code>/setprompt</code> followed by the new template on "
        "new lines, or reply to a message containing it."
    ),
    # Rich messages switch.
    "txt_rich_on": "Admin messages are sent as rich messages, with a classic fallback.",
    "txt_rich_off": "Admin messages are sent as classic HTML.",
    "txt_rich_unsupported": (
        "Saved, but the installed kurigram can't send rich messages — replies stay "
        "classic until it is upgraded."
    ),
    "h_richcheck": "🧪 Rich message check",
    "hint_richcheck": (
        "Each probe was sent to this chat and deleted again; ❌ rows show "
        "Telegram's reason."
    ),
    # Add-channel wizard.
    "h_wizard": "➕ Add channel pair ({step}/3)",
    "lbl_wiz_name": "Name",
    "lbl_wiz_src": "Source channel id",
    "lbl_wiz_dst": "Destination (English) channel id",
    "txt_wiz_name": "Send the channel <b>name</b> (letters, digits, underscore), or 🚫 Cancel.",
    "txt_wiz_src": "Send the <b>source</b> channel id (e.g. <code>-1001234567890</code>).",
    "txt_wiz_dst": "Send the <b>destination</b> (English) channel id.",
    "txt_wiz_cancelled": "No channel was added.",
    "err_wiz_name": "name must match [a-z0-9_]+",
    "err_wiz_int": "That must be an integer channel id",
    "err_wiz_dup": "channel '{name}' already exists",
    "hint_wiz_cancel": "Send /cancel to stop.",
    # Native chat picker (KeyboardButtonRequestChat → chat_shared). The picker is
    # filtered to channels the bot is already a member of, which is exactly the
    # condition /addchannel could previously only warn about after the fact.
    "wiz_pick_hint": (
        "📡 Tap the button below to pick it from your channels — only ones the bot "
        "can already read are listed. Or paste the numeric id."
    ),
    "wiz_picked": "📡 {title} → <code>{id}</code>",
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
    "cmd_desc_setrich": "Switch rich messages on or off",
    "cmd_desc_richcheck": "Test which rich features Telegram accepts",
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
# Partial-by-design is allowed (missing keys fall back to English). A
# native-fluency review is still recommended before considering `be` final.

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
    "btn_ai": "🤖 Налады ІІ",
    "btn_pick_channel": "📡 Выбраць канал…",
    "btn_copy_model": "📋 Скапіяваць id мадэлі",
    "kbd_placeholder": "Націсніце кнопку або ўвядзіце каманду",
    # Inline menu buttons.
    "settings_btn_model": "🤖 Задаць мадэль",
    "settings_btn_temp": "🌡️ Тэмпература",
    "settings_btn_tokens": "🔢 Макс. токенаў",
    "settings_btn_effort": "⚡ Намаганні",
    "settings_btn_log": "🪵 Логі",
    "settings_btn_rmch": "🗑️ Выдаліць канал",
    "settings_btn_close": "✖️ Закрыць",
    "settings_btn_rich": "✨ Багатыя паведамленні: {state}",
    "logs_btn_view": "📄 Паказаць апошнія логі",
    "logs_btn_refresh": "🔄 Абнавіць",
    "rmch_none": "(няма каналаў для выдалення)",
    "lang_en": "English",
    "lang_be": "Беларуская",
    # Alert toasts.
    "alert_saved": "Захавана",
    "alert_removed": "Выдалена",
    "alert_error": "Памылка",
    "alert_closed": "Закрыта",
    "alert_expired": "Састарэла",
    "alert_lang": "Мова",
    # Shared values.
    "common_none": "(няма)",
    "val_yes": "так",
    "val_no": "не",
    "val_unknown": "невядома",
    "val_on": "Укл.",
    "val_off": "Выкл.",
    "val_ignored": "ігнаруецца",
    # Shared labels and table columns.
    "lbl_uptime": "Час працы",
    "lbl_connected": "Pyrogram падключаны",
    "lbl_model": "Мадэль",
    "lbl_temp": "Тэмпература",
    "lbl_tokens": "Макс. токенаў",
    "lbl_effort": "Намаганні",
    "lbl_log_level": "Узровень логаў",
    "lbl_admins": "Адміны",
    "lbl_channels": "Каналы",
    "lbl_rich": "Багатыя паведамленні",
    "lbl_current": "Бягучае",
    "lbl_relayed": "Рэтрансляваных падзей",
    "lbl_failures": "Збояў",
    "lbl_success_rate": "Доля поспеху",
    "lbl_chars": "Сімвалаў",
    "lbl_lines": "Радкоў",
    "lbl_source": "Крыніца",
    "lbl_destination": "Прызначэнне",
    "col_time": "Час (UTC)",
    "col_channel": "Канал",
    "col_detail": "Падрабязнасці",
    "col_posts": "Пастоў",
    "col_failures": "Збояў",
    "col_share": "Доля",
    "col_name": "Імя",
    "col_source": "Крыніца",
    "col_destination": "Прызначэнне",
    "col_id": "ID",
    "col_command": "Каманда",
    "col_description": "Што робіць",
    "col_model": "Мадэль",
    "col_input": "Увод $/1М",
    "col_output": "Вывад $/1М",
    "col_notes": "Заўвагі",
    "col_feature": "Магчымасць",
    "col_result": "Вынік",
    # Outcome titles.
    "err_usage": "Ужыванне",
    "err_command": "Нешта пайшло не так",
    "err_unknown_cmd": "Невядомая каманда",
    "ok_model": "Мадэль захавана",
    "ok_temp": "Тэмпература захавана",
    "ok_tokens": "Макс. токенаў захавана",
    "ok_effort": "Намаганні захаваны",
    "ok_log": "Узровень логаў захаваны",
    "ok_prompt": "Шаблон промпта абноўлены",
    "ok_reload": "Перачытана канфігурацыя .env і шаблон промпта.",
    "ok_lang": "Мову меню зменена.",
    "ok_menu_closed": "Меню закрыта",
    "ok_cancelled": "Скасавана",
    "ok_rich": "Багатыя паведамленні: {state}",
    "ok_addch": "Дададзены канал '{name}'",
    "ok_editch": "Абноўлены '{name}'",
    "ok_rmch": "Выдалены канал '{name}'",
    "err_stats_days": "дні мусяць быць 1..30",
    "err_stats_unavailable": "Статыстыка недаступная",
    "err_temp_nan": "Тэмпература мусіць быць лікам 0..1",
    "err_temp_range": "Тэмпература мусіць быць 0..1",
    "err_tokens_nan": "max_tokens мусіць быць цэлым лікам",
    "err_tokens_range": "max_tokens мусіць быць 1..128000",
    "err_effort_invalid": "намаганні мусяць быць адным з {levels}",
    "err_log_invalid": "узровень мусіць быць адным з {levels}",
    "err_setprompt": "Шаблон не знойдзены",
    "err_prompt_invalid": "Промпт адхілены",
    "err_reload": "{action}: збой пры перазагрузцы",
    "err_addch_name": "name мусіць адпавядаць [a-z0-9_]+",
    "err_addch_dup": "канал '{name}' ужо існуе (ужыйце /editchannel)",
    "err_addch_int": "src_id і dst_id мусяць быць цэлымі лікамі",
    "err_unknown_channel": "невядомы канал '{name}'",
    "err_protected": "'{name}' абаронены і не можа быць выдалены",
    "err_logs_read": "Не атрымалася прачытаць логі",
    "err_no_user_picked": "Карыстальнік не атрыманы.",
    "err_no_valid_user": "Няма карэктнага карыстальніка.",
    "err_username_lookup": "Пошук па імені тут недаступны — ужыйце лікавы id.",
    "err_resolve": "Не атрымалася знайсці {target}",
    "err_rich_value": "значэнне мусіць быць on або off",
    "err_richcheck": "Багатыя паведамленні недаступныя",
    "txt_menu_expired": "Гэта меню састарэла",
    # Shared sentences.
    "txt_applied_live": "Ужыта ў працуючым боце.",
    "txt_retry": "Паспрабуйце зноў або /cancel.",
    "txt_resolve_hint": "Бот можа знайсці толькі тых карыстальнікаў, якіх бачыць.",
    # /menu greeting.
    "h_menu": "📋 Меню бота-перакладчыка",
    "txt_menu_intro": (
        "Націсніце кнопку ніжэй або адкрыйце 🛠️ Налады, каб прагледзець і змяніць "
        "канфігурацыю."
    ),
    "hint_menu_typed": "Тэкставыя каманды таксама працуюць — націсніце ❓ Дапамога.",
    "txt_menu_reopen": "Дашліце /menu, каб адкрыць зноў.",
    "txt_menu_expired_body": "Націсніце 🛠️ Налады або дашліце /menu.",
    # /help.
    "h_help": "Бот-перакладчык — адмінскае меню",
    "txt_help_intro": "Націсніце кнопку ніжэй; набраныя каманды таксама працуюць.",
    "txt_help_status": "📊 Стан — час працы, падключэнне, мадэль, нядаўнія падзеі",
    "txt_help_ai": "🤖 Налады ІІ — мадэль, тэмпература, макс. токены, промпт",
    "txt_help_settings": "🛠️ Налады — логі, каналы, адміны, мова",
    "h_commands": "⌨️ Тэкставыя каманды",
    "grp_monitoring": "📊 Назіранне",
    "grp_ai": "🤖 ІІ",
    "grp_channels": "📡 Каналы",
    "grp_admins": "👤 Адміны",
    "grp_system": "⚙️ Сістэма",
    "hint_help": "Дашліце /menu, каб вярнуць кнопкі.",
    "prompt_for_help": "Дашліце /help для спісу каманд або /menu для кнопак.",
    "hint_unknown": "Дашліце /help для спісу каманд.",
    # Add admin.
    "h_add_admin": "➕ Дадаць адміна",
    "txt_add_admin_pick": (
        "Націсніце «👤 Выбраць карыстальніка…», каб выбраць кагосьці са сваіх "
        "чатаў — я аўтаматычна вазьму яго id і імя."
    ),
    "txt_add_admin_typed": (
        "Або ўвядзіце <code>/addadmin &lt;user_id&gt;</code> ці "
        "<code>/addadmin @username</code> [метка]."
    ),
    # Settings.
    "h_settings": "⚙️ Налады",
    "hint_settings": "Выберыце наладу для змены.",
    # AI Settings.
    "h_ai": "🤖 Налады ІІ",
    "hint_ai": "Наладзьце мадэль перакладу ніжэй.",
    # Model.
    "h_model": "🤖 Мадэль",
    "txt_model_pricing": "Магчымасці і цана (USD за 1М токенаў):",
    "txt_model_note_haiku": "найхутчэйшая і таннейшая",
    "txt_model_note_sonnet": "збалансаваная (па змаўчанні)",
    "txt_model_note_opus": "найбольш магутная, найдаражэйшая",
    "h_billing": "💲 Як налічваецца кошт",
    "txt_model_billing": (
        "Кожны пост білінгуецца за токены ўводу (крыніца + промпт) + вываду "
        "(пераклад), таму вышэйшы клас каштуе ў некалькі разоў больш за пост."
    ),
    "txt_model_active": "Шэрая кнопка — тое, што ўжо ўключана.",
    "hint_setmodel": "Выберыце прэсет або ўвядзіце <code>/setmodel &lt;id&gt;</code> для іншай.",
    # Temperature.
    "h_temp": "🌡️ Тэмпература",
    "txt_temp_intro": "Кіруе выпадковасцю ў выбары слоў:",
    "txt_temp_opt_0": (
        "<b>0</b> — дэтэрмінавана і літаральна. Найлепш для дакладнага перакладу — "
        "аднолькавы ўвод дае аднолькавы вывад, найменшае адхіленне ад крыніцы."
    ),
    "txt_temp_opt_mid": "<b>0.3–0.7</b> — лёгкая варыяцыя; больш натуральна, але можа адхіляцца.",
    "txt_temp_opt_1": "<b>1.0</b> — найбольш творча/зменліва; найвышэйшая рызыка адхілення.",
    "h_cost": "💲 Кошт",
    "txt_temp_cost": "Няма — тэмпература змяняе фармулёўку, а не колькасць токенаў.",
    "txt_temp_inert": (
        "<b>Зараз не выкарыстоўваецца.</b> {model} адхіляе параметры сэмплавання, "
        "таму тэмпература не адпраўляецца. Наладзьце ⚡ Намаганні або /setmodel на "
        "мадэль, якая яе прымае."
    ),
    "txt_temp_ignored": (
        "Захавана, але бягучая мадэль ({model}) ігнаруе temperature — Claude Opus "
        "4.7+ і Sonnet 5 адхіляюць параметры сэмплавання, таму ён не адпраўляецца. "
        "Выкарыстайце /setmodel, каб перайсці на мадэль, якая яго прымае, або "
        "наладзьце ANTHROPIC_EFFORT."
    ),
    "hint_settemp": "Выберыце значэнне або ўвядзіце <code>/settemp &lt;0..1&gt;</code>.",
    # Max tokens.
    "h_tokens": "🔢 Макс. токенаў",
    "txt_tokens_intro": (
        "Жорсткая мяжа на даўжыню <b>вываду</b> аднаго перакладу "
        "(≈ ¾ слова на токен):"
    ),
    "txt_tokens_opt_low": "Занадта мала → доўгія пасты абразаюцца на сярэдзіне сказа.",
    "txt_tokens_opt_high": "Больш → без мінусаў; гэта мяжа, а не рэзерв.",
    "txt_tokens_cost": (
        "Вы плаціце толькі за фактычна згенераваныя токены вываду па стаўцы вываду "
        "мадэлі — стаўце крыху вышэй за самы доўгі пост, а не адвольна шмат."
    ),
    "txt_tokens_thinking": (
        "На Sonnet 5 / Opus 4.7+ гэты бюджэт пакрывае <b>развагі і пераклад "
        "разам</b>, таму патрабуе больш запасу, чым здаецца па бачным тэксце."
    ),
    "hint_settokens": (
        "Выберыце значэнне або ўвядзіце <code>/setmaxtokens &lt;1..128000&gt;</code>."
    ),
    # Effort.
    "h_effort": "⚡ Намаганні",
    "txt_effort_intro": "Колькі мадэль разважае перад адказам:",
    "txt_effort_opt_low": (
        "<b>low</b> — найменш разваг, найхутчэй і танней. Тое, што трэба для "
        "літаральнага перакладу па фіксаваным промпце."
    ),
    "txt_effort_opt_medium": "<b>medium</b> — больш разваг; калі пераклады выглядаюць павярхоўна.",
    "txt_effort_opt_high": "<b>high</b> — найбольш дбайна; найпавольней і найдаражэй.",
    "txt_effort_cost": (
        "Развагі білінгуюцца як токены вываду і дзеляць бюджэт max-tokens, таму "
        "павышэнне падымае і цану, і рызыку абразання."
    ),
    "txt_effort_inert": (
        "<b>Зараз не выкарыстоўваецца.</b> {model} не прымае наладу намаганняў, "
        "таму яна не адпраўляецца. Дзейнічае на Sonnet 5 / Opus 4.7+."
    ),
    "txt_effort_ignored": (
        "Захавана, але бягучая мадэль ({model}) не прымае наладу намаганняў, таму "
        "яна не адпраўляецца. Дзейнічае на Sonnet 5 / Opus 4.7+."
    ),
    "hint_seteffort": (
        "Выберыце значэнне або ўвядзіце <code>/seteffort &lt;low|medium|high&gt;</code>."
    ),
    # Logs.
    "h_log": "🪵 Логі",
    "txt_log_intro": "Паглядзіце апошні вывад або змяніце ўзровень.",
    "h_logs": "📄 Апошнія логі",
    "txt_logs_none": "(файла логаў яшчэ няма)",
    "txt_logs_empty": "(файл логаў пусты)",
    "hint_logs": "Найноўшыя ўнізе · {time} UTC",
    # Channels.
    "h_channels": "📡 Пары каналаў",
    "channels_line": "{name}: зых {src} → прызн {dst}",
    "hint_channels_add": "Націсніце ➕, каб дадаць новую пару пакрокава.",
    "hint_channels_copy": (
        "📋 Націсніце канал ніжэй, каб скапіяваць <code>name src dst</code> — "
        "устаўце адразу пасля <code>/editchannel</code>."
    ),
    "h_rmch": "🗑️ Выдаліць канал",
    "txt_rmch_intro": "Выберыце канал, каб спыніць рэтрансляцыю.",
    "h_rmch_confirm": "🗑️ Выдаліць '{name}'?",
    "txt_rmch_confirm": "Гэта спыніць рэтрансляцыю гэтай пары.",
    "txt_addch_member": (
        "Пераканайцеся, што бот — адмін/удзельнік зыходнага канала, інакш Telegram "
        "не будзе дастаўляць яго пасты."
    ),
    # Admins.
    "h_admins": "👤 Адміны",
    "hint_admins_menu": (
        "Націсніце на адміна, каб выдаліць. Дадаць праз "
        "<code>/addadmin &lt;id&gt; [метка]</code>."
    ),
    "hint_admins_cmds": (
        "Дадаць: /addadmin &lt;user_id&gt; [метка] · Выдаліць: /removeadmin &lt;user_id&gt;"
    ),
    "txt_admins_note": "Імя вызначаецца, толькі калі гэты карыстальнік пісаў боту ў DM.",
    "h_admin_confirm": "👤 Выдаліць адміна <code>{uid}</code>?",
    "txt_admin_confirm": "Ён страціць кіраванне праз DM і перастане атрымліваць абвесткі.",
    # Language.
    "h_lang": "🌐 Мова",
    "txt_lang_intro": "Выберыце мову меню.",
    # Status.
    "h_status": "📊 Стан",
    "h_events": "Нядаўнія падзеі (апошнія 7д) — {count}",
    "h_events_none": "Нядаўнія падзеі",
    "txt_events_none": "Няма за апошнія 7 дзён",
    "hint_status": "Здымак {time} UTC · /stats для падсумоўвання",
    # Stats.
    "h_stats": "📈 Статыстыка — апошнія {days}д",
    "h_by_channel": "Па зыходных каналах",
    "hint_stats": "<code>/stats &lt;дні&gt;</code> — любы перыяд ад 1 да 30 дзён.",
    # Prompt.
    "h_prompt": "📝 Шаблон промпта",
    "txt_prompt_none": "(няма файла шаблона промпта)",
    "txt_prompt_reloaded": "Перазагружаны — наступны пераклад ужо выкарыстае яго.",
    "txt_setprompt_how": (
        "Дашліце шаблон пасля каманды на новых радках або адкажыце на паведамленне "
        "з ім."
    ),
    "hint_setprompt": (
        "Каб змяніць, дашліце <code>/setprompt</code> з новым шаблонам на новых "
        "радках або адкажыце на паведамленне з ім."
    ),
    # Rich messages switch.
    "txt_rich_on": "Адмінскія паведамленні адпраўляюцца як багатыя, з класічным запасным варыянтам.",
    "txt_rich_off": "Адмінскія паведамленні адпраўляюцца як класічны HTML.",
    "txt_rich_unsupported": (
        "Захавана, але ўсталяваны kurigram не ўмее адпраўляць багатыя паведамленні — "
        "адказы застануцца класічнымі да абнаўлення."
    ),
    "h_richcheck": "🧪 Праверка багатых паведамленняў",
    "hint_richcheck": (
        "Кожная проба была адпраўлена ў гэты чат і выдалена; радкі з ❌ паказваюць "
        "прычыну ад Telegram."
    ),
    # Add-channel wizard.
    "h_wizard": "➕ Дадаць пару каналаў ({step}/3)",
    "lbl_wiz_name": "Назва",
    "lbl_wiz_src": "id зыходнага канала",
    "lbl_wiz_dst": "id канала прызначэння (англ.)",
    "txt_wiz_name": "Дашліце <b>назву</b> канала (літары, лічбы, падкрэсліванне) або 🚫 Скасаваць.",
    "txt_wiz_src": "Дашліце id <b>зыходнага</b> канала (напр. <code>-1001234567890</code>).",
    "txt_wiz_dst": "Дашліце id <b>прызначэння</b> (англійскага) канала.",
    "txt_wiz_cancelled": "Канал не дададзены.",
    "err_wiz_name": "name мусіць адпавядаць [a-z0-9_]+",
    "err_wiz_int": "Гэта мусіць быць цэлы id канала",
    "err_wiz_dup": "канал '{name}' ужо існуе",
    "hint_wiz_cancel": "Дашліце /cancel, каб спыніць.",
    "wiz_pick_hint": (
        "📡 Націсніце кнопку ніжэй, каб выбраць яго са сваіх каналаў — у спісе "
        "толькі тыя, якія бот ужо можа чытаць. Або ўстаўце лікавы id."
    ),
    "wiz_picked": "📡 {title} → <code>{id}</code>",
    # Native command menu.
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
    "cmd_desc_setrich": "Уключыць або выключыць багатыя паведамленні",
    "cmd_desc_richcheck": "Праверыць, якія багатыя магчымасці прымае Telegram",
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
