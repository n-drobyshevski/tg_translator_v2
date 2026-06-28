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

```bash
# Run the relay bot (it adds the repo root to sys.path itself)
python translator/bot.py

# Run the admin web app — must run from the app/ directory with repo root on PYTHONPATH,
# because flask_app.py mixes bare imports (admin_dashboard) and package imports (app.admin_events, translator.*)
cd app && PYTHONPATH=<repo-root> python flask_app.py   # serves on 0.0.0.0:5000

# Tests (Windows convenience script: creates .venv, installs, runs pytest+coverage)
test.bat

# Tests directly
PYTHONPATH=<repo-root> pytest --cov=translator
PYTHONPATH=<repo-root> pytest translator/tests/test_config.py            # one file
PYTHONPATH=<repo-root> pytest translator/tests/test_config.py::test_name # one test
```

Test config lives in `translator/pytest.ini` (`asyncio_mode = auto`, so async
tests need no decorator; `python_files = tests/test_*.py`).

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
DM commands and receives error alerts). Admin app also reads `ADMIN_PASSWORD`,
`SECRET_KEY`.

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
5. Send via `services/telegram_sender.TelegramSender` — `send_photo_message`
   when it's a photo with a download link and caption < 1024 chars, else
   `send_message` (which splits at the 4096-char limit). `TelegramSender` talks
   to the **raw Bot API over `httpx.AsyncClient`** (a fresh client per call, since
   it's shared by the async bot and the per-request-loop Flask app), not via PTB.
6. Record the outcome with `services/event_logger.EventRecorder`.

**Edits** are handled separately: the edit handler looks up the previously-sent
destination message ID via `CONFIG.get_destination_msg_id(...)` (which scans
`events.json` newest-first) and calls `TelegramSender.edit_message`. That method
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
  read-only `/help /status /stats /config /channels /prompt`; writable
  `/setmodel /settemp /setmaxtokens /setloglevel /setprompt`; channel management
  `/addchannel /editchannel /removechannel`; and `/reload`. Replies are
  HTML-escaped and truncated under the 4096-char cap.
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
  `reload()` raise. Caveat surfaced in the reply: the bot must already be an
  admin/member of the source channel or Telegram delivers nothing.
- **Error forwarding:** `services/error_sender.send_alert` (httpx → Bot API,
  throttled ~300s per signature `key`) now reads `ADMIN_ALERT_CHAT_ID` **or**
  falls back to `ADMIN_CHAT_ID` — previously it was a silent no-op since `.env`
  only defines the latter. `services/log_forwarding.py` additionally attaches a
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
  indexed seek via `idx_events_src_msg`, not a full scan).

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
default **`claude-haiku-4-5`** — the old `claude-3-haiku-20240307` was retired by
Anthropic on 2026-04-20). `ANTHROPIC_MAX_TOKENS`/`ANTHROPIC_TEMPERATURE` are also
env-overridable (defaults 1500 / 0). The system/instructions/example prompt lives in
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
  captions, 20 MB for Bot API file fetches (`max_size` in the handler).
