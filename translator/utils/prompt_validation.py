"""Shared validation for the operator-editable prompt template.

The long-message translation path does ``PROMPT_TEMPLATE.format(message_text=...)``
(see ``translation_utils.build_messages``), so a saved template MUST contain the
``{message_text}`` placeholder and must not contain stray braces that break
``str.format``. Both the Flask admin app and the bot's ``/setprompt`` DM command
validate with this single function before overwriting the live template.
"""

from __future__ import annotations

from typing import Optional


def validate_prompt(text: str) -> Optional[str]:
    """Return an error string if ``text`` is an invalid template, else None."""
    if not text or not text.strip():
        return "No prompt provided."
    if "{message_text}" not in text:
        return "Template must contain the {message_text} placeholder."
    try:
        text.format(message_text="sample")
    except (KeyError, IndexError, ValueError) as e:
        return (
            f"Template has invalid placeholders ({e}). "
            "Escape literal braces as {{ and }}."
        )
    return None
