"""Per-model Anthropic pricing and a local cost estimator.

Prices are USD per 1,000,000 tokens and are **maintained manually** — Anthropic
can change them, so treat the local estimate as an approximation and prefer the
Admin Cost API (see :mod:`translator.services.cost_report`) when an admin key is
configured. Figures below are current as of 2026-06 (from the Claude API skill).

Cache pricing follows Anthropic's published multipliers relative to the model's
*input* rate: a cache read costs ~0.1x input, and a 5-minute cache write ~1.25x.
"""

from __future__ import annotations

import re
from typing import Dict

# USD per 1,000,000 tokens, keyed by model alias.
PRICING: Dict[str, Dict[str, float]] = {
    "claude-haiku-4-5": {"input": 1.0, "output": 5.0},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
    "claude-opus-4-8": {"input": 5.0, "output": 25.0},
    "claude-opus-4-7": {"input": 5.0, "output": 25.0},
    "claude-opus-4-6": {"input": 5.0, "output": 25.0},
    "claude-fable-5": {"input": 10.0, "output": 50.0},
}

# Fallback when the model is unknown: assume the cheap/fast tier (the bot's
# default model), so an unrecognised id under-states rather than over-states.
DEFAULT = {"input": 1.0, "output": 5.0}

CACHE_READ_MULTIPLIER = 0.1
CACHE_WRITE_MULTIPLIER = 1.25

# Strips a trailing dated snapshot suffix, e.g. "claude-haiku-4-5-20251022".
_SNAPSHOT_RE = re.compile(r"-\d{8}$")


def rates_for(model: str) -> Dict[str, float]:
    """Return the {input, output} per-1M rates for a model id.

    Matches an exact alias first, then the alias with any ``-YYYYMMDD`` snapshot
    suffix stripped, then falls back to :data:`DEFAULT`.
    """
    if not model:
        return DEFAULT
    if model in PRICING:
        return PRICING[model]
    base = _SNAPSHOT_RE.sub("", model)
    return PRICING.get(base, DEFAULT)


def estimate_cost_usd(
    model: str,
    in_tok: int,
    out_tok: int,
    cache_read: int = 0,
    cache_create: int = 0,
) -> float:
    """Estimate the USD cost of one (or aggregated) Anthropic call.

    ``in_tok`` is uncached input; cache reads/writes are priced separately at the
    standard multipliers of the input rate. All token counts are absolute (not
    per-million); the division by 1e6 happens here.
    """
    r = rates_for(model)
    per_in = r["input"] / 1_000_000
    per_out = r["output"] / 1_000_000
    return (
        in_tok * per_in
        + out_tok * per_out
        + cache_read * per_in * CACHE_READ_MULTIPLIER
        + cache_create * per_in * CACHE_WRITE_MULTIPLIER
    )
