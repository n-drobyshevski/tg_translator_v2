"""Tests for the local Anthropic cost estimator (translator/pricing.py)."""

from translator import pricing


def test_rates_exact_alias():
    assert pricing.rates_for("claude-haiku-4-5") == {"input": 1.0, "output": 5.0}
    assert pricing.rates_for("claude-opus-4-8") == {"input": 5.0, "output": 25.0}


def test_rates_strip_snapshot_suffix():
    # A dated snapshot resolves to its base alias's rates.
    assert pricing.rates_for("claude-haiku-4-5-20251022") == pricing.PRICING[
        "claude-haiku-4-5"
    ]


def test_rates_unknown_falls_back_to_default():
    assert pricing.rates_for("some-future-model") == pricing.DEFAULT
    assert pricing.rates_for("") == pricing.DEFAULT


def test_estimate_cost_basic():
    # 1M input + 1M output on Haiku = $1 + $5 = $6.
    cost = pricing.estimate_cost_usd("claude-haiku-4-5", 1_000_000, 1_000_000)
    assert cost == 6.0


def test_estimate_cost_includes_cache_multipliers():
    # 1M cache-read @ 0.1x input ($0.10) + 1M cache-write @ 1.25x input ($1.25).
    cost = pricing.estimate_cost_usd(
        "claude-haiku-4-5", 0, 0, cache_read=1_000_000, cache_create=1_000_000
    )
    assert round(cost, 6) == round(0.10 + 1.25, 6)


def test_estimate_cost_zero_tokens():
    assert pricing.estimate_cost_usd("claude-opus-4-8", 0, 0) == 0.0
