"""Turn an exception (or a stored exception string) into one readable line.

Relay failures used to surface the raw Anthropic SDK string
(``Error code: 400 - {'type': 'error', 'error': {'message': ...}}``) straight to
the admin. This module distils it down to a single sentence that says what
happened and what to do, for the ``/status`` failures view and the event store.
The full raw exception still goes to ``bot.log``.

Two entry points share one classifier:

* :func:`humanize_error` — for a live exception (the bot's failure branches).
* :func:`humanize_text` — for an already-stored ``exception_message`` string,
  which may be a raw SDK dump from before humanization existed. This lets
  ``/status`` clean up *historical* events at display time, non-destructively.

No imports from the rest of the package, so it is trivially unit-testable.
"""

from __future__ import annotations

import ast
import re
from typing import Any, Optional

# Cap for the generic fallback line so a stray multi-KB error can't blow up the
# reply or the stored event.
_MAX_LEN = 160

# Matches the SDK's "Error code: NNN - {...}" prefix to recover the status code.
_STATUS_RE = re.compile(r"\s*Error code:\s*(\d+)")
# Fallback extractor for the inner error message when the dict won't parse.
_MESSAGE_RE = re.compile(r"'message':\s*'(.*?)'(?:\s*[,}])", re.DOTALL)


def _inner_message(exc: Any) -> str:
    """Best clean message for an exception.

    Anthropic SDK errors carry the parsed JSON body, whose
    ``error.message`` is the human-written reason — far cleaner than ``str(exc)``
    (which is prefixed with ``Error code: NNN - {...}``). Fall back to the SDK's
    ``.message`` attribute, then to ``str(exc)``.
    """
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            msg = err.get("message")
            if isinstance(msg, str) and msg.strip():
                return msg.strip()
    msg = getattr(exc, "message", None)
    if isinstance(msg, str) and msg.strip():
        return msg.strip()
    return str(exc).strip()


def _extract_sdk_message(text: str) -> Optional[str]:
    """Pull ``error.message`` out of a raw ``Error code: NNN - {..dict..}`` string.

    The dict is a Python repr (single quotes), not JSON, so parse it with
    ``ast.literal_eval``; fall back to a regex when that fails.
    """
    idx = text.find("- {")
    if idx != -1:
        blob = text[idx + 2 :]
        try:
            data = ast.literal_eval(blob)
        except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
            data = None
        if isinstance(data, dict):
            err = data.get("error")
            if isinstance(err, dict) and isinstance(err.get("message"), str):
                return err["message"]
    m = _MESSAGE_RE.search(text)
    return m.group(1) if m else None


def _first_line(text: str, limit: int = _MAX_LEN) -> str:
    """First line of ``text``, collapsed and capped at ``limit`` chars."""
    line = text.strip().splitlines()[0].strip() if text.strip() else ""
    return line if len(line) <= limit else line[: limit - 1].rstrip() + "…"


def _classify(status: Optional[int], hay: str) -> Optional[str]:
    """Map a status code + lowercased haystack to a known reason, else None.

    The haystack is the message plus any surrounding SDK text, so error *types*
    like ``not_found_error`` / ``rate_limit_error`` classify correctly even when
    the status code isn't available (the stored-string path).
    """
    if "credit balance" in hay:
        return "Anthropic credits exhausted. Top up under Plans & Billing."
    if status == 429 or "rate limit" in hay or "rate_limit" in hay:
        return "Rate limited by Anthropic; it will retry."
    if status == 529 or "overloaded" in hay:
        return "Anthropic is temporarily overloaded; it will retry."
    if status == 401 or "authentication" in hay or "invalid x-api-key" in hay:
        return "Anthropic API key rejected. Check ANTHROPIC_API_KEY."
    if status == 404 or "not_found" in hay:
        return "Anthropic model not found. Check ANTHROPIC_MODEL."
    return None


def humanize_error(exc: Any) -> str:
    """Return a single, plain-language line describing a live exception ``exc``."""
    inner = _inner_message(exc)
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    hay = (inner + " " + str(exc)).lower()
    return _classify(status, hay) or _first_line(inner) or "Unknown error."


def humanize_text(text: str) -> str:
    """Distil a stored ``exception_message`` (possibly a raw SDK dump) to one line.

    Idempotent on already-humanized text, so it is safe to apply at display time
    to a mix of old (raw) and new (clean) events.
    """
    text = (text or "").strip()
    if not text:
        return "Unknown error."
    inner = _extract_sdk_message(text) or text
    m = _STATUS_RE.match(text)
    status = int(m.group(1)) if m else None
    hay = (text + " " + inner).lower()
    return _classify(status, hay) or _first_line(inner)
