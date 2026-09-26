"""List prices per Claude model, for the admin DM's cost report.

Like :mod:`translator.utils.model_capabilities`, this is the single place for a
model-dependent fact: the ``/cost`` report, the ``/stats`` estimate and the
Model menu's price table all read it, so a price change is one edit here.

Every relayed translation records its Anthropic usage in the event store
(``input_tokens`` / ``output_tokens`` / ``cache_read_tokens`` /
``cache_creation_tokens`` / ``model_used``). ``usage.input_tokens`` is the
*uncached* input only, so a request costs::

    input·p_in + cache_write·1.25·p_in + cache_read·p_cache_read + output·p_out

Cache reads are **not** a uniform 0.1× of input on every model (Opus 5.5 is
0.05×, Fable 5.1 is 0.025×), so each row carries its own cache-read price.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Optional

# When the table below was last checked against the published list prices.
PRICES_AS_OF = "2026-06"

# translate_html marks the system prompt with the default 5-minute ephemeral
# cache, whose writes bill at 1.25× input (a 1-hour TTL would be 2×).
CACHE_WRITE_MULTIPLIER = 1.25


@dataclass(frozen=True)
class Price:
    """USD per 1M tokens."""

    input: float
    output: float
    cache_read: float


PRICES: Dict[str, Price] = {
    "claude-haiku-4-5": Price(1.0, 5.0, 0.10),
    "claude-sonnet-5": Price(2.0, 10.0, 0.20),
    "claude-sonnet-4-6": Price(3.0, 15.0, 0.30),
    "claude-opus-5": Price(5.0, 25.0, 0.50),
    "claude-opus-5-5": Price(4.0, 20.0, 0.20),
    "claude-opus-4-8": Price(5.0, 25.0, 0.50),
    "claude-opus-4-7": Price(5.0, 25.0, 0.50),
    "claude-opus-4-6": Price(5.0, 25.0, 0.50),
    "claude-fable-5": Price(10.0, 50.0, 1.00),
    "claude-fable-5-1": Price(10.0, 50.0, 0.25),
}


# "<id>" or "<id>-YYYYMMDD". The id part is non-greedy so the date suffix is
# never swallowed into it.
_SNAPSHOT = re.compile(r"(.+?)(?:-\d{8})?")


def canonical_id(model_id: Optional[str]) -> str:
    """``model_id`` without a dated-snapshot suffix, when it is a known model.

    Lets a report group ``claude-sonnet-5`` and ``claude-sonnet-5-20260101`` as
    the one model they are. Unknown ids come back unchanged (stripped).
    """
    raw = (model_id or "").strip()
    match = _SNAPSHOT.fullmatch(raw.lower())
    return match.group(1) if match and match.group(1) in PRICES else raw


def price_for(model_id: Optional[str]) -> Optional[Price]:
    """Price for ``model_id``, or None if it isn't in the table.

    Matches the id exactly, or as a dated snapshot of it (``resp.model`` can come
    back as ``claude-haiku-4-5-20251001``). Anything else is unknown — including
    a newer point release such as a future ``claude-sonnet-5-1``, which a plain
    prefix match would silently bill at Sonnet 5's rate. A wrong price is worse
    than a report that says it doesn't know.
    """
    match = _SNAPSHOT.fullmatch((model_id or "").strip().lower())
    return PRICES.get(match.group(1)) if match else None


def estimate_cost(
    model_id: Optional[str],
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> Optional[float]:
    """Estimated USD for one request's usage, or None when the model is unpriced."""
    price = price_for(model_id)
    if price is None:
        return None
    return (
        input_tokens * price.input
        + cache_write_tokens * price.input * CACHE_WRITE_MULTIPLIER
        + cache_read_tokens * price.cache_read
        + output_tokens * price.output
    ) / 1_000_000
