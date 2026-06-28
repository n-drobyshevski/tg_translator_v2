"""Single source of truth for the Anthropic API client.

A **synchronous** client is used deliberately. It is loop-agnostic, so one cached
singleton instance is safe to share between the bot's long-lived event loop and
the Flask admin app's per-request ``asyncio.run()`` loops. (An ``AsyncAnthropic``
client binds its underlying httpx pool to the loop it first runs on and would
break on the second Flask request — the same loop-binding hazard documented for
``TelegramSender``'s per-call httpx client.) Translation calls stay off the event
loop via ``asyncio.to_thread`` in ``translation_utils.translate_html``.
"""

import os
from functools import lru_cache

from anthropic import Anthropic

from translator.config import CONFIG

# Hard ceiling for a single translation request so a hung API call can't pin a
# worker thread forever (env-overridable).
ANTHROPIC_TIMEOUT = float(os.getenv("ANTHROPIC_TIMEOUT", "60"))


@lru_cache(maxsize=1)
def get_anthropic_client() -> Anthropic:
    """Return the shared, lazily-created Anthropic client."""
    return Anthropic(api_key=CONFIG.ANTHROPIC_API_KEY, timeout=ANTHROPIC_TIMEOUT)
