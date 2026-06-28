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

from anthropic import Anthropic, AsyncAnthropic

from translator.config import CONFIG

# Hard ceiling for a single translation request so a hung API call can't pin a
# worker thread forever (env-overridable).
ANTHROPIC_TIMEOUT = float(os.getenv("ANTHROPIC_TIMEOUT", "60"))


@lru_cache(maxsize=1)
def get_anthropic_client() -> Anthropic:
    """Return the shared, lazily-created **synchronous** Anthropic client.

    Loop-agnostic, so it is the client used by the Flask admin app's per-request
    ``asyncio.run()`` loops (and by any caller that can't guarantee a single
    long-lived loop). ``translate_html`` runs its ``messages.create`` off the
    event loop via ``asyncio.to_thread``.
    """
    return Anthropic(api_key=CONFIG.ANTHROPIC_API_KEY, timeout=ANTHROPIC_TIMEOUT)


@lru_cache(maxsize=1)
def get_async_anthropic_client() -> AsyncAnthropic:
    """Return the lazily-created **async** Anthropic client — bot use only.

    ``AsyncAnthropic`` binds its underlying httpx pool to the loop it first runs
    on, so it is safe **only** for the bot's single, long-lived event loop. The
    Flask app must keep using ``get_anthropic_client()`` (see its docstring);
    sharing this instance across the app's per-request loops would break on the
    second request. ``translate_html`` awaits this client's ``messages.create``
    directly, with no thread offload.
    """
    return AsyncAnthropic(api_key=CONFIG.ANTHROPIC_API_KEY, timeout=ANTHROPIC_TIMEOUT)
