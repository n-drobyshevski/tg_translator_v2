import html as _html
import json
import logging
import os
import re
from typing import List, Optional, Tuple, Any

import httpx
from dotenv import load_dotenv
from translator.config import CHANNEL_CONFIGS, BOT_TOKEN
from translator.services.event_logger import EventRecorder
from translator.utils import custom_emoji


load_dotenv()

# Default timeout for all Bot API calls.
_HTTP_TIMEOUT = 10

def _env_flag(name: str, default: bool) -> bool:
    """Read a boolean env var; blank/unset falls back to ``default``."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "no", "")


# Link preview ("message filling") control for relayed/edited text posts.
# build_payload appends a "Source channel:" link, so an enabled preview renders
# that card. Previews are ON by default; set DISABLE_LINK_PREVIEW=1 to turn them
# off. This is the modern replacement for the deprecated disable_web_page_preview
# flag (Bot API 7.0+).
DISABLE_LINK_PREVIEW = _env_flag("DISABLE_LINK_PREVIEW", False)


def build_link_preview_options() -> dict:
    """Build the LinkPreviewOptions object sent with text messages and edits.

    Disabled → ``{"is_disabled": True}``. Enabled → modern rich options
    (large media + optional positioning / pinned URL), all env-overridable:
    ``LINK_PREVIEW_PREFER_LARGE_MEDIA`` (default on), ``LINK_PREVIEW_SHOW_ABOVE_TEXT``
    (default off) and ``LINK_PREVIEW_URL`` (default: let Telegram pick the first link).
    """
    if DISABLE_LINK_PREVIEW:
        return {"is_disabled": True}
    options = {
        "prefer_large_media": _env_flag("LINK_PREVIEW_PREFER_LARGE_MEDIA", True),
        "prefer_small_media": _env_flag("LINK_PREVIEW_PREFER_SMALL_MEDIA", False),
        "show_above_text": _env_flag("LINK_PREVIEW_SHOW_ABOVE_TEXT", False),
    }
    pinned_url = os.getenv("LINK_PREVIEW_URL")
    if pinned_url:
        options["url"] = pinned_url
    return options


def _as_form_value(value: Any) -> Any:
    """Encode one option value for a *form-encoded* Bot API body.

    Nested objects go as JSON strings (the treatment ``link_preview_options``
    already gets on the edit path), and booleans must be lowercase JSON literals —
    httpx would otherwise form-encode Python's ``True``, which is not one of the
    values Telegram documents for Boolean fields.
    """
    if isinstance(value, (dict, list, bool)):
        return json.dumps(value)
    return value


def build_reply_parameters(message_id: Optional[int]) -> Optional[dict]:
    """Build the ReplyParameters object (Bot API 7.0+) for a reply, or None.

    Replaces the legacy scalar ``reply_to_message_id``. ``allow_sending_without_reply``
    is a behaviour fix, not just modernization: a long-caption post is relayed as
    media + a reply carrying the remainder, and if the media is deleted in the gap
    between the two calls the old parameter made Telegram reject the remainder
    outright, silently losing the bulk of the message. With this flag the remainder
    is posted unlinked instead of lost.
    """
    if not message_id:
        return None
    return {"message_id": message_id, "allow_sending_without_reply": True}


def build_send_options(*, with_caption: bool = False) -> dict:
    """Common, env-gated options shared by every send call.

    Kept in one place so sendMessage / sendPhoto / sendMediaGroup / the edit paths
    can't drift apart. All default to the historical behaviour (everything off).

    ``show_caption_above_media`` (Bot API 7.10) only applies to captioned media, so
    it is emitted only when ``with_caption`` is set.
    """
    options = {}
    if _env_flag("PROTECT_CONTENT", False):
        options["protect_content"] = True
    if _env_flag("DISABLE_NOTIFICATION", False):
        options["disable_notification"] = True
    if with_caption and _env_flag("SHOW_CAPTION_ABOVE_MEDIA", False):
        options["show_caption_above_media"] = True
    return options


def record_sent(recorder: EventRecorder, *message_ids: Any) -> None:
    """Append destination message ids to ``dest_message_ids`` (send order).

    Every message a post produces is kept — text chunks, a caption's remainder
    reply, each album item — because a deletion of the source post must remove
    all of them, and a reply to it must point at the first.
    """
    new = [str(i) for i in message_ids if i not in (None, "", 0)]
    if not new:
        return
    existing = recorder.get("dest_message_ids") or ""
    recorder.set(dest_message_ids=",".join([p for p in existing.split(",") if p] + new))


# Shared regexes (compiled once instead of re-importing/re-compiling per call).
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
# Zero-width / BOM characters that aren't matched by \s but should be dropped.
_ZERO_WIDTH_RE = re.compile("[​-‍⁠﻿]")

def sanitize_html(text: str) -> str:
    """Sanitize HTML for Telegram by removing or replacing unsupported tags."""
    if not text:
        return ""
    
    # Apply sanitization rules
    sanitized = (
        text.replace("<p>", "")
        .replace("</p>", "\n")  # Changed to add newline instead of removing
        .replace("<br>", "\n")
        .replace("<br/>", "\n")
        .replace("<br />", "\n")
    )
    
    # Normalize whitespace to prevent false differences
    sanitized = "\n".join(line.rstrip() for line in sanitized.split("\n"))
    # Collapse runs of 3+ newlines (two or more blank lines) down to a single
    # blank line. The </p> -> "\n" replacement above stacks onto the model's own
    # blank line between <p> blocks, which otherwise yields doubled paragraph gaps.
    sanitized = re.sub(r"\n{3,}", "\n\n", sanitized)
    sanitized = sanitized.strip()

    return sanitized


def normalize_for_comparison(text: str) -> str:
    """Normalize text for content comparison by removing formatting differences."""
    if not text:
        return ""
    # Strip HTML tags, then collapse all whitespace to single spaces.
    return _WS_RE.sub(" ", _TAG_RE.sub("", text).strip())


def telegram_normalize_text(text: str) -> str:
    """Normalize text to approximate Telegram's internal content comparison.

    More aggressive than ``normalize_for_comparison``: it applies the same
    sanitization used for sending, strips tags, decodes HTML entities with the
    stdlib ``html.unescape`` (full entity coverage, not a hand-rolled table),
    drops zero-width characters, and collapses all (incl. Unicode) whitespace.
    """
    if not text:
        return ""
    normalized = sanitize_html(text)
    normalized = _TAG_RE.sub("", normalized)
    normalized = _html.unescape(normalized)
    normalized = _ZERO_WIDTH_RE.sub("", normalized)
    return _WS_RE.sub(" ", normalized.strip())


def advanced_content_comparison(text1: str, text2: str) -> bool:
    """Return True if two texts would be considered identical by Telegram.

    Tries progressively more aggressive normalizations (direct equality \u2192
    send-time sanitization \u2192 full Telegram-style normalization). The last stage
    subsumes the basic tag/whitespace pass, so no separate step is needed.
    """
    if not text1 and not text2:
        return True
    if not text1 or not text2:
        return False
    if text1 == text2:
        return True
    if sanitize_html(text1) == sanitize_html(text2):
        return True
    if telegram_normalize_text(text1) == telegram_normalize_text(text2):
        return True
    return False


def get_channel_config(target: str):
    cfg = CHANNEL_CONFIGS.get(target)
    if not cfg:
        logging.error("No channel config for destination key %r", target)
        return None, "No channel config for destination key"
    if not getattr(cfg, "channel_id", None):
        logging.error("No channel_id for %s", target)
        return None, "No channel_id for target"
    return cfg, None


class TelegramSender:
    def __init__(self):
        self.configs = CHANNEL_CONFIGS
        self.MAX_MESSAGE_LENGTH = 4096

    def split_message(self, text: str) -> List[str]:
        """Split into <=4096‑char chunks, preserving lines."""
        if len(text) <= self.MAX_MESSAGE_LENGTH:
            return [text]
        messages, current = [], ""
        for line in text.split("\n"):
            if len(current) + len(line) + 1 > self.MAX_MESSAGE_LENGTH:
                messages.append(current.rstrip("\n"))
                current = line + "\n"
            else:
                current += line + "\n"
        if current:
            messages.append(current.rstrip("\n"))
        return messages

    def _extract_meta_fields(
        self, meta: Any, target: str
    ) -> Tuple[str, Optional[int], Optional[str], Optional[Any]]:
        """Extract media_type, file_size_bytes, source_channel, message_id from meta/source_msg."""
        media_type = "text"
        file_size_bytes = None
        source_channel = None
        message_id = None
        if meta is not None:
            source_msg = meta.get("source_msg")
            if source_msg:
                if hasattr(source_msg, "photo") and getattr(source_msg, "photo", None):
                    media_type = "photo"
                    file_size_bytes = getattr(source_msg.photo, "file_size", None)
                elif hasattr(source_msg, "video") and getattr(
                    source_msg, "video", None
                ):
                    media_type = "video"
                    file_size_bytes = getattr(source_msg.video, "file_size", None)
                elif hasattr(source_msg, "document") and getattr(
                    source_msg, "document", None
                ):
                    media_type = "doc"
                    file_size_bytes = getattr(source_msg.document, "file_size", None)
                if hasattr(source_msg, "chat"):
                    source_channel = str(getattr(source_msg.chat, "id", None))
                message_id = getattr(source_msg, "id", None) or getattr(
                    source_msg, "message_id", None
                )
        if not source_channel and meta is not None:
            source_channel = str(meta.get("source_channel_id", ""))
        return media_type, file_size_bytes, source_channel, message_id

    def _store_message(
        self,
        sent_chat_id: Optional[int],
        sent_msg_id: Optional[int],
        source_msg: Any,
        target: str,
        html_content: str,
        meta: Any,
    ) -> None:
        mapping = meta.get("mapping") if meta else None
        dest_channel_id = None
        if mapping:
            for k, v in mapping.items():
                if v == target:
                    dest_channel_id = k
                    break
        if dest_channel_id:
            dest_msg_data = {
                "message_id": sent_msg_id,
                "date": getattr(source_msg, "date", None) if source_msg else None,
                "chat_title": target,
                "chat_username": "",
                "html": html_content,
                "source_channel_id": (
                    getattr(source_msg.chat, "id", None) if source_msg else "None"
                ),
                "source_message_id": (
                    (
                        getattr(source_msg, "message_id", None)
                        or getattr(source_msg, "id", None)
                    )
                    if source_msg
                    else "None"
                ),
            }
            # Note: Message storage functionality would go here
            # Currently disabled to avoid recursion issue

    async def _post_once(
        self, url: str, *, data: Optional[dict] = None, json: Optional[dict] = None
    ) -> Tuple[bool, Optional[httpx.Response], Optional[str]]:
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                r = await client.post(url, data=data, json=json)
            if r.status_code != 200:
                desc = None
                try:
                    desc = r.json().get("description", r.text)
                except Exception:
                    desc = r.text
                return False, r, desc
            return True, r, None
        except Exception as e:
            return False, None, str(e)

    async def _post_telegram(
        self, url: str, *, data: Optional[dict] = None, json: Optional[dict] = None
    ) -> Tuple[bool, Optional[httpx.Response], Optional[str]]:
        """
        Send a POST request to the Telegram Bot API (non-blocking via httpx).

        A fresh AsyncClient is created per call on purpose: this sender is used
        both by the bot's persistent event loop and by Flask routes that spin up
        a new loop per request (asyncio.run), and a shared client would bind to
        one loop and fail in the other.

        A request Telegram rejects (400) while it carries custom emoji is sent
        once more with them flattened to plain emoji — a bot may use custom
        emoji in a channel only with a Fragment username, and losing the whole
        post over its emoji would be worse. If that retry succeeds the refusal
        is remembered (see :mod:`translator.utils.custom_emoji`), so the next
        posts are flattened up front.

        Returns:
            (success, response, error_message)
            - success: True if status_code is 200, else False
            - response: httpx.Response object if available, else None
            - error_message: error description or exception string if failed, else None
        """
        ok, r, err = await self._post_once(url, data=data, json=json)
        if ok or r is None or r.status_code != 400:
            return ok, r, err
        if "not modified" in str(err).lower():
            # An identical edit, not an emoji refusal: the flattened text would
            # *differ*, so a retry would "succeed" by stripping good emoji.
            return ok, r, err
        flat_json = custom_emoji.flatten_body(json)
        flat_data = custom_emoji.flatten_body(data)
        if flat_json is None and flat_data is None:
            return ok, r, err
        logging.warning("Telegram refused a post with custom emoji (%s); retrying with plain emoji", err)
        ok2, r2, err2 = await self._post_once(
            url,
            data=flat_data if flat_data is not None else data,
            json=flat_json if flat_json is not None else json,
        )
        if ok2:
            custom_emoji.mark_refused(err)
        return ok2, r2, err2

    async def send_message(
        self,
        text: str,
        recorder: EventRecorder,
        reply_to_message_id: Optional[int] = None,
    ):
        target, dest_channel_id = recorder.get("dest_channel_name", "dest_channel_id")
        if not dest_channel_id:
            # Guard against an unresolved/blanked destination (e.g. a recorder
            # whose dest fields were never set). Raise a non-retryable ValueError
            # so run_with_retries surfaces it to the handler instead of POSTing
            # to an empty chat_id.
            raise ValueError(
                f"empty destination chat_id for send (dest_channel_name={target!r})"
            )

        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        chunks = self.split_message(text)
        sent_msg_id, posting_success = None, False

        for chunk in chunks:
            sanitized_chunk = sanitize_html(chunk)
            logging.info("Send message: Sending chunk to %s (chat_id %s)…", target, dest_channel_id)
            body = {
                "chat_id": dest_channel_id,
                "text": sanitized_chunk,
                "parse_mode": "HTML",
            }
            # Reply to the photo so a split long-caption post stays grouped. Only
            # the first chunk needs the linkage; keeping it on every chunk is
            # harmless (all point at the same photo) and simpler.
            # JSON body -> reply_parameters / link_preview_options nest directly.
            reply_parameters = build_reply_parameters(reply_to_message_id)
            if reply_parameters:
                body["reply_parameters"] = reply_parameters
            body["link_preview_options"] = build_link_preview_options()
            body.update(build_send_options())
            success, r, err = await self._post_telegram(url, json=body)
            exception_message = None
            if not success or r is None:
                # Relay send failures are pull-only: recorded on the event and
                # shown under /status, so don't DM them (extra={"no_forward": True}).
                logging.error(
                    "Send message: Failed to send to %s: %s",
                    dest_channel_id,
                    err,
                    extra={"no_forward": True},
                )
                if r is not None:
                    try:
                        exception_message = r.json().get("description", r.text)
                    except Exception:
                        exception_message = r.text
                else:
                    exception_message = str(err)
                recorder.set(
                    dest_message_id=sent_msg_id,
                    posting_success=posting_success,
                    api_error_code=err,
                    exception_message=exception_message,
                )
                logging.error(
                    "Send message: Error sending message to %s: %s",
                    dest_channel_id,
                    exception_message,
                    extra={"no_forward": True},
                )
                return False
            result = r.json().get("result", {})
            sent_msg_id = result.get("message_id")
            posting_success = True
            recorder.set(
                dest_message_id=sent_msg_id,
                posting_success=posting_success,
                api_error_code=None,
                exception_message=None,
            )
            record_sent(recorder, sent_msg_id)
        logging.info(
            "Send message: Successfully sent %d chunk(s) to %s", len(chunks), target
        )

        return True

    async def _send_media_message(
        self,
        endpoint: str,
        media_field: str,
        media_value: str,
        caption: str,
        recorder: EventRecorder,
        supports_caption: bool = True,
        reply_to_message_id: Optional[int] = None,
        extra: Optional[dict] = None,
    ):
        """Send a media message (photo/video/document/…) via the Bot API.

        The pyrogram listener runs as a *bot* session, so the source ``file_id``
        is valid for the Bot API and can be re-sent directly. Captions support
        HTML; link previews don't apply to media.

        ``supports_caption=False`` is for ``sendVideoNote``, the one media endpoint
        that accepts no ``caption`` at all — sending one is an API error, so the
        caller posts the translated text as a follow-up reply instead.

        ``extra`` carries endpoint-specific fields (``sendLivePhoto``'s static
        ``photo``); ``reply_to_message_id`` links the post as a reply.
        """
        target, dest_channel_id = recorder.get("dest_channel_name", "dest_channel_id")
        if not dest_channel_id:
            # See send_message: refuse to POST media to an empty destination.
            raise ValueError(
                f"empty destination chat_id for {media_field} send "
                f"(dest_channel_name={target!r})"
            )
        cfg, err = get_channel_config(target)
        if not cfg:
            return False
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/{endpoint}"
        sanitized_caption = sanitize_html(caption)

        sent_msg_id, posting_success = None, False

        logging.info("Sending %s to %s (chat_id %s)…", media_field, target, cfg.channel_id)
        data = {
            "chat_id": dest_channel_id,
            media_field: media_value,
            "parse_mode": "HTML",
        }
        has_caption = bool(sanitized_caption) and supports_caption
        if has_caption:
            data["caption"] = sanitized_caption
        if extra:
            data.update(extra)
        reply_parameters = build_reply_parameters(reply_to_message_id)
        if reply_parameters:
            data["reply_parameters"] = _as_form_value(reply_parameters)
        # Form-encoded body -> booleans/objects must be JSON-encoded (see
        # _as_form_value); the JSON sendMessage path nests them directly instead.
        for key, value in build_send_options(with_caption=has_caption).items():
            data[key] = _as_form_value(value)
        success, r, err = await self._post_telegram(url, data=data)
        if not success or r is None:
            logging.error(
                "Failed to send %s to %s: %s",
                media_field,
                dest_channel_id,
                err,
                extra={"no_forward": True},
            )
            recorder.set(
                dest_message_id=sent_msg_id,
                posting_success=posting_success,
                api_error_code=r.status_code if r else None,
                exception_message=err,
            )
            return False

        result = r.json().get("result", {})
        sent_msg_id = result.get("message_id")
        posting_success = True

        recorder.set(
            dest_message_id=sent_msg_id,
            posting_success=posting_success,
            api_error_code=None,
            exception_message=None,
        )
        record_sent(recorder, sent_msg_id)
        logging.info("Successfully sent %s to %s", media_field, target)
        return True

    async def send_photo_message(
        self, photo: str, caption: str, recorder: EventRecorder, reply_to_message_id=None
    ):
        return await self._send_media_message(
            "sendPhoto", "photo", photo, caption, recorder,
            reply_to_message_id=reply_to_message_id,
        )

    async def send_video_message(
        self, video: str, caption: str, recorder: EventRecorder, reply_to_message_id=None
    ):
        return await self._send_media_message(
            "sendVideo", "video", video, caption, recorder,
            reply_to_message_id=reply_to_message_id,
        )

    async def send_document_message(
        self, document: str, caption: str, recorder: EventRecorder, reply_to_message_id=None
    ):
        return await self._send_media_message(
            "sendDocument", "document", document, caption, recorder,
            reply_to_message_id=reply_to_message_id,
        )

    async def send_animation_message(
        self, animation: str, caption: str, recorder: EventRecorder, reply_to_message_id=None
    ):
        return await self._send_media_message(
            "sendAnimation", "animation", animation, caption, recorder,
            reply_to_message_id=reply_to_message_id,
        )

    async def send_audio_message(
        self, audio: str, caption: str, recorder: EventRecorder, reply_to_message_id=None
    ):
        return await self._send_media_message(
            "sendAudio", "audio", audio, caption, recorder,
            reply_to_message_id=reply_to_message_id,
        )

    async def send_voice_message(
        self, voice: str, caption: str, recorder: EventRecorder, reply_to_message_id=None
    ):
        return await self._send_media_message(
            "sendVoice", "voice", voice, caption, recorder,
            reply_to_message_id=reply_to_message_id,
        )

    async def send_video_note_message(
        self, video_note: str, caption: str, recorder: EventRecorder, reply_to_message_id=None
    ):
        """Send a round video note. ``sendVideoNote`` accepts no caption at all,
        so the caption is dropped here and the handler posts it as a reply."""
        return await self._send_media_message(
            "sendVideoNote", "video_note", video_note, caption, recorder,
            supports_caption=False,
            reply_to_message_id=reply_to_message_id,
        )

    async def send_live_photo_message(
        self,
        video: str,
        photo: str,
        caption: str,
        recorder: EventRecorder,
        reply_to_message_id=None,
    ):
        """Send a live photo (Bot API 10.0): its short video plus the static photo.

        Both go by file_id — ``sendLivePhoto`` accepts no URLs.
        """
        return await self._send_media_message(
            "sendLivePhoto", "live_photo", video, caption, recorder,
            reply_to_message_id=reply_to_message_id,
            extra={"photo": photo},
        )

    async def send_media_group(
        self,
        items: List[Tuple[str, ...]],
        caption: str,
        recorder: EventRecorder,
        reply_to_message_id: Optional[int] = None,
    ):
        """Relay an album in one ``sendMediaGroup`` call.

        ``items`` is ``[(input_media_type, file_id), …]`` already validated by
        ``media_group_buffer.can_send_as_album``. Telegram shows the album's
        caption from the **first** item only, so the translated caption goes
        there; a caption over the 1024-char media limit is the caller's problem
        (it splits and posts the remainder as a reply to the group).

        ``sendMediaGroup`` returns an *array* of messages. The first one's id is
        recorded as ``dest_message_id`` so the source→destination edit mapping in
        ``CONFIG.get_destination_msg_id`` keeps working unchanged; all of them go
        to ``dest_message_ids`` for delete sync.

        A live-photo item is ``("live_photo", video_file_id, photo_file_id)``.
        """
        target, dest_channel_id = recorder.get("dest_channel_name", "dest_channel_id")
        if not dest_channel_id:
            # Same guard as send_message / _send_media_message.
            raise ValueError(
                f"empty destination chat_id for media group send "
                f"(dest_channel_name={target!r})"
            )

        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMediaGroup"
        sanitized_caption = sanitize_html(caption)
        show_above = _env_flag("SHOW_CAPTION_ABOVE_MEDIA", False)

        media = []
        for index, item in enumerate(items):
            input_type, file_id = item[0], item[1]
            entry = {"type": input_type, "media": file_id}
            if input_type == "live_photo" and len(item) > 2:
                entry["photo"] = item[2]
            if index == 0 and sanitized_caption:
                entry["caption"] = sanitized_caption
                entry["parse_mode"] = "HTML"
                if show_above:
                    entry["show_caption_above_media"] = True
            media.append(entry)

        logging.info(
            "Sending media group of %d item(s) to %s (chat_id %s)…",
            len(media),
            target,
            dest_channel_id,
        )
        data = {"chat_id": dest_channel_id, "media": json.dumps(media)}
        for key, value in build_send_options().items():
            data[key] = _as_form_value(value)
        reply_parameters = build_reply_parameters(reply_to_message_id)
        if reply_parameters:
            data["reply_parameters"] = _as_form_value(reply_parameters)

        success, r, err = await self._post_telegram(url, data=data)
        if not success or r is None:
            exception_message = err
            if r is not None:
                try:
                    exception_message = r.json().get("description", r.text)
                except Exception:
                    exception_message = r.text
            logging.error(
                "Failed to send media group to %s: %s",
                dest_channel_id,
                exception_message,
                extra={"no_forward": True},
            )
            recorder.set(
                dest_message_id=None,
                posting_success=False,
                api_error_code=r.status_code if r else None,
                exception_message=exception_message,
            )
            return False

        # result is an array of Messages; the first carries the album caption.
        results = r.json().get("result") or []
        sent_msg_id = results[0].get("message_id") if results else None
        recorder.set(
            dest_message_id=sent_msg_id,
            posting_success=True,
            api_error_code=None,
            exception_message=None,
        )
        record_sent(recorder, *(m.get("message_id") for m in results))
        logging.info(
            "Successfully sent media group (%d item(s)) to %s", len(media), target
        )
        return True

    async def send_poll(
        self,
        poll: dict,
        recorder: EventRecorder,
        reply_to_message_id: Optional[int] = None,
    ):
        """Send a poll (``sendPoll`` fields already built by the caller).

        ``poll`` holds ``question``, ``options`` and whichever optional fields
        apply (``type``, ``correct_option_ids``, ``explanation`` …). JSON body,
        so nested objects go in as-is.
        """
        target, dest_channel_id = recorder.get("dest_channel_name", "dest_channel_id")
        if not dest_channel_id:
            raise ValueError(
                f"empty destination chat_id for poll send (dest_channel_name={target!r})"
            )
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPoll"
        body = {"chat_id": dest_channel_id, **poll}
        reply_parameters = build_reply_parameters(reply_to_message_id)
        if reply_parameters:
            body["reply_parameters"] = reply_parameters
        body.update(build_send_options())
        success, r, err = await self._post_telegram(url, json=body)
        if not success or r is None:
            logging.error(
                "Failed to send poll to %s: %s", dest_channel_id, err,
                extra={"no_forward": True},
            )
            recorder.set(
                posting_success=False,
                api_error_code=r.status_code if r is not None else None,
                exception_message=err,
            )
            return False
        sent_msg_id = (r.json().get("result") or {}).get("message_id")
        recorder.set(
            dest_message_id=sent_msg_id,
            posting_success=True,
            api_error_code=None,
            exception_message=None,
        )
        record_sent(recorder, sent_msg_id)
        return True

    async def stop_poll(self, chat_id, message_id) -> bool:
        """Close a relayed poll (``stopPoll``); True on success."""
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/stopPoll"
        ok, _r, err = await self._post_telegram(
            url, json={"chat_id": chat_id, "message_id": int(message_id)}
        )
        if not ok:
            logging.warning("stopPoll failed for %s/%s: %s", chat_id, message_id, err)
        return ok

    async def delete_messages(self, chat_id, message_ids: List[int]) -> Tuple[bool, Optional[str]]:
        """Delete destination messages (``deleteMessages``, up to 100 per call).

        Returns ``(ok, error)``. Telegram skips ids it can't find, so deleting a
        post that is already gone is not an error.
        """
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/deleteMessages"
        ids = [int(i) for i in message_ids]
        for start in range(0, len(ids), 100):
            ok, _r, err = await self._post_telegram(
                url, json={"chat_id": chat_id, "message_ids": ids[start : start + 100]}
            )
            if not ok:
                return False, err
        return True, None

    async def edit_message(self, channel_id, message_id, text, recorder: EventRecorder, original_text: Optional[str] = None):
        """
        Edit a message in a Telegram channel by channel_id and message_id.
        Returns (posting_success, api_error_code, exception_message).
        
        Args:
            channel_id: The chat ID of the channel
            message_id: The message ID to edit
            text: The new text content
            recorder: Event recorder for logging
            original_text: Optional original message text for comparison
        """
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
        sanitized_text = sanitize_html(text)
        
        # Pre-check: Compare content if original_text is provided
        if original_text is not None:
            sanitized_original = sanitize_html(original_text)
            
            # Enhanced debugging for content comparison
            logging.debug(
                "Edit message: Content comparison debug for message %s in %s",
                message_id,
                channel_id,
            )
            logging.debug("Original text length: %d", len(original_text))
            logging.debug("New text length: %d", len(text))
            logging.debug("Sanitized original length: %d", len(sanitized_original))
            logging.debug("Sanitized new length: %d", len(sanitized_text))
            
            # Try multiple normalization approaches for better comparison
            normalized_original = normalize_for_comparison(sanitized_original)
            normalized_new = normalize_for_comparison(sanitized_text)
            
            # Also try the more comprehensive normalization
            telegram_normalized_original = telegram_normalize_text(original_text)
            telegram_normalized_new = telegram_normalize_text(text)
            
            logging.info("Normalized original: %s", normalized_original[:200] + "..." if len(normalized_original) > 200 else normalized_original)
            logging.info("Normalized new: %s", normalized_new[:200] + "..." if len(normalized_new) > 200 else normalized_new)
            logging.debug("Telegram normalized original: %s", telegram_normalized_original[:200] + "..." if len(telegram_normalized_original) > 200 else telegram_normalized_original)
            logging.debug("Telegram normalized new: %s", telegram_normalized_new[:200] + "..." if len(telegram_normalized_new) > 200 else telegram_normalized_new)
            
            # Check if content is the same using advanced comparison
            if advanced_content_comparison(original_text, text):
                logging.info(
                    "Edit message: Content unchanged for message %s in %s - skipping edit",
                    message_id,
                    channel_id,
                )
                recorder.set(
                    dest_message_id=message_id,
                    posting_success=True,
                    api_error_code=None,
                    exception_message="Content unchanged - edit skipped",
                )
                return True
        
        # Log the content being sent for debugging
        logging.info(
            "Edit message: Attempting to edit message %s in channel %s",
            message_id,
            channel_id,
        )
        logging.info(
            "Edit message: New content (length: %d): %s",
            len(sanitized_text),
            sanitized_text[:200] + "..." if len(sanitized_text) > 200 else sanitized_text,
        )
        
        payload = {
            "chat_id": channel_id,
            "message_id": message_id,
            "text": sanitized_text,
            "parse_mode": "HTML",
        }
        # Form-encoded body -> link_preview_options must be a JSON-encoded string.
        payload["link_preview_options"] = json.dumps(build_link_preview_options())
        posting_success = False
        api_error_code = None
        exception_message = None
        sent_msg_id = None

        success, resp, err = await self._post_telegram(url, data=payload)
        
        if not success or resp is None:
            # Handle specific "message is not modified" error
            if err and "message is not modified" in str(err).lower():
                logging.warning(
                    "Edit message: Message %s in %s is unchanged - treating as successful",
                    message_id,
                    channel_id,
                )
                logging.debug(
                    "Edit message: Content that was considered unchanged: %s",
                    sanitized_text[:200] + "..." if len(sanitized_text) > 200 else sanitized_text,
                )
                # Treat as successful since the message already has the correct content
                posting_success = True
                sent_msg_id = message_id
                api_error_code = None
                exception_message = "Message content unchanged"
            else:
                logging.error(
                    "Edit message: Failed to edit message %s in %s: %s",
                    message_id,
                    channel_id,
                    err,
                    extra={"no_forward": True},
                )
                api_error_code = resp.status_code if resp else None
                exception_message = err
        else:
            result = resp.json().get("result", {})
            sent_msg_id = result.get("message_id")
            posting_success = True
            logging.info(
                "Edit message: Successfully edited message %s in %s",
                message_id,
                channel_id,
            )

        recorder.set(
            dest_message_id=sent_msg_id,
            posting_success=posting_success,
            api_error_code=api_error_code,
            exception_message=exception_message,
        )
        return posting_success

    async def edit_caption(
        self,
        channel_id,
        message_id,
        caption,
        recorder: EventRecorder,
        original_text: Optional[str] = None,
    ):
        """Edit the caption of a relayed media message via editMessageCaption.

        Mirrors ``edit_message`` (unchanged-content skip + "not modified"
        tolerance) but targets media posts, where ``editMessageText`` is invalid.
        Link previews don't apply to captions.
        """
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageCaption"
        sanitized_caption = sanitize_html(caption)

        if original_text is not None and advanced_content_comparison(original_text, caption):
            logging.info(
                "Edit caption: Content unchanged for message %s in %s - skipping edit",
                message_id,
                channel_id,
            )
            recorder.set(
                dest_message_id=message_id,
                posting_success=True,
                api_error_code=None,
                exception_message="Content unchanged - edit skipped",
            )
            return True

        payload = {
            "chat_id": channel_id,
            "message_id": message_id,
            "caption": sanitized_caption,
            "parse_mode": "HTML",
        }
        # editMessageCaption accepts show_caption_above_media, so an edited post
        # keeps the same layout as the original send. protect_content and
        # disable_notification are send-only and must not be sent here.
        if _env_flag("SHOW_CAPTION_ABOVE_MEDIA", False):
            payload["show_caption_above_media"] = _as_form_value(True)
        posting_success = False
        api_error_code = None
        exception_message = None
        sent_msg_id = None

        success, resp, err = await self._post_telegram(url, data=payload)

        if not success or resp is None:
            if err and "message is not modified" in str(err).lower():
                logging.warning(
                    "Edit caption: Message %s in %s is unchanged - treating as successful",
                    message_id,
                    channel_id,
                )
                posting_success = True
                sent_msg_id = message_id
                exception_message = "Message content unchanged"
            else:
                logging.error(
                    "Edit caption: Failed to edit message %s in %s: %s",
                    message_id,
                    channel_id,
                    err,
                    extra={"no_forward": True},
                )
                api_error_code = resp.status_code if resp else None
                exception_message = err
        else:
            result = resp.json().get("result", {})
            sent_msg_id = result.get("message_id")
            posting_success = True
            logging.info(
                "Edit caption: Successfully edited message %s in %s",
                message_id,
                channel_id,
            )

        recorder.set(
            dest_message_id=sent_msg_id,
            posting_success=posting_success,
            api_error_code=api_error_code,
            exception_message=exception_message,
        )
        return posting_success
