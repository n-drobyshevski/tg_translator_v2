# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Telegram bot that mirrors Russian-language Telegram channels into paired
English channels, translating each post with the Anthropic API. It ships with a
Flask admin web app for monitoring throughput, editing the prompt, and manually
re-translating / re-posting individual messages.

There are **two independent entry points** that share the `translator` package
and a single SQLite event store (`translator/cache/events.db`; see the event-store
section — `STORAGE_BACKEND=json` falls back to the legacy `events.json`):

- `translator/bot.py` — the long-running relay bot (the production workload).
- `app/flask_app.py` — the admin dashboard (operations + observability).

## Commands

All commands assume the **repo root is on `PYTHONPATH`** (this is the single
most common source of `ModuleNotFoundError: translator`).

**Dependencies are managed with [uv](https://docs.astral.sh/uv/).** `pyproject.toml`
declares them, `uv.lock` pins the exact resolved set (both committed), and the
two `requirements*.txt` files are **generated** fallbacks — see the dependency
section under "Conventions & gotchas".

```bash
# Set up / refresh the environment from the lockfile (creates .venv)
uv sync --frozen          # --frozen: use uv.lock as-is, never silently re-resolve

# Run the relay bot (it adds the repo root to sys.path itself)
uv run python translator/bot.py

# Run the admin web app — must run from the app/ directory with repo root on PYTHONPATH,
# because flask_app.py mixes bare imports (admin_dashboard) and package imports (app.admin_events, translator.*)
cd app && PYTHONPATH=<repo-root> uv run python flask_app.py   # serves on 0.0.0.0:5000

# Tests (Windows convenience script; uses uv when present, else pip)
test.bat

# Tests directly — note the `translator` argument
uv run --frozen pytest translator --cov=translator
uv run --frozen pytest translator/tests/test_config.py            # one file
uv run --frozen pytest translator/tests/test_config.py::test_name # one test
```

> **Run pytest against `translator/`, not bare.** `pytest.ini` lives in
> `translator/`, so a bare `pytest` from the repo root never loads it — which
> means `asyncio_mode = auto` is off and ~50 async tests fail with "async def
> functions are not natively supported". It looks like a broken suite and is not.

> Without uv: `pip install -r requirements-test.txt` then
> `PYTHONPATH=<repo-root> pytest translator`. That installs the same versions
> (the file is exported from the lock), just without the lock being enforced.

Test config lives in `translator/pytest.ini` (`asyncio_mode = auto`, so async
tests need no decorator; `python_files = tests/test_*.py`).

## Deploying (PythonAnywhere)

The production host is a shared PythonAnywhere account: the checkout is at
`~/bot`, the virtualenv at `~/.virtualenvs/translatorbot`, and there is no CI —
dependencies are installed by hand, which is why the installed set has drifted
from the pins before (it ran kurigram 2.2.23 against code that needed 2.2.26,
and the admin menu crashed). uv makes that drift a one-command, verifiable fix.

```bash
pip install uv                      # into the venv; the standalone installer
                                    # needs outbound access a free account lacks
export UV_PROJECT_ENVIRONMENT=~/.virtualenvs/translatorbot
cd ~/bot && git pull
uv sync --frozen --no-dev           # exactly uv.lock, runtime only
```

Then restart the always-on task (Tasks tab) and reload the web app.

> **`uv sync` prunes.** It removes anything in the environment that is not in the
> lock — including `pip` itself, since uv does not install it. That is the point
> (the environment then provably matches the lock), but it means the first run
> against the live venv is not reversible in place. **Migrate blue/green**: sync
> into a *new* path, check it, then repoint the task:
>
> ```bash
> UV_PROJECT_ENVIRONMENT=~/.virtualenvs/translatorbot-uv uv sync --frozen --no-dev
> ~/.virtualenvs/translatorbot-uv/bin/python -c "import pyrogram, anthropic; \
>     print(pyrogram.__version__, anthropic.__version__)"
> ```
>
> Expect `2.2.26 1.6.0`. Keep the old venv until the bot has run a while on the
> new one.

If uv can't be used on the host at all, `pip install -r requirements.txt` still
works — that file is generated from the same lock.

## Configuration

All config comes from environment variables, loaded from a `.env` at the repo
root via `python-dotenv`. `translator/config.py` builds the `Config` singleton
(`CONFIG`) at import time and **raises `RuntimeError` on any missing required
variable** — importing almost anything will fail without a complete env. `Config`
is **not** frozen: `CONFIG.reload()` re-reads `os.environ` and rebuilds the
channel map, which is how the DM admin commands apply changes live (see below).

Channels are organized as **logical pairs**. The set of logical names is
env-driven via `LOGICAL_CHANNELS` (comma-separated; defaults to
`christianvision,shaltnotkill,test` for back-compat). For each logical name the
config reads:

- `<NAME>_CHANNEL` — source channel ID (Russian)
- `<NAME>_EN_CHANNEL_ID` — destination channel ID (English)
- `<NAME>_CHANNEL_NAME` / `<NAME>_EN_CHANNEL_NAME` — optional display names

These become two `ChannelInfo` entries (`<name>` as `"source"`, `<name>_en` as
`"destination"`) that point at each other via `pair_key`. The lookup helpers
(`get_destination_id`, `get_channel_name`, `get_source_channel_ids`) are the
canonical way to resolve channels — use them rather than reading env vars
directly. Other required vars: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_API_ID`,
`TELEGRAM_API_HASH`, `ANTHROPIC_API_KEY`, `TEST_CHANNEL` (the `test` pair is also
"protected" — the DM `/removechannel` refuses it because `TEST_CHANNEL` is
required independently of `LOGICAL_CHANNELS`). Optional: `ADMIN_CHAT_ID` (admin
Telegram user id(s), comma/semicolon-separated → `CONFIG.ADMIN_CHAT_IDS`; gates
DM commands and receives error alerts), `ADMIN_RICH_MESSAGES` (default on; `0`
sends admin DMs and alerts as classic HTML — see the DM admin section). Admin app also
reads `ADMIN_PASSWORD`, `SECRET_KEY`.

> **`CHANNEL_CONFIGS` is captured by value** by `TelegramSender` at construction
> (`self.configs = CHANNEL_CONFIGS`), so `Config.reload()` mutates that dict
> **in place** via `rebuild_channel_configs()` — never rebind the name, or the
> sender keeps pointing at a stale dict.

> Security note: the working-tree `.env` currently contains **real, live API
> keys and tokens**. It is gitignored, but treat these as secrets — do not echo
> them, paste them into code, or commit them anywhere.

## Architecture — the relay bot

The bot runs **two Telegram clients at once** because neither alone exposes
everything needed:

1. **Pyrogram** (`Client`, MTProto) runs as the **bot account**
   (`bot_token=...`, the maintained `kurigram` fork) and listens to source
   channels via `@pyro.on_message` / `@pyro.on_edited_message`. The source filter
   is a **live custom filter** (`filters.create(... m.chat.id in
   CONFIG.get_source_channel_ids())`), read fresh on every update — not
   `filters.chat(...)` captured at registration — so a channel added/removed from
   a DM takes effect after `CONFIG.reload()` with no restart. Because it's a bot
   account it also receives **private DMs**, which powers the admin command
   surface (below).
2. **python-telegram-bot** (`Application`, Bot API) cannot listen to arbitrary
   channels but *can* resolve chat metadata and file download links. It is used
   only for `get_chat`/`get_file` via `ptb_worker`; it does **not** poll for
   updates.

They are bridged by an `asyncio.Queue` + `asyncio.Future` handshake:

```
Pyrogram handler → builds MetadataRequest(chat_id, message_id, file_id) with a Future
                 → query_queue.put(req); meta = await req.response
ptb_worker (background task) → queue.get() → Bot API get_chat / get_file
                            → req.response.set_result(meta)
```

Per-message pipeline in `register_handlers` (`translator/bot.py`):

1. Extract text/caption + media (`utils/message_utils.get_media_info`).
2. Request metadata via the queue (above); convert Telegram entities to HTML
   (`utils/utils_html.entities_to_html`).
3. Build a translation payload (`message_utils.build_payload`) — appends a
   "Source channel:" link.
4. Translate (`utils/translation_utils.translate_html`) wrapped in
   `utils/utils_async.run_with_retries` (3 attempts, exponential backoff + jitter,
   skips non-retryable errors like `ValueError`/`KeyError`). The Anthropic call is
   synchronous SDK wrapped in `asyncio.to_thread` so it never blocks the loop.
5. Send via `services/telegram_sender.TelegramSender` — the matching
   `send_<kind>_message` when there's a download link and the caption fits in
   1024 chars, else `send_message` (which splits at the 4096-char limit).
   `TelegramSender` talks to the **raw Bot API over `httpx.AsyncClient`** (a fresh
   client per call, since it's shared by the async bot and the per-request-loop
   Flask app), not via PTB.
6. Record the outcome with `services/event_logger.EventRecorder`.

`get_media_info` recognizes `live_photo, animation, voice, video_note, audio, doc,
photo, video` — **in that order, which matters**: a live photo (Bot API 10.0)
arrives with `.photo` set to its still frame too, so probing `photo` first would
silently drop the motion; and Pyrogram sets `.document` (and sometimes `.video`)
alongside `.animation` for GIFs, and first-present wins. A live photo goes out via
`sendLivePhoto` with **two file_ids** (the video, and the still from
`live_photo_still_id`; the endpoint takes no URLs), falling back to `sendPhoto`
with the still; in albums it is `("live_photo", video_id, still_id)` →
`InputMediaLivePhoto`.
`sendVideoNote` is the one endpoint that takes **no caption at all**, so a video
note is relayed bare and the translation follows as a reply
(`bot.CAPTIONLESS_MEDIA`); everything else in `bot.CAPTIONED_MEDIA` carries its
caption, which is also what the edit handler keys on to choose
`editMessageCaption` vs `editMessageText`.

**Beyond plain posts** (all in `register_handlers`):

- **Replies.** If a source post replies to an earlier one, `reply_target` maps it
  to the *head* of that post's translation and every send path passes it as
  `reply_parameters` (with `allow_sending_without_reply`).
- **Deletions** (`on_deleted_messages`, `SYNC_DELETES`, default on, read live):
  deleting a source post deletes **every** message its translation produced via
  `deleteMessages`, and records a `delete` event. That needs all the ids, so each
  sender appends to `MessageEvent.dest_message_ids` (`record_sent`: text chunks,
  a caption's remainder reply, each album item); `CONFIG.get_destination_msg_ids`
  reads it, head first, falling back to the single legacy `dest_message_id`.
  Deleting a non-lead album part deletes nothing (only the lead is mapped).
- **Polls** are translated field by field in plain-text mode
  (`translate_plain`: `PLAIN_SYSTEM` instead of the post template, which would
  bold and `<p>`-wrap a poll option) and re-created with `sendPoll`
  (`build_poll_request`: always anonymous in a channel, limits enforced, a quiz
  whose answer the bot can't see goes out as a regular poll). Polls can't be
  edited, so the edit handler only mirrors **closing** one (`stopPoll`).
- **Checklists** can't be sent to a channel by a bot at all (`sendChecklist`
  needs a business connection), so `checklist_to_html` turns one into a ✅/⬜️
  text post that goes through the normal pipeline — edits (ticking a task)
  included.

**Albums** (`services/media_group_buffer.py`): Telegram delivers a media group as
N independent updates sharing a `media_group_id`, with no "group complete"
signal and the caption on only one part. `handle_message` routes those into a
`MediaGroupBuffer`, which debounces on quiet (`MEDIA_GROUP_DEBOUNCE`, default 2s)
and then relays the whole album through one `sendMediaGroup` with a single
translation. `can_send_as_album` enforces the Bot API's rules (2–10 items; only
photo/video/document/audio, and only one family per album — animations, voice and
video notes are never albumable); anything else falls back to per-item relay.
`sendMediaGroup` returns an **array** of messages, and the first id is recorded
as `dest_message_id` so the edit mapping keeps working.

Send options are centralized in `telegram_sender`: `build_link_preview_options`,
`build_reply_parameters` (Bot API 7.0 `reply_parameters`, replacing the legacy
`reply_to_message_id`, with `allow_sending_without_reply` so a split post can't
lose its remainder) and `build_send_options` (env-gated `PROTECT_CONTENT`,
`DISABLE_NOTIFICATION`, `SHOW_CAPTION_ABOVE_MEDIA`). **Watch the encoding split**:
`sendMessage` uses a JSON body so these nest directly, while the media and edit
paths are form-encoded and must go through `_as_form_value` (booleans become
lowercase JSON literals, objects become JSON strings).

**Edits** are handled separately: the edit handler looks up the previously-sent
destination message ID via `CONFIG.get_destination_msg_id(...)` (one indexed
SQLite seek — see the event-store section) and calls `TelegramSender.edit_message`. That method
does aggressive content-equality normalization (`sanitize_html`,
`telegram_normalize_text`, `advanced_content_comparison`) to avoid Telegram's
"message is not modified" error.

On startup `main_async` acquires an exclusive `bot.lock` (cross-platform advisory
lock, `utils/single_instance.py`) and refuses to start if another instance holds
it — this is the real single-instance guard (the old `PRAGMA quick_check` on
`bot.session` only detected a *locked* session, not a second idle instance; it is
kept purely as a session-corruption check).

## Architecture — DM admin control & error forwarding

The bot exposes an **operator control surface over a private Telegram DM**, gated
to `CONFIG.ADMIN_CHAT_IDS`. Because the Pyrogram client is a bot account it
receives DMs directly — no PTB polling is involved.

- `services/admin_commands.py` registers one `filters.private & _admin_filter()`
  handler. The dispatch entry point `handle_command(msg, ...)` is deliberately
  free of Pyrogram plumbing so it's unit-testable with a fake message. Commands:
  read-only `/help /status /stats /channels /prompt /logs`; writable
  `/setmodel /settemp /setmaxtokens /seteffort /setloglevel /setprompt /setlang
  /setrich`;
  channel management `/addchannel /editchannel /removechannel`; admin management
  `/admins /addadmin /removeadmin`; plus `/reload`, `/cancel` and `/richcheck`.
  Every reply is a rich message with a classic fallback (next section); data is
  HTML-escaped, and each rendering is fitted to its own size cap.
- **Buttons, not just commands** (`services/admin_menu.py`): a persistent reply
  keyboard whose taps arrive as *labels* (`resolve_button_label` maps them back
  to commands via `BUTTON_KEYS`, across every locale) plus an inline menu tree
  navigated by `on_callback_query`. All of it routes back into the same `_cmd_*`
  helpers — no business logic is duplicated. The pure layer (`build_menu`,
  `handle_callback`, `resolve_button_label`) is Pyrogram-free and unit-tested
  with plain strings; `to_inline_markup` / `to_reply_markup` are the only glue.
  Operator strings live in `services/admin_i18n.py` (`en` + partial `be`, falling
  back to `en`), per-admin language in `services/admin_prefs.py`.
- **Newer Bot API button kinds are encoded in the `callback_data` slot**, not by
  widening the `(label, data)` pair every menu and test is written against:
  `copy:<text>` → `CopyTextButton` (7.11) and `x:<data>` → `DisabledButton`
  (10.2), decoded in `to_inline_markup`; destructive heads (`rmchok`, `rmadminok`)
  render `ButtonStyle.DANGER` (9.4). Telegram fires no callback query for either
  kind, so `handle_callback` never sees those prefixes.
- **Every button kind newer than Bot API 7.x is optional and probed at import.**
  `admin_menu` resolves `HAS_COPY_BUTTON` / `HAS_DISABLED_BUTTON` /
  `HAS_BUTTON_STYLE` / `HAS_CHAT_PICKER` / `HAS_KEYBOARD_HINTS` once, checking
  **both** that the type exists (`getattr(pyro_types, …)`) and that the
  constructor takes the keyword (`_accepts`) — an older `InlineKeyboardButton`
  imports fine while `style=` is still a `TypeError`. Nothing outside those
  guards may reference an optional type, and **no function may `from
  pyrogram.types import` one**: that is exactly the bug that took the menu down
  in production, where the `plain=True` fallback re-ran the same unconditional
  import and raised the *identical* `ImportError` it existed to catch.
  Why this matters here: dependencies on the PythonAnywhere host are installed
  by hand and there is no CI, so the kurigram actually running routinely lags
  `requirements.txt` (it ran the new menu code against 2.2.23, which has no
  `CopyTextButton`). `main_async` logs the version and the resolved flags at
  startup so the next skew is a line in `bot.log`, not a traceback DM'd mid-tap.
- **Every admin message is a rich message (Bot API 10.1–10.3), on by default,
  with a classic fallback.** Headings, tables, lists, collapsible `<details>`,
  footers and buttons *inside* the message body. Two facts shape all of it:
  `InputRichMessage(html=…)` goes **straight to Telegram** (kurigram does no local
  parsing), so the dialect is server-validated only and nothing in CI can prove a
  payload is accepted; and how the dialect treats a bare `"\n"` is undocumented,
  so layout never relies on newlines. Hence:

  - **Author once, render twice** (`services/rich_html.py`, stdlib-only). A screen
    is a `Doc` of blocks (`Heading Para KV Setting Table Bullets Quote RawQuote Pre
    Details Hr Footer Status Note`), each rendering itself as rich HTML (≤ 32000
    UTF-8 bytes) *and* classic Telegram HTML (≤ 4000 chars) in the layout
    operators already knew (`label: value`, `KEY = value`, `✅ …` first).
    `Doc.render()` returns a **`RichText`**: a `str` whose value is the classic
    rendering (so `startswith("✅")` and every substring test run against exactly
    what the fallback sends) carrying `.rich` and `.status`. **`rt + "x"` returns a
    plain `str` and drops `.rich`** — compose with `Doc.add` / `admin_commands.compose`.
    Block constructors take trusted inline HTML (escape data with `esc`); `Pre` /
    `RawQuote` take raw text, escape it, and are the "elastic" blocks that absorb
    truncation (logs and tracebacks keep their tail, the prompt its head), so
    headings, footers and closing tags survive a cut.
  - **One send path** (`services/admin_send.py`): `reply(msg, content, rows=… |
    reply_markup=…)` and `edit(cq, content, rows=…)`. A guard test fails on any
    direct `reply_text` / `edit_message_text` in `admin_commands` / `admin_menu` /
    `admin_wizard`. Reply keyboards can't live in the body, so they ride along
    with `reply_rich(…, reply_markup=kb)`.
  - **`send_with_markup` degrades markup and format, never the message**: rich +
    in-body `<tg-button-row>` → rich + ordinary inline keyboard → classic styled →
    classic plain → classic with **no markup at all**. Markup is built outside the
    send so a construction failure is logged apart from a Telegram rejection, and
    `MessageNotModified` is re-raised untouched from any tier. In the rich body
    every button kind has a spelling (`type="copy_text" text=…`,
    `type="disabled"`, `style="danger"`); `rich_button_rows` returns `None` only
    past the API limits (callback data > 64 bytes, copy text > 256, > 8 per row),
    which skips just the in-body tier. On the classic tiers a disabled button
    degrades to the ordinary button it wraps (`x:` carries the action), copy
    buttons drop out, and an emptied row is skipped — so degrading never makes an
    action unreachable.
  - **The rich edit must omit `text`.** kurigram's `edit_message_text` checks
    `text` first and silently ignores `rich_message` when both are given — the
    menus-only version passed both, so its "rich" edits were quietly classic.
    If every edit tier fails, `admin_send.edit` sends the screen as a new message.
  - **Rich needs its own callable**, not another kwarg: `Message.reply_text` does
    not accept `rich_message` — only `reply_rich` and the edit methods do.
    `HAS_RICH_MESSAGES` probes the send half with `reply_markup` (kurigram
    2.2.25+), the edit half, and `RichMessageButton` (2.2.26).
  - **Kill switch & breaker.** `rich_enabled()` = capability **and**
    `ADMIN_RICH_MESSAGES` (default on; the old `ADMIN_RICH_MENUS` is a deprecated
    alias — an explicit `=0` there still opts out, the new name wins, startup
    warns) **and** a closed circuit breaker (3 consecutive rich rejections → rich
    skipped for 15 min; any success resets). `/setrich on|off` (or ✨ in Settings)
    persists the switch live. `load_dotenv` runs only at import, so `/reload`
    does **not** re-read `.env` in general — `_cmd_reload` copies just the two
    rich keys from it, so an out-of-band edit of the kill switch still lands.
  - **`/richcheck`** sends every `rich_html.PROBES` document to the chat, deletes
    it, and replies with a ✅/❌ table of Telegram's verdicts — the only real test
    of the dialect. `test_every_emitted_tag_has_a_probe` fails if a block starts
    emitting a tag or attribute no probe covers.
  - **Fallback logs are WARNING, never ERROR**: ERROR records are DM'd by the log
    forwarder, and a handled degradation must not page the operator.
  - **i18n strings are fragments** (`h_* lbl_* col_* txt_* hint_* ok_* err_*
    val_*`), never layouts, and never contain `"\n"` (tested). Outcome icons come
    from the `Status` block. `test_every_key_used_in_the_code_exists_in_english`
    catches typo'd keys, which `t()` would otherwise render as the raw key.
  - Tests: `translator/tests/conftest.py` neutralises both rich env keys (the real
    `.env` is loaded by config import) and resets the breaker for every test.
- **Preset lists track `config.py`, not the docs.** `MODEL_PRESETS` /
  `TOKEN_PRESETS` / `EFFORT_PRESETS` went stale once (the menu still said
  "Haiku 4.5 (default)" after the default became Sonnet 5), so which preset is
  active is derived at render time and `test_admin_modern_ui.py` asserts each
  default appears in its list. Temperature and effort are **mutually exclusive**
  — each request surface takes one and rejects the other (see
  `model_capabilities`) — so the AI menu flags whichever the live model ignores
  and greys out its presets rather than offering buttons that change nothing.
- **Native command menu:** `publish_admin_commands(pyro)` runs once in
  `main_async` *after* `pyro.start()` (the client must be connected) and pushes
  `COMMAND_SPECS` via `set_bot_commands` with **`BotCommandScopeChat` per admin**
  — never globally, because the command list maps the whole control surface and a
  stranger who DMs the bot should not be handed it. It also points the ☰ button
  at that list (`MenuButtonCommands`). Every failure is a logged warning: a bot
  that can't set its command menu must still relay. Switching language
  (typed `/setlang` or the inline button) republishes for that admin, since the
  scope stores one fixed language per chat.
- **Persistence:** writable settings are saved to the shared root `.env` via
  `services/env_store.py` (`set_env_var`/`unset_env_var` — atomic temp-file +
  `os.replace`, preserves comments/secrets/ordering, only the target key is
  rewritten) **and** applied live with `CONFIG.reload()`. So changes survive a
  restart and are visible to the Flask app. `/setprompt` writes
  `prompt_template.txt` (with a `.bak`) and calls
  `translation_utils.reload_prompt_template()` — needed because `PROMPT_TEMPLATE`
  is a module global frozen at import (model/temp/max-tokens, by contrast, are
  read fresh from `CONFIG` per translation, so they apply on the next message).
  Prompt input is validated by the shared `utils/prompt_validation.validate_prompt`
  (also used by `app/admin_prompt.py`).
- **`/addchannel`** writes the leaf vars first and appends the name to
  `LOGICAL_CHANNELS` **last**, then reloads, so a half-written pair can't make
  `reload()` raise. The bot must already be an admin/member of the source channel
  or Telegram delivers nothing — the reply still warns about it for the typed
  path, but the button path now makes it unmakeable: the add-channel wizard
  (`services/admin_wizard.py`) offers Telegram's **native chat picker**
  (`KeyboardButtonRequestChat` with `chat_is_channel` + `bot_is_member`), so only
  channels the bot can already read are listed. `build_channel_picker_keyboard`
  returns `None` where `HAS_CHAT_PICKER` is false, and `_reply_for_wizard` then
  suppresses the pick hint too rather than advertising a button that isn't there. A pick arrives as a `chat_shared`
  service message and is fed into `admin_wizard.feed()` exactly as a typed id
  would be, so both routes share one validation path and one commit. Typed ids
  still work. `admin_wizard.current_step()` is what the Pyrogram layer reads to
  decide which keyboard a reply needs; the picker keyboard is one-shot, so
  finishing or cancelling restores the main menu keyboard. The picker's Cancel is
  a *label*, so it must stay mapped in `BUTTON_KEYS` or it gets swallowed as the
  wizard's next answer.
- **Error forwarding:** `services/error_sender.send_alert` (httpx → Bot API,
  throttled ~300s per signature `key`) now reads `ADMIN_ALERT_CHAT_ID` **or**
  falls back to `ADMIN_CHAT_ID` (the first id, when it lists several) —
  previously it was a silent no-op since `.env` only defines the latter. Alerts
  go out via **`sendRichMessage`** (`build_alert_html`: first line → heading,
  `Key: value` lines → table, the rest — a traceback — → expandable quote keeping
  its tail), falling back to the plain `sendMessage` on any non-200 or error;
  `ADMIN_RICH_MESSAGES=0` skips rich. The signature stays `(text, key=None)`: the
  callers already write that shape, and `TelegramErrorHandler.emit` builds the
  coroutine synchronously, where a new kwarg would fail silently. `services/log_forwarding.py` additionally attaches a
  root-logger `TelegramErrorHandler` (wired in `main_async` once the loop exists)
  that bridges sync `emit` → async `send_alert` via `run_coroutine_threadsafe`,
  so **any** ERROR-level log is DM'd. Recursion/flood guards: it skips the
  `ALERT` logger, holds an `_in_emit` reentrancy flag, and relies on the
  send_alert throttle. (Note: the admin must `/start` the bot once before
  Telegram allows it to send DMs.)

## Architecture — the event store (SQLite)

The event store is **SQLite** at `translator/cache/events.db` (`DB_PATH`), via the
`translator/db/` package (`schema.sql`, `connection.py`, `events_dao.py`,
`migrate.py`). It replaced the old single `events.json` file, whose read-modify-
rewrite-on-every-event was unsafe across the two processes (bot + Flask). WAL +
`busy_timeout` + connection-per-operation make concurrent access safe.

- **Written** by `EventRecorder` — call `.set(field=...)` to accumulate a
  payload, then `.finalize()`, which inserts one row via `events_dao.insert_event`.
  `.set()` raises `KeyError` for unknown fields, so fields must exist on
  `MessageEvent`.
- **Read** by `aggregator.py` (`load_messages` + `build_*`) for dashboard charts,
  and by `config.get_destination_msg_id` for edit source→dest mapping (a single
  indexed seek via `idx_events_src_msg`, not a full scan). Schema v3 added
  `dest_message_ids` (all destination ids of a post, comma-separated) for reply
  mapping and delete sync — `get_destination_msg_ids`; like every added column
  it is back-filled on old DBs by `connection._ADDED_COLUMNS`.

`STORAGE_BACKEND` env (`sqlite` default | `json`) flips back to the legacy
events.json path for rollback; the three call sites branch on it. Run
`python -m translator.db.migrate` once to import an existing events.json into the
DB (idempotent; leaves events.json in place as a backup).

## Architecture — the Flask admin app

`app/flask_app.py` is the entry point. It uses Flask-Login with a single static
admin user (password from `ADMIN_PASSWORD`); all admin routes are
`@login_required`. Blueprints (one per `app/admin_*.py` module):

- `admin_bp` (`admin_dashboard.py`), `admin_stats_bp` (`admin_events.py`),
  `admin_logs_bp` (`admin_logs.py`) — observability over `events.json` /
  `bot.log`.
- `admin_config_bp`, `admin_prompt_bp` — view/edit env config and the prompt
  template.
- `admin_manager_bp` (`admin_manager.py`) — manual workflow: pick a channel +
  message (or paste custom text), translate via the *same* `translate_html`, and
  post/edit/delete in a target channel. HTML is cleaned for Telegram with
  `bleach` (`clean_telegram_html`, allowed tags `b/i/u/s/a/code/pre/blockquote/
  tg-spoiler`). These routes are **synchronous** (`def`, not `async`) and drive
  async sender calls via `asyncio.run` — required because PythonAnywhere is
  WSGI-only (no ASGI).
- `bp` (`/api/metrics/summary`) — JSON for the dashboard charts.

The manager and aggregator code is heavily instrumented with `print(...)`
"banner" debug logging — that's intentional existing style, not dead code.

## Translation specifics

`translate_html` calls the model in `CONFIG.ANTHROPIC_MODEL` (env `ANTHROPIC_MODEL`,
default **`claude-sonnet-5`**). `ANTHROPIC_MAX_TOKENS` (8000),
`ANTHROPIC_TEMPERATURE` (0) and `ANTHROPIC_EFFORT` (`low`) are env-overridable,
and all four are settable live from the admin DM (`/setmodel`, `/setmaxtokens`,
`/settemp`, `/seteffort`, or the 🤖 AI Settings menu).
The previous default, `claude-haiku-4-5`, is still served but carries a published
retirement floor of 2026-10-15.

### What it costs: `/cost`

Every relayed translation records its usage (`input_tokens`, `output_tokens`,
`cache_read_tokens`, `cache_creation_tokens`, `model_used`) in the event store.
The admin DM turns that into a spend estimate: `/cost [days]` (1–90, or AI
Settings → 💲 Cost with 7/30/90-day buttons), plus an `Est. cost` row in `/stats`.
Prices live in **`utils/model_pricing.py` — the one place to edit when list prices
change** (`PRICES_AS_OF` is shown in the report footer); the Model menu's price
table reads the same table. Three things it gets right on purpose:

- `usage.input_tokens` is the *uncached* input, so cost = input·p_in + cache
  writes·1.25·p_in (the 5-minute TTL `translate_html` uses) + cache reads·p_read +
  output·p_out — and **cache reads are priced per model** (0.025× on Fable 5.1,
  0.05× on Opus 5.5, 0.1× elsewhere), not as a flat tenth.
- `price_for` matches an id exactly or as a dated snapshot (`…-YYYYMMDD`), never
  by bare prefix: `claude-opus-5` is a prefix of the cheaper `claude-opus-5-5`, and
  a future `claude-sonnet-5-1` must read as *unpriced*, not as Sonnet 5.
  Unpriced translations still count their tokens and are flagged in the report.
- It covers relayed posts only: the Flask app's manual translations
  (`app/admin_manager.py`, `app/admin_prompt.py`) pass no `usage_out`, and a
  failed attempt inside `run_with_retries` isn't recorded — so it is a floor.

### The request shape follows the model

**`utils/model_capabilities.py` is the single place that decides which parameters
are legal for a given model**, because the model is switchable at runtime (env, or
the admin DM `/setmodel`) and the two generations disagree:

| | Haiku 4.5 / 4.6 / 4.5 line | Opus 4.7+ surface (incl. **Sonnet 5**) |
|---|---|---|
| `temperature` | accepted (via `extra_body`) | **rejected — 400** |
| `output_config.effort` | errors on Sonnet/Haiku | supported |
| `thinking` | n/a | adaptive, sent explicitly |

Unknown model ids are treated as the **modern** surface on purpose: omitting a
sampling parameter is accepted everywhere, while sending one 400s on the new
models — so the safe guess is the one that can't take the relay down.

Three traps this code exists to avoid, all of which fail on *every* message:

1. **`temperature` is never a named kwarg.** `anthropic` 1.x removed it from the
   `messages.create()` signature, so passing it is a `TypeError` — and `TypeError`
   is in `run_with_retries`' `NON_RETRYABLE` tuple, so it fails permanently with no
   retry. On models that still accept it, it travels in `extra_body`.
2. **Never index `resp.content[0].text`.** With adaptive thinking the first block
   is a *thinking* block, which has no `.text` at all (and `thinking.display`
   defaults to `"omitted"`, so it's present with empty text even when reasoning
   isn't surfaced). Select blocks by `type == "text"` instead.
3. **`max_tokens` covers thinking + response together.** An under-sized budget
   surfaces as `stop_reason == "max_tokens"`, i.e. a translation cut off mid-post.
   `translate_html` raises on it rather than publishing the partial text.

> The test doubles all take `**kwargs` and so cannot catch a dropped parameter on
> their own — `test_translate_html_kwargs_match_the_real_sdk_signature` binds our
> kwargs against the installed SDK's real signature, for *both* surfaces. That is
> what makes the next such removal a failing test instead of a production outage.

> **Test-isolation caveat:** `env_store.set_env_var` writes to `os.environ` as well
> as `.env` — by design, since that is how `CONFIG.reload()` applies a DM change
> live — so any test exercising `/setmodel` (or another `_persist_and_reload`
> command) leaks that value into every later test in the run. Tests that depend on
> the model must pin `CONFIG.ANTHROPIC_MODEL` themselves rather than trust the
> ambient default. `test_admin_modern_ui.py` instead uses an autouse fixture that
> snapshots and restores `os.environ`, which is the pattern to copy: it needs the
> *shipped* defaults to check that the menu presets still match them, and it also
> stops its own `/seteffort` tests leaking onward. There is still no suite-wide
> guard — this has now caused a pass-alone/fail-in-suite bug twice.

The system/instructions/example prompt lives in
`translator/prompt_template.txt` (loaded via `config.load_prompt_template`) and
encodes strict literal-translation rules (preserve HTML links/URLs, hashtags,
paragraph `<p>` tags, wrap the first sentence in `<b>`, never relabel Belarusian
church names as "Russian orthodox"). Short messages (< 7 words or < 20 chars)
bypass the full template. The response is post-processed to strip stray
`<translation>/<source>/<system>/...` wrapper tags the model sometimes emits.

## Conventions & gotchas

- **Telegram client:** the code imports `pyrogram`, but the installed package is
  **`kurigram`** (the maintained drop-in fork — Pyrogram itself is abandoned). It
  exposes the same `pyrogram` import path, so imports are unchanged. All
  dependencies are now **pinned** in `requirements.txt` / `pyproject.toml`
  (`telethon` removed); `requirements-test.txt` exists and is pinned.
- Inline comments and the `bot.py` module docstring are in **Russian** — match
  the surrounding language when editing those areas.
- `EventRecorder.prefill` initializes `float` fields to `False` (a pre-existing
  quirk) — be deliberate when changing `MessageEvent` field types.
- Telegram limits enforced in code: 4096 chars/message, 1024 chars for photo
  captions, 20 MB for Bot API file fetches (`max_size` in the handler), 2–10 items
  per `sendMediaGroup`.
- **`anthropic` is on 1.x**, whose internal HTTP layer is `httpx2`. That installs
  *alongside* the separately-pinned `httpx` (different distribution, no conflict):
  `httpx` is ours, used by `telegram_sender` / `error_sender` and patched in tests.
  Don't "unify" them, and don't call `httpx2.alias_httpx()` — the tests mock
  Telegram HTTP, not SDK HTTP, so aliasing would only break the existing doubles.
- **Dependencies: `pyproject.toml` is the only file you edit.** `uv.lock` holds
  the resolved set (53 packages, transitives included) and is committed;
  `requirements.txt` / `requirements-test.txt` are **generated** and must never
  be hand-edited. After any dependency change:

  ```bash
  uv lock                 # or `uv add <pkg>` / `uv remove <pkg>`, which lock for you
  uv export --frozen --no-dev --no-hashes --no-emit-project -o requirements.txt
  uv export --frozen --no-hashes --no-emit-project -o requirements-test.txt
  ```

  `translator/tests/test_dependency_manifests.py` fails if you skip the export
  step, or bump a pin in `pyproject.toml` without re-locking. It parses both
  files with plain regex — no uv and no `tomllib` at test time, because
  `tomllib` is 3.11+ and the server runs 3.10.

  The generated files exist because the production host installs by hand and may
  not have uv. They are a *fallback*, not a second source of truth — which is the
  distinction that was missing before, when all three files were hand-maintained
  copies and the skew left production on kurigram 2.2.23 against code needing
  2.2.26.
- **`[tool.uv] package = false`** — this repo is run from a checkout with the
  root on `PYTHONPATH`; neither `translator` nor `app` was ever installed as a
  distribution, and setuptools has no package config to do it with. Without that
  flag `uv sync` would try to build and install the project itself.
- `python-telegram-bot` lags the current Bot API (22.8 targets 10.0 vs Telegram's
  10.3), which is harmless because PTB is only a `get_chat`/`get_file` RPC client —
  the relay's own sends go through `TelegramSender`'s raw calls.
- `translator/tests/test_utils_html.py` drives kurigram's **real** parser through
  semi-private paths (`pyrogram.parser.html.HTML.unparse`,
  `parser_utils.add_surrogates`), so it is the canary for a kurigram bump. Its
  filters are `isinstance`-based since 2.2.26, which is why message stand-ins in
  `test_admin_auth.py` must be real `Message` instances, not `SimpleNamespace`.
- **Custom emoji** (`utils/custom_emoji.py`, `PRESERVE_CUSTOM_EMOJI`, default
  **`auto`**). A bot may put custom emoji into a **channel** post only if it owns
  an extra username bought on Fragment — the Bot API 9.4 allowance for a
  Premium owner covers private chats and groups, *not* channels. In `auto` the
  `<tg-emoji>` tags are kept (the prompt tells the model to copy them verbatim);
  if Telegram answers 400 to a request carrying them, `TelegramSender._post_telegram`
  re-sends it once flattened to the plain fallback emoji and, on success,
  remembers the refusal for 24h so later posts are flattened up front (one
  refused call a day, never a lost post). `1` always keeps them (still with the
  retry), `0` always flattens (the old behaviour). The Flask sanitizer
  (`app/admin_manager._preserve_custom_emoji`) flattens only when the variable is
  unset.
