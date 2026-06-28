# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Telegram bot that mirrors Russian-language Telegram channels into paired
English channels, translating each post with the Anthropic API. It ships with a
Flask admin web app for monitoring throughput, editing the prompt, and manually
re-translating / re-posting individual messages.

There are **two independent entry points** that share the `translator` package
and a single JSON event log:

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
root via `python-dotenv`. `translator/config.py` builds a frozen `Config`
singleton (`CONFIG`) at import time and **raises `RuntimeError` on any missing
required variable** — importing almost anything will fail without a complete env.

Channels are organized as **logical pairs**. For each logical name in
`("christianvision", "shaltnotkill", "test")` the config reads:

- `<NAME>_CHANNEL` — source channel ID (Russian)
- `<NAME>_EN_CHANNEL_ID` — destination channel ID (English)

These become two `ChannelInfo` entries (`<name>` as `"source"`, `<name>_en` as
`"destination"`) that point at each other via `pair_key`. The lookup helpers
(`get_destination_id`, `get_channel_name`, `get_source_channel_ids`) are the
canonical way to resolve channels — use them rather than reading env vars
directly. Other required vars: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_API_ID`,
`TELEGRAM_API_HASH`, `ANTHROPIC_API_KEY`, `TEST_CHANNEL`. Admin app also reads
`ADMIN_PASSWORD`, `SECRET_KEY`.

> Security note: the working-tree `.env` currently contains **real, live API
> keys and tokens**. It is gitignored, but treat these as secrets — do not echo
> them, paste them into code, or commit them anywhere.

## Architecture — the relay bot

The bot runs **two Telegram clients at once** because neither alone exposes
everything needed:

1. **Pyrogram** (`Client`, MTProto, user-level) listens to source channels via
   `@pyro.on_message` / `@pyro.on_edited_message` filtered to
   `CONFIG.get_source_channel_ids()`. It receives full message content and
   entities.
2. **python-telegram-bot** (`Application`, Bot API) cannot listen to arbitrary
   channels but *can* resolve chat metadata and file download links.

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
   `utils/utils_async.run_with_retries` (3 attempts, 2s delay).
5. Send via `services/telegram_sender.TelegramSender` — `send_photo_message`
   when it's a photo with a download link and caption < 1024 chars, else
   `send_message` (which splits at the 4096-char limit). `TelegramSender` talks
   to the **raw Bot API over `requests`**, not via PTB.
6. Record the outcome with `services/event_logger.EventRecorder`.

**Edits** are handled separately: the edit handler looks up the previously-sent
destination message ID via `CONFIG.get_destination_msg_id(...)` (which scans
`events.json` newest-first) and calls `TelegramSender.edit_message`. That method
does aggressive content-equality normalization (`sanitize_html`,
`telegram_normalize_text`, `advanced_content_comparison`) to avoid Telegram's
"message is not modified" error.

On startup `main_async` does a SQLite `PRAGMA quick_check` on `bot.session` and
refuses to start if the session is locked (i.e. another bot instance is
running) — delete the session file only after stopping all instances.

## Architecture — the event log (the de-facto database)

There is no database. `translator/cache/events.json` (`EVENTS_PATH`) is the
single source of truth: a `{"messages": [...]}` list of `MessageEvent` records
(see `translator/models.py`). It is:

- **Written** by `EventRecorder` — call `.set(field=...)` to accumulate a
  payload, then `.finalize()` to append and flush to disk. `.set()` raises
  `KeyError` for unknown fields, so fields must exist on `MessageEvent`.
- **Read** by `aggregator.py` (`load_messages` + `build_*` functions) to produce
  the dashboard's chart data, and by `config.get_destination_msg_id` for edit
  source→dest mapping.

Source→destination message mapping for edits/deletes is derived entirely by
scanning these events, not stored in a separate index.

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
  `bleach` (`clean_telegram_html`, allowed tags `b/i/u/a/code`).
- `bp` (`/api/metrics/summary`) — JSON for the dashboard charts.

The manager and aggregator code is heavily instrumented with `print(...)`
"banner" debug logging — that's intentional existing style, not dead code.

## Translation specifics

`translate_html` calls **`claude-3-haiku-20240307`** (`temperature=0`,
`max_tokens=1500`). The system/instructions/example prompt lives in
`translator/prompt_template.txt` (loaded via `config.load_prompt_template`) and
encodes strict literal-translation rules (preserve HTML links/URLs, hashtags,
paragraph `<p>` tags, wrap the first sentence in `<b>`, never relabel Belarusian
church names as "Russian orthodox"). Short messages (< 7 words or < 20 chars)
bypass the full template. The response is post-processed to strip stray
`<translation>/<source>/<system>/...` wrapper tags the model sometimes emits.

## Conventions & gotchas

- **Dependency drift:** `requirements.txt` (and the actual code) use
  **`pyrogram`**, but `pyproject.toml` lists `telethon` — the code uses Pyrogram.
  `test.bat` installs `requirements-test.txt`, which is **not in the repo**; add
  it or install test deps manually (`pytest`, `pytest-asyncio`, `pytest-cov`).
- Inline comments and the `bot.py` module docstring are in **Russian** — match
  the surrounding language when editing those areas.
- `EventRecorder.prefill` initializes `float` fields to `False` (a pre-existing
  quirk) — be deliberate when changing `MessageEvent` field types.
- Telegram limits enforced in code: 4096 chars/message, 1024 chars for photo
  captions, 20 MB for Bot API file fetches (`max_size` in the handler).
