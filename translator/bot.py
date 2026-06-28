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
from translator.services.anthropic_client import get_anthropic_client

from pyrogram import filters
from pyrogram.client import Client
from telegram.error import TelegramError
from telegram.ext import Application

# === Utility imports ===
from translator.utils.utils_html import entities_to_html
from translator.utils.utils_async import run_with_retries
from translator.utils.single_instance import (
    acquire_single_instance_lock,
    AlreadyRunningError,
)
from translator.utils.translation_utils import translate_html
from translator.utils.message_utils import get_media_info, build_payload
from translator.services.telegram_sender import TelegramSender
from translator.services.event_logger import EventRecorder
from translator.services.error_sender import send_alert

# PTB optional rate limiter
try:
    from telegram.ext import AIORateLimiter  # type: ignore
except ImportError:  # pragma: no cover
    AIORateLimiter = None

query_queue = asyncio.Queue()

# Max seconds to wait for the PTB worker to answer a metadata request. On timeout
# the handler degrades to no-metadata instead of blocking forever on the future.
META_TIMEOUT = float(os.getenv("META_TIMEOUT", "30"))


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


def _edit_target_mismatch(recorder: EventRecorder) -> bool:
    """True if the last edit failed because text/caption method was mismatched.

    editMessageText on a media post → "there is no text in the message to edit";
    editMessageCaption on a text post → "there is no caption in the message to
    edit". Either means we should retry with the other method.
    """
    msg = str(recorder.get("exception_message") or "").lower()
    return (
        "no text in the message to edit" in msg
        or "no caption in the message to edit" in msg
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

        # The handler may have already given up (wait_for timeout cancelled the
        # future); setting a result then would raise InvalidStateError.
        if not req.response.done():
            req.response.set_result(meta)
        else:
            ptb_log.warning(
                "Dropping metadata for chat %s msg %s: request already timed out/cancelled",
                req.chat_id,
                req.message_id,
            )


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
            meta = await asyncio.wait_for(req.response, timeout=META_TIMEOUT)
            # `file` is None for text-only posts; guard so they don't fall into
            # the except branch and lose entity→HTML conversion.
            file_obj = meta.get("file") or {}
            if file_obj.get("file_path"):
                recorder.set(file_path=file_obj["file_path"])
            html_text = entities_to_html(text, msg.entities or msg.caption_entities)
        except asyncio.TimeoutError:
            pyro_log.warning("PTB worker timed out after %ss; degrading metadata", META_TIMEOUT)
            meta = {}
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
            media_dispatch = {
                "photo": sender.send_photo_message,
                "video": sender.send_video_message,
                "doc": sender.send_document_message,
            }
            send_media = media_dispatch.get(media_type)
            if send_media and meta.get("file_download_link"):
                if len(translated) < 1024:
                    pyro_log.info(
                        "Detected %s message; re-sending media with translated caption.",
                        media_type,
                    )
                    await run_with_retries(send_media, file_id, translated, recorder)
                else:
                    # Caption exceeds Telegram's 1024-char media limit: post the
                    # media (no caption) then the full translation as a separate
                    # text message so the media isn't dropped.
                    pyro_log.info(
                        "Caption too long for %s media (%d chars); sending media + follow-up text.",
                        media_type,
                        len(translated),
                    )
                    await run_with_retries(send_media, file_id, "", recorder)
                    await run_with_retries(sender.send_message, translated, recorder)
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
            await send_alert(
                f"Relay FAILED for msg {msg.id} in '{msg.chat.title}': {exc}",
                key="relay-fail",
            )
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
        recorder.set(event_type="edit")
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
            meta = await asyncio.wait_for(req.response, timeout=META_TIMEOUT)
            html_text = entities_to_html(text, msg.entities or msg.caption_entities)
        except asyncio.TimeoutError:
            pyro_log.warning("PTB worker timed out after %ss; degrading metadata", META_TIMEOUT)
            meta = {}
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

            # Route the edit by how the post was originally delivered: media
            # posts (photo/video/doc whose caption fits) were sent with a
            # caption and must be edited via editMessageCaption; everything else
            # via editMessageText. Recompute the same decision used on send, and
            # self-heal by retrying the other method if Telegram reports the
            # target had no text/caption.
            is_media_delivery = (
                media_type in ("photo", "video", "doc")
                and meta.get("file_download_link")
                and len(translated) < 1024
            )
            if is_media_delivery:
                ok = await run_with_retries(
                    sender.edit_caption, dest_channel_id, dest_id, translated, recorder
                )
                if not ok and _edit_target_mismatch(recorder):
                    await run_with_retries(
                        sender.edit_message, dest_channel_id, dest_id, translated, recorder
                    )
            else:
                ok = await run_with_retries(
                    sender.edit_message, dest_channel_id, dest_id, translated, recorder
                )
                if not ok and _edit_target_mismatch(recorder):
                    await run_with_retries(
                        sender.edit_caption, dest_channel_id, dest_id, translated, recorder
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
            await send_alert(
                f"Edit relay FAILED for msg {msg.id} in '{msg.chat.title}': {exc}",
                key="edit-fail",
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
    # --- Single-instance guard ---
    # Exclusive advisory lock: refuses to start if another instance is running
    # (even an idle one), preventing duplicate posting. Released on process exit.
    try:
        acquire_single_instance_lock(os.path.join(CACHE_DIR, "bot.lock"))
    except AlreadyRunningError as e:
        logger.error("%s", e)
        raise
    # Corruption check on the MTProto session DB (separate concern from locking).
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
    # --- end single-instance guard ---

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
    anthropic_client = get_anthropic_client()
    sender = TelegramSender()
    return pyro, ptb_app, anthropic_client, sender, recorder


if __name__ == "__main__":
    try:
        asyncio.run(main_async())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Interrupted by user")
