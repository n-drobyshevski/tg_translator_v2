"""Turn an exception into one short, operator-readable line.

Relay failures used to surface the raw Anthropic SDK string
(``Error code: 400 - {'type': 'error', 'error': {'message': ...}}``) straight to
the admin. This module distils such an exception down to a single sentence that
says what happened and what to do, for the ``/status`` failures view and the
event store. The full raw exception still goes to ``bot.log``.

No imports from the rest of the package, so it is trivially unit-testable.
"""

from __future__ import annotations

from typing import Any

# Cap for the generic fallback line so a stray multi-KB error can't blow up the
# reply or the stored event.
_MAX_LEN = 160


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


def _first_line(text: str, limit: int = _MAX_LEN) -> str:
    """First line of ``text``, collapsed and capped at ``limit`` chars."""
    line = text.strip().splitlines()[0].strip() if text.strip() else ""
    return line if len(line) <= limit else line[: limit - 1].rstrip() + "…"


def humanize_error(exc: Any) -> str:
    """Return a single, plain-language line describing ``exc``.

    Maps the failures an operator actually hits (exhausted credits, rate limits,
    overload, a rejected key) to a reason plus the action that fixes it; anything
    else degrades to the exception's own first line.
    """
    inner = _inner_message(exc)
    low = inner.lower()
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)

    if "credit balance" in low:
        return "Anthropic credits exhausted. Top up under Plans & Billing."
    if status == 429 or "rate limit" in low:
        return "Rate limited by Anthropic; it will retry."
    if status == 529 or "overloaded" in low:
        return "Anthropic is temporarily overloaded; it will retry."
    if status == 401 or "authentication" in low or "invalid x-api-key" in low:
        return "Anthropic API key rejected. Check ANTHROPIC_API_KEY."

    return _first_line(inner) or "Unknown error."
