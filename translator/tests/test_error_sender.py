"""Tests for failure alerting, incl. the ADMIN_CHAT_ID fallback."""

import httpx
import pytest

from translator.services import error_sender


@pytest.fixture(autouse=True)
def _reset_throttle():
    error_sender._last_sent.clear()
    yield
    error_sender._last_sent.clear()


async def test_no_chat_id_is_noop(monkeypatch):
    monkeypatch.delenv("ADMIN_ALERT_CHAT_ID", raising=False)
    monkeypatch.delenv("ADMIN_CHAT_ID", raising=False)
    assert await error_sender.send_alert("hello", key="k1") is False


async def test_falls_back_to_admin_chat_id(monkeypatch):
    monkeypatch.delenv("ADMIN_ALERT_CHAT_ID", raising=False)
    monkeypatch.setenv("ADMIN_CHAT_ID", "999")
    monkeypatch.setattr(error_sender, "BOT_TOKEN", "tok")

    captured = {}

    class _Resp:
        status_code = 200
        text = "ok"

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None):
            captured["json"] = json
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    ok = await error_sender.send_alert("boom", key="k2")
    assert ok is True
    assert captured["json"]["chat_id"] == "999"


async def test_alert_chat_id_takes_precedence(monkeypatch):
    monkeypatch.setenv("ADMIN_ALERT_CHAT_ID", "555")
    monkeypatch.setenv("ADMIN_CHAT_ID", "999")
    monkeypatch.setattr(error_sender, "BOT_TOKEN", "tok")

    captured = {}

    class _Resp:
        status_code = 200
        text = "ok"

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None):
            captured["json"] = json
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    await error_sender.send_alert("boom", key="k3")
    assert captured["json"]["chat_id"] == "555"
