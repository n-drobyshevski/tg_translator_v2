"""Tests for the per-model request-shape rules.

Getting these wrong means a 400 on every translation, and the model is
switchable at runtime (env / admin DM `/setmodel`), so the rules have to hold for
models nobody tested against by hand.
"""

import pytest

from translator.utils.model_capabilities import (
    build_model_params,
    is_modern_surface,
    supports_effort,
    supports_sampling_params,
)


@pytest.mark.parametrize(
    "model",
    [
        "claude-sonnet-5",
        "claude-opus-5",
        "claude-opus-4-7",
        "claude-opus-4-8",
        "claude-fable-5-1",
        "claude-mythos-5-1",
        "claude-sonnet-5-20260401",  # dated snapshot
    ],
)
def test_modern_surface_models(model):
    assert is_modern_surface(model) is True
    assert supports_sampling_params(model) is False
    assert supports_effort(model) is True


@pytest.mark.parametrize(
    "model",
    [
        "claude-haiku-4-5",
        "claude-haiku-4-5-20251001",  # dated snapshot
        "claude-sonnet-4-6",
        "claude-opus-4-6",
        "claude-sonnet-4-5",
    ],
)
def test_legacy_surface_models(model):
    # Sampling params are still accepted below the Opus 4.7 cutover.
    assert is_modern_surface(model) is False
    assert supports_sampling_params(model) is True
    assert supports_effort(model) is False


def test_opus_cutover_is_at_4_7():
    assert is_modern_surface("claude-opus-4-6") is False
    assert is_modern_surface("claude-opus-4-7") is True


@pytest.mark.parametrize("model", ["", "   ", "something-else", "gpt-4", None])
def test_unknown_models_assume_modern_surface(model):
    # Deliberate: omitting temperature is accepted by every model, while sending
    # one 400s on the new ones. Guess the way that cannot take the relay down.
    assert is_modern_surface(model) is True
    assert supports_sampling_params(model) is False


# --- build_model_params ------------------------------------------------------


def test_params_for_legacy_model():
    params = build_model_params(
        "claude-haiku-4-5", temperature=0.0, effort="low"
    )
    # 1.x dropped the named kwarg, so temperature travels in extra_body...
    assert params == {"extra_body": {"temperature": 0.0}}
    # ...and effort/thinking are NOT sent (effort errors on Haiku 4.5).
    assert "output_config" not in params
    assert "thinking" not in params


def test_params_for_legacy_model_without_temperature():
    assert build_model_params("claude-haiku-4-5", temperature=None) == {}


def test_params_for_modern_model():
    params = build_model_params(
        "claude-sonnet-5", temperature=0.0, effort="low"
    )
    # temperature must be dropped entirely — Sonnet 5 400s on a non-default value.
    assert "extra_body" not in params
    assert params["thinking"] == {"type": "adaptive"}
    assert params["output_config"] == {"effort": "low"}


def test_modern_model_without_effort_still_sets_thinking():
    params = build_model_params("claude-sonnet-5", temperature=0.0, effort=None)
    assert params == {"thinking": {"type": "adaptive"}}


def test_temperature_never_becomes_a_top_level_kwarg():
    # Whatever the model, `temperature=` as a named argument is a TypeError
    # against anthropic 1.x.
    for model in ("claude-haiku-4-5", "claude-sonnet-5", "claude-opus-5"):
        assert "temperature" not in build_model_params(model, temperature=0.0)
