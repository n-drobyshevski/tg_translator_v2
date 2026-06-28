import pytest
from translator.utils.channel_utils import format_channel_id, validate_channel


def test_format_channel_id_at():
    assert format_channel_id("@test") == "@test"


def test_format_channel_id_numeric():
    assert format_channel_id("123456") == "-100123456"


def test_format_channel_id_dash_numeric():
    assert format_channel_id("-123456") == "-100123456"


def test_format_channel_id_strange():
    assert format_channel_id("chan_1") == "@chan_1"


def test_format_channel_id_invalid(caplog):
    assert format_channel_id("") is None


def test_validate_channel_requests(monkeypatch):
    # Simulate a 200 OK with expected json
    class FakeResponse:
        status_code = 200

        def json(self):
            return {"result": {"title": "T", "type": "private"}}

    monkeypatch.setattr("requests.get", lambda *a, **k: FakeResponse())
    validate_channel("-100123", "Test", bot_token="tok")  # Should not raise


def test_format_channel_id_none():
    assert format_channel_id(None) is None


def test_format_channel_id_invalid(monkeypatch):
    monkeypatch.setattr("logging.error", lambda *a, **k: None)
    assert format_channel_id("$$$") is None


def test_validate_channel_error(monkeypatch):
    class BadResponse:
        status_code = 400

        def json(self):
            return {"description": "bad"}

    monkeypatch.setattr("requests.get", lambda *a, **k: BadResponse())
    with pytest.raises(ValueError):
        validate_channel("chan", "chan", bot_token="tok")
