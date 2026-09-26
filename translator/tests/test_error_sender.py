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


# --- Rich alerts (Bot API 10.3 sendRichMessage) with a plain fallback ---------


class _Scripted:
    """httpx.AsyncClient stand-in: records (url, json), replies from a script."""

    posts = []
    script = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None):
        type(self).posts.append((url.rsplit("/", 1)[-1], json))
        outcome = type(self).script.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        resp = type("R", (), {"status_code": outcome, "text": "body"})
        return resp()


@pytest.fixture
def scripted(monkeypatch):
    monkeypatch.delenv("ADMIN_ALERT_CHAT_ID", raising=False)
    monkeypatch.setenv("ADMIN_CHAT_ID", "999")
    monkeypatch.setattr(error_sender, "BOT_TOKEN", "tok")
    _Scripted.posts = []
    _Scripted.script = []
    monkeypatch.setattr(httpx, "AsyncClient", _Scripted)
    return _Scripted


RELAY_FAIL = (
    "⚠️ Relay failed\n"
    "Channel: News <&>\n"
    "Post: https://t.me/c/1/2\n"
    "Reason: credits exhausted\n"
    "Traceback (most recent call last):\n"
    '  File "x.py", line 1\n'
    "ValueError: <boom>"
)


async def test_alert_is_sent_rich_first(scripted):
    scripted.script = [200]
    assert await error_sender.send_alert(RELAY_FAIL, key="r1") is True
    [(method, payload)] = scripted.posts
    assert method == "sendRichMessage"
    assert payload["chat_id"] == "999" and "text" not in payload
    html = payload["rich_message"]["html"]
    assert html.startswith("<h4>⚠️ Relay failed</h4><table compact>")
    assert "<td>News &lt;&amp;&gt;</td>" in html  # escaped
    assert '<a href="https://t.me/c/1/2">' in html
    # The traceback goes into an expandable quote, the exception line included.
    assert "<blockquote expandable>Traceback" in html
    assert "ValueError: &lt;boom&gt;</blockquote>" in html
    assert "<boom>" not in html
    assert html.endswith("UTC</footer>")


async def test_refused_rich_alert_falls_back_to_plain_text(scripted):
    scripted.script = [400, 200]
    assert await error_sender.send_alert(RELAY_FAIL, key="r2") is True
    assert [m for m, _ in scripted.posts] == ["sendRichMessage", "sendMessage"]
    assert scripted.posts[1][1] == {"chat_id": "999", "text": RELAY_FAIL}


async def test_rich_transport_error_falls_back_too(scripted):
    scripted.script = [httpx.ConnectError("down"), 200]
    assert await error_sender.send_alert("boom", key="r3") is True
    assert [m for m, _ in scripted.posts] == ["sendRichMessage", "sendMessage"]


async def test_both_failing_returns_false_without_raising(scripted):
    scripted.script = [400, 500]
    assert await error_sender.send_alert("boom", key="r4") is False


async def test_kill_switch_sends_plain_only(scripted, monkeypatch):
    monkeypatch.setenv("ADMIN_RICH_MESSAGES", "0")
    scripted.script = [200]
    assert await error_sender.send_alert("boom", key="r5") is True
    assert [m for m, _ in scripted.posts] == ["sendMessage"]


async def test_formatter_failure_degrades_to_plain(scripted, monkeypatch):
    def broken(text):
        raise RuntimeError("formatter bug")

    monkeypatch.setattr(error_sender, "build_alert_html", broken)
    scripted.script = [200]
    assert await error_sender.send_alert("boom", key="r6") is True
    assert [m for m, _ in scripted.posts] == ["sendMessage"]


async def test_throttle_still_applies(scripted):
    scripted.script = [200]
    assert await error_sender.send_alert("boom", key="same") is True
    assert await error_sender.send_alert("boom", key="same") is False
    assert len(scripted.posts) == 1


async def test_multi_admin_chat_id_uses_the_first(scripted, monkeypatch):
    # "111,222" is a valid ADMIN_CHAT_ID but not a valid Telegram chat id.
    monkeypatch.setenv("ADMIN_CHAT_ID", "111, 222")
    scripted.script = [200]
    await error_sender.send_alert("boom", key="r7")
    assert scripted.posts[0][1]["chat_id"] == "111"


def test_huge_alert_fits_both_limits():
    html = error_sender.build_alert_html("title\n" + "x" * 100_000)
    assert len(html.encode()) <= 32000
    assert "<blockquote expandable>" in html


def test_long_first_line_is_shortened_in_the_heading_but_kept_below():
    line = "2026-09-26 ERROR root - " + "y" * 300
    html = error_sender.build_alert_html(line)
    heading = html.split("</h4>")[0]
    assert heading.startswith("<h4>🚨 2026-09-26") and heading.endswith("…")
    assert "y" * 300 in html  # the full line survives in the quotation
