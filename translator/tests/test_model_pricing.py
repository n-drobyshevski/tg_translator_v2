"""Tests for the per-model list prices behind the /cost report."""

import pytest

from translator.utils import model_pricing
from translator.utils.model_pricing import PRICES, estimate_cost, price_for


def test_exact_ids_resolve():
    assert price_for("claude-sonnet-5") == PRICES["claude-sonnet-5"]
    assert price_for("CLAUDE-SONNET-5 ") == PRICES["claude-sonnet-5"]


def test_dated_snapshots_resolve_to_their_base_id():
    # resp.model can come back as a dated snapshot.
    assert price_for("claude-haiku-4-5-20251001") == PRICES["claude-haiku-4-5"]
    assert price_for("claude-opus-5-20260401") == PRICES["claude-opus-5"]


def test_opus_5_5_is_not_priced_as_opus_5():
    # "claude-opus-5" is a string prefix of "claude-opus-5-5"; 5.5 is cheaper.
    assert price_for("claude-opus-5-5") == PRICES["claude-opus-5-5"]
    assert price_for("claude-opus-5-5-20260901") == PRICES["claude-opus-5-5"]
    assert price_for("claude-opus-5-5").input < price_for("claude-opus-5").input


@pytest.mark.parametrize(
    "model", ["claude-sonnet-5-1", "claude-sonnet-5-2026", "gpt-x", "", None, "?"]
)
def test_unknown_ids_are_never_guessed(model):
    # A future point release must not silently bill at its predecessor's rate.
    assert price_for(model) is None
    assert estimate_cost(model, input_tokens=1000) is None


def test_cost_math_with_cache_reads_and_writes():
    # Sonnet 5: $2 in, $10 out, $0.20 cache read; writes at 1.25 × input.
    cost = estimate_cost(
        "claude-sonnet-5",
        input_tokens=1_000_000,
        output_tokens=100_000,
        cache_read_tokens=2_000_000,
        cache_write_tokens=400_000,
    )
    assert cost == pytest.approx(2.0 + 1.0 + 0.4 + 400_000 * 2.0 * 1.25 / 1e6)


def test_cache_reads_are_priced_per_model_not_as_a_flat_tenth():
    # Fable 5.1 reads at 0.025× input, Opus 5.5 at 0.05×, most others at 0.1×.
    assert estimate_cost("claude-fable-5-1", cache_read_tokens=1_000_000) == pytest.approx(0.25)
    assert estimate_cost("claude-opus-5-5", cache_read_tokens=1_000_000) == pytest.approx(0.20)
    assert estimate_cost("claude-fable-5", cache_read_tokens=1_000_000) == pytest.approx(1.00)


def test_zero_usage_costs_nothing():
    assert estimate_cost("claude-haiku-4-5") == 0


def test_write_multiplier_matches_the_5_minute_ttl():
    assert model_pricing.CACHE_WRITE_MULTIPLIER == 1.25


def test_canonical_id_folds_snapshots_but_leaves_unknowns_alone():
    assert model_pricing.canonical_id("claude-sonnet-5-20260101") == "claude-sonnet-5"
    assert model_pricing.canonical_id("claude-opus-5-5") == "claude-opus-5-5"
    assert model_pricing.canonical_id("claude-future-9-20260101") == "claude-future-9-20260101"
    assert model_pricing.canonical_id(None) == ""
