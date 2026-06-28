"""
Bidirectional Pyrogram ⇆ PTB relay bot.

• Pyrogram прослушивает исходные каналы.
• Для каждого сообщения формирует MetadataRequest и кладёт в очередь.
• Фоновый ptb_worker снимает запрос, вытаскивает максимум метаданных через Bot API
  и резолвит future.
• Pyrogram дожидается future, обогащает сообщение и переводит/пересылает.

"""

from __future__ import annotations

import os
import sys
import logging

# ensure project root is on PYTHONPATH when running this file directly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from datetime import timezone, datetime
import asyncio
import html
import signal
import time
import sqlite3
from typing import Any, Dict, Tuple

from anthropic import Anthropic
from translator.config import CONFIG, CACHE_DIR
from translator.models import MetadataRequest

from pyrogram import filters
from pyrogram.client import Client
from telegram.error import TelegramError
from telegram.ext import Application

# === Utility imports ===
from translator.utils.utils_html import entities_to_html
from translator.utils.utils_async import run_with_retries
from translator.utils.translation_utils import translate_html
from translator.utils.message_utils import get_media_info, build_payload
from translator.services.telegram_sender import TelegramSender
from translator.services.event_logger import EventRecorder

# PTB optional rate limiter
try:
    from telegram.ext import AIORateLimiter  # type: ignore
except ImportError:  # pragma: no cover
    AIORateLimiter = None

query_queue = asyncio.Queue()


###############################################################################
# Logging
###############################################################################
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# Ensure cache directory exists for logs
os.makedirs(CACHE_DIR, exist_ok=True)
LOG_FILE_PATH = os.path.join(CACHE_DIR, "bot.log")

try:
    # Set up file logging
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format="%(asctime)s — %(levelname)s — %(name)s — %(message)s",
        filename=LOG_FILE_PATH,  # Log file path in cache/
        filemode="a",  # Append mode
        encoding="utf-8",  # Ensure UTF-8 output
    )
except OSError as e:
    print(f"WARNING: Could not write to log file {LOG_FILE_PATH}: {e}")
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format="%(asctime)s — %(levelname)s — %(name)s — %(message)s",
    )

# Set up console logging (StreamHandler)
console = logging.StreamHandler()
console.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
formatter = logging.Formatter("%(asctime)s — %(levelname)s — %(name)s — %(message)s")
console.setFormatter(formatter)
logging.getLogger().addHandler(console)

logger = logging.getLogger("MAIN")
pyro_log = logging.getLogger("PYRO")
ptb_log = logging.getLogger("PTB")

# Add a runtime check for log file writability and log to console if not writable
try:
    with open(LOG_FILE_PATH, "a", encoding="utf-8") as f:
        pass
except OSError as e:
    logger = logging.getLogger()
    logger.error(
        "OSError: write error to log file %s: %s. Logging to console only.",
        LOG_FILE_PATH,
        e,
    )


###############################################################################
# PTB‑worker (метаданные вложений)
###############################################################################
async def ptb_worker(ptb_app: Application, stop_event: asyncio.Event):
    """Fetch **all** Bot‑API data we can access: chat info + file info."""
    bot = ptb_app.bot
    ptb_log.info("PTB‑worker started")
    while not stop_event.is_set():
        req = await query_queue.get()
        ptb_log.info("Queue GET %s", req)

        # start meta with every attribute present in req
        meta: Dict[str, Any] = req.__dict__.copy()
        # ptb_log.info("Initial meta: %s", meta)
        # ensure future not leaked to meta
        meta.pop("response", None)
        meta["chat"] = None
        meta["file"] = None
        # 1 Chat‑level information ---------------------------------------
        try:
            chat_obj = await bot.get_chat(req.chat_id)
            meta["chat"] = chat_obj.to_dict()
            if getattr(chat_obj, "username", None):
                meta["chat_link"] = f"https://t.me/{chat_obj.username}"
            else:
                meta["chat_link"] = None
        except TelegramError as e:
            ptb_log.warning("get_chat failed for %s: %s", req.chat_id, e)
            meta["chat_error"] = str(e)

        # 2 File‑level information (<=20 MB) -----------------------------
        if req.file_id:
            try:
                file_obj = await bot.get_file(req.file_id)
                meta["file"] = file_obj.to_dict()
                if file_obj.file_path:
                    meta["file_download_link"] = (
                        f"https://api.telegram.org/file/bot{bot.token}/{file_obj.file_path}"
                    )
            except TelegramError as e:
                err_msg = str(e)
                if "File is too big" in err_msg:
                    ptb_log.warning("File too big (>20MB) %s", req.file_id)
                    meta["file_error"] = "too_big"
                else:
                    ptb_log.warning("Bot API error: %s", err_msg)
                    meta["file_error"] = err_msg

        req.response.set_result(meta)


###############################################################################
# Pyrogram handler
###############################################################################


def register_handlers(
    pyro: Client, anthropic: Anthropic, sender: TelegramSender, recorder: EventRecorder
):
    max_size = 20 * 1024 * 1024

    # The following handler matches ALL channel messages, which can cause duplicate handling
    @pyro.on_message(filters.channel & filters.chat(CONFIG.get_source_channel_ids()))
    async def handle_message(_: Client, msg):
        pyro_log.info("\n\n")
        pyro_log.info("=============================================")
        pyro_log.info("==== BEGIN HANDLING MESSAGE %s ====", msg.id)
        pyro_log.info("=============================================")

        # === 0. Prepare recorder and extract metadata ===
        recorder.set(timestamp=datetime.now(timezone.utc).isoformat())
        recorder.set(source_channel_id=msg.chat.id, source_channel_name=msg.chat.title)
        recorder.set(event_type="create")
        text = msg.text or msg.caption or ""
        file_id, file_size_bytes, media_type = get_media_info(msg, max_size)

        recorder.set(
            media_type=media_type,
            file_size_bytes=file_size_bytes,
            original_size=len(text),
        )
        # === 1. Request metadata from PTB ===
        req = MetadataRequest(msg.chat.id, msg.id, file_id)
        raw_entities = msg.entities or msg.caption_entities or []
        req.message_entities = [
            e.to_dict() if hasattr(e, "to_dict") else e for e in raw_entities
        ]
        try:
            await query_queue.put(req)
            meta = await req.response
            file_path = meta.get("file").get("file_path")
            recorder.set(file_path=file_path)
            # Convert entities to HTML
            html_text = entities_to_html(text, msg.entities or msg.caption_entities)
        except Exception as e:
            pyro_log.warning("!!! PTB worker failed: %s", e)
            meta = {}
            html_text = text

        # === 2. Build payload and log original message ===
        payload = build_payload(msg, html_text, meta)
        recorder.set(
            message_id=(getattr(msg, "id", None) or getattr(msg, "message_id", None))
        )

        # === 3. Translate message ===
        translation_start = time.monotonic()
        retry_count = 0
        translation_time = None
        translated = ""
        exception_message = None
        api_error_code = None

        dest_id = CONFIG.get_destination_id(recorder.get("source_channel_id"))
        recorder.set(dest_channel_id=dest_id)
        recorder.set(dest_channel_name=CONFIG.get_channel_name(dest_id))
        pyro_log.info(
            "Source channel: %s (%s), Dest - id: %s name: %s",
            recorder.get("source_channel_name"),
            recorder.get("source_channel_id"),
            dest_id,
            recorder.get("dest_channel_name"),
        )
        try:
            translated = await run_with_retries(translate_html, anthropic, payload)
            translation_time = time.monotonic() - translation_start
            # pyro_log.info("Translated message: %s", translated)
            recorder.set(
                source_message=html.escape(html_text),
                translated_size=len(translated),
                translated_message=html.escape(translated),
                translation_time=translation_time,
                retry_count=retry_count,
            )
            if (
                media_type == "photo"
                and meta.get("file_download_link")
                and len(translated) < 1024
            ):
                pyro_log.info(
                    "Detected photo message; ready to process photo with file download link."
                )
                await run_with_retries(
                    sender.send_photo_message, file_id, translated, recorder
                )
            else:
                await run_with_retries(sender.send_message, translated, recorder)
            pyro_log.info(
                "DONE chat:%s msg:%s → destination msg: %s",
                msg.chat.title,
                msg.id,
                dest_id,
            )
        except Exception as exc:
            exception_message = str(exc)
            api_error_code = getattr(exc, "status", None)
            recorder.set(
                exception_message=exception_message, api_error_code=api_error_code
            )
            pyro_log.error("FAILED %s: %s", msg.id, exc)
        # === 4. Log event and finalize recorder ===
        recorder.finalize()
        pyro_log.info("=============================================")
        pyro_log.info("==== END HANDLING MESSAGE %s ====", msg.id)
        pyro_log.info("=============================================")

    @pyro.on_edited_message(
        filters.channel & filters.chat(CONFIG.get_source_channel_ids())
    )
    async def handle_edit_message(_: Client, msg):
        pyro_log.info("\n\n")
        pyro_log.info("=============================================")
        pyro_log.info("==== BEGIN HANDLING EDITED MESSAGE %s ====", msg.id)
        pyro_log.info("=============================================")
        # === 0. Prepare recorder and extract metadata ===
        recorder.set(timestamp=datetime.now(timezone.utc).isoformat())
        recorder.set(source_channel_id=msg.chat.id, source_channel_name=msg.chat.title)
        recorder.set(event_type="create")
        text = msg.text or msg.caption or ""
        file_id, file_size_bytes, media_type = get_media_info(msg, max_size)

        recorder.set(
            media_type=media_type,
            file_size_bytes=file_size_bytes,
            original_size=len(text),
        )

        text = msg.text or msg.caption or ""
        file_id, file_size_bytes, media_type = get_media_info(msg, max_size)

        # === 1. Request metadata from PTB ===TB
        req = MetadataRequest(msg.chat.id, msg.id, file_id)
        raw_entities = msg.entities or msg.caption_entities or []
        req.message_entities = [
            e.to_dict() if hasattr(e, "to_dict") else e for e in raw_entities
        ]
        try:
            await query_queue.put(req)
            meta = await req.response
            html_text = entities_to_html(text, msg.entities or msg.caption_entities)
        except Exception as e:
            pyro_log.warning("!!! PTB worker failed: %s", e)
            meta = {}
            html_text = text

        # === 2. Build payload and log original message ===
        payload = build_payload(msg, html_text, meta)
        recorder.set(
            message_id=(getattr(msg, "id", None) or getattr(msg, "message_id", None))
        )
        # === 3. Translate message ===
        translation_start = time.monotonic()
        retry_count = 0
        translation_time = None
        translated = ""
        exception_message = None
        api_error_code = None

        try:
            # Get destination message ID from events log
            source_channel_id: int = msg.chat.id  # Use message's channel ID directly
            message_id: str = str(msg.id)  # Convert message ID to string
            
            # Record source info first
            recorder.set(
                source_channel_id=source_channel_id,
                message_id=message_id
            )

            # Get destination message mapping
            dest_id = CONFIG.get_destination_msg_id(source_channel_id, message_id)
            if not dest_id:
                raise ValueError(
                    f"No destination message found for source channel {source_channel_id}, "
                    f"message {message_id}"
                )

            # Get destination channel info
            dest_channel_id = CONFIG.get_destination_id(source_channel_id)
            recorder.set(
                dest_channel_id=dest_channel_id,
                dest_channel_name=CONFIG.get_channel_name(dest_channel_id)
            )
            
            pyro_log.info(
                "Source channel: %s (%s), Dest channel: %s (%s), Dest msg: %s",
                msg.chat.title,
                source_channel_id,
                recorder.get("dest_channel_name"),
                dest_channel_id,
                dest_id
            )

            pyro_log.info("Translating edited message %s → %s...", msg.id, dest_id)
            translated = await run_with_retries(translate_html, anthropic, payload)
            pyro_log.info("Translated.")

            # Now edit the message in the dest channel
            await run_with_retries(
                sender.edit_message, dest_channel_id, dest_id, translated, recorder
            )
            pyro_log.info(
                "EDIT DONE chat:%s msg:%s → destination msg: %s",
                msg.chat.title,
                msg.id,
                dest_id,
            )
        except Exception as exc:
            pyro_log.error("FAILED TO EDIT %s: %s", msg.id, exc)
            recorder.set(
                exception_message=exception_message, api_error_code=api_error_code
            )

        recorder.finalize()
        pyro_log.info("=============================================")
        pyro_log.info("==== END HANDLING EDITED MESSAGE %s ======", msg.id)
        pyro_log.info("=============================================")


###############################################################################
# Main                                                                        #
###############################################################################
async def main_async():
    logger.info("=== BOT STARTUP ===")
    # --- Session lock check ---
    session_file = "bot.session"
    if os.path.exists(session_file):
        try:
            conn = sqlite3.connect(session_file)
            conn.execute("PRAGMA quick_check")
            conn.close()
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e):
                logger.error(
                    "Session file %s is locked. Stop all bots and delete this file before restarting.",
                    session_file,
                )
                raise
    # --- end session lock check ---

    pyro, ptb_app, anthropic, sender, event_recorder = init_clients()

    register_handlers(pyro, anthropic, sender, event_recorder)
    # register_channel_logger(pyro)

    await ptb_app.initialize()

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass

    asyncio.create_task(ptb_worker(ptb_app, stop_event))

    await pyro.start()
    pyro_log.info("Pyrogram started — Ctrl-C to exit")

    await stop_event.wait()

    pyro_log.info("Shutting down …")
    await ptb_app.stop()
    await pyro.stop()
    logger.info("=== BOT SHUTDOWN COMPLETE ===")


def init_clients() -> (
    Tuple[Client, Application, Anthropic, TelegramSender, EventRecorder]
):
    pyro = Client(
        "bot",
        api_id=CONFIG.TELEGRAM_API_ID,
        api_hash=CONFIG.TELEGRAM_API_HASH,
        bot_token=CONFIG.TELEGRAM_BOT_TOKEN,
    )
    builder = Application.builder().token(CONFIG.TELEGRAM_BOT_TOKEN)
    if AIORateLimiter is not None:
        try:
            builder = builder.rate_limiter(AIORateLimiter())
        except RuntimeError:
            pass
    ptb_app = builder.build()
    recorder = EventRecorder()
    anthropic_client = Anthropic(api_key=CONFIG.ANTHROPIC_API_KEY)
    sender = TelegramSender()
    return pyro, ptb_app, anthropic_client, sender, recorder


if __name__ == "__main__":
    try:
        asyncio.run(main_async())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Interrupted by user")
