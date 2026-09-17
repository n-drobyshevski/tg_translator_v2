"""Per-model request-shape rules for the Anthropic Messages API.

The translation model is env-switchable (``ANTHROPIC_MODEL``, also settable live
from the admin DM ``/setmodel``), and the model decides which request parameters
are *legal*. Send the wrong ones and the API returns 400 for every translation,
so the shape has to follow the model rather than be hard-coded.

Two request surfaces are in play:

* the **Opus 4.7+ surface** — Opus 4.7/4.8/5, Sonnet 5, Fable/Mythos 5.x.
  ``temperature``/``top_p``/``top_k`` are rejected (Sonnet 5 rejects non-default
  values; Opus 4.7+ rejects the parameter outright), manual
  ``thinking.budget_tokens`` is gone in favour of adaptive thinking, and
  ``output_config.effort`` is how you tune thinking depth.
* the **older line** — Haiku 4.5 and the 4.6/4.5 families. These accept sampling
  parameters, and ``effort`` errors on the Sonnet/Haiku members.

Unknown model ids are treated as the modern surface **on purpose**: omitting a
sampling parameter is accepted by every model, while sending one 400s on the new
ones. When guessing, guess the way that cannot take the relay down.

These are read fresh per request, so ``/setmodel`` takes effect on the next
message with no restart — the same contract model/temp/max-tokens already had.
"""

import re
from typing import NamedTuple, Optional

# claude-<family>-<major>[-<minor>][-<snapshot date>]
# Matches claude-sonnet-5, claude-haiku-4-5, claude-opus-4-8,
# claude-fable-5-1 and dated snapshots like claude-haiku-4-5-20251001.
# Older ids (claude-3-haiku-20240307, claude-3-5-sonnet-…) deliberately do not
# match and fall through to the safe modern-surface default.
_MODEL_RE = re.compile(
    r"^claude-(haiku|sonnet|opus|fable|mythos)-(\d+)(?:-(\d+))?", re.IGNORECASE
)


class _ModelName(NamedTuple):
    family: str
    major: int
    minor: int


def _parse(model: str) -> Optional[_ModelName]:
    match = _MODEL_RE.match((model or "").strip())
    if not match:
        return None
    family, major, minor = match.group(1).lower(), match.group(2), match.group(3)
    return _ModelName(family, int(major), int(minor or 0))


def is_modern_surface(model: str) -> bool:
    """True if ``model`` is on the Opus 4.7+ request surface.

    That surface rejects sampling parameters and takes ``output_config.effort``.
    Unknown/unparseable ids answer True — see the module docstring for why that
    is the safe direction to guess.
    """
    parsed = _parse(model)
    if parsed is None:
        return True
    family, major, minor = parsed
    if family in ("fable", "mythos"):
        return True
    if family == "opus":
        # Opus 4.7 is where sampling params were removed.
        return major > 4 or (major == 4 and minor >= 7)
    # Sonnet and Haiku crossed over at their 5.x releases. Haiku 4.5 — the model
    # this bot defaulted to — is the notable "still accepts temperature" case.
    return major >= 5


def supports_sampling_params(model: str) -> bool:
    """True if ``temperature``/``top_p``/``top_k`` may be sent to ``model``."""
    return not is_modern_surface(model)


def supports_effort(model: str) -> bool:
    """True if ``output_config.effort`` may be sent to ``model``.

    Tied to the modern surface. Opus 4.5/4.6 also accept ``effort``, but it
    errors on Sonnet 4.5 / Haiku 4.5, and skipping an optional tuning knob on a
    4.6-era model is harmless where sending it to Haiku 4.5 is not.
    """
    return is_modern_surface(model)


def uses_adaptive_thinking(model: str) -> bool:
    """True if ``thinking: {"type": "adaptive"}`` should be sent to ``model``.

    Sent explicitly rather than relying on the default, because the default is
    not consistent across the surface: omitting ``thinking`` runs adaptive on
    Opus 5 / Sonnet 5 but runs thinking-*off* on Opus 4.7/4.8.
    """
    return is_modern_surface(model)


def build_model_params(
    model: str,
    *,
    temperature: Optional[float] = None,
    effort: Optional[str] = None,
) -> dict:
    """Build the model-specific part of a ``messages.create`` call.

    Returns only the keys that are valid for ``model``:

    * older models get ``extra_body={"temperature": …}`` when a temperature is
      configured (1.x dropped the named kwarg, so it travels in the body);
    * modern models get ``thinking`` plus ``output_config={"effort": …}`` and no
      sampling parameter at all.
    """
    params: dict = {}
    if supports_sampling_params(model):
        if temperature is not None:
            # anthropic 1.x removed the named `temperature` kwarg; extra_body is
            # merged into the request JSON as-is.
            params["extra_body"] = {"temperature": temperature}
        return params

    if uses_adaptive_thinking(model):
        params["thinking"] = {"type": "adaptive"}
    if effort and supports_effort(model):
        params["output_config"] = {"effort": effort}
    return params
