"""Tests for humanize_error — turning raw exceptions into one readable line."""

from translator.utils.error_format import humanize_error


class FakeAPIError(Exception):
    """Stand-in for an Anthropic SDK APIStatusError (carries status_code + body)."""

    def __init__(self, status_code, message):
        super().__init__(f"Error code: {status_code} - {{'error': {{'message': {message!r}}}}}")
        self.status_code = status_code
        self.body = {"type": "error", "error": {"type": "x", "message": message}}


def test_credit_balance_maps_to_actionable_line():
    exc = FakeAPIError(
        400,
        "Your credit balance is too low to access the Anthropic API. "
        "Please go to Plans & Billing to upgrade or purchase credits.",
    )
    out = humanize_error(exc)
    assert out == "Anthropic credits exhausted. Top up under Plans & Billing."
    # No raw SDK noise leaks through.
    assert "Error code:" not in out
    assert "{" not in out


def test_rate_limit_by_status():
    exc = FakeAPIError(429, "Number of requests has exceeded your rate limit")
    assert humanize_error(exc) == "Rate limited by Anthropic; it will retry."


def test_overloaded_by_status():
    exc = FakeAPIError(529, "Overloaded")
    assert humanize_error(exc) == "Anthropic is temporarily overloaded; it will retry."


def test_auth_by_status():
    exc = FakeAPIError(401, "invalid x-api-key")
    assert humanize_error(exc) == "Anthropic API key rejected. Check ANTHROPIC_API_KEY."


def test_generic_400_falls_back_to_clean_inner_message():
    exc = FakeAPIError(400, "max_tokens: must be greater than 0")
    out = humanize_error(exc)
    assert out == "max_tokens: must be greater than 0"
    assert "Error code:" not in out


def test_plain_exception_uses_first_line_and_caps_length():
    exc = ValueError("something broke\nsecond line should be dropped")
    assert humanize_error(exc) == "something broke"

    long = ValueError("x" * 500)
    out = humanize_error(long)
    assert len(out) <= 160
    assert out.endswith("…")


def test_empty_exception_has_a_fallback():
    assert humanize_error(Exception("")) == "Unknown error."
