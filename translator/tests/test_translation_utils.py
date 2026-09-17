import inspect
import pytest
from unittest.mock import patch
from types import SimpleNamespace
from translator.config import CONFIG
from translator.utils import translation_utils
from translator.utils.translation_utils import translate_html, build_messages


def test_build_messages_short_message():
    system, user = build_messages("hello")
    assert "Translate the user's HTML message" in system
    assert user == "hello"


def test_build_messages_long_message():
    msg = " ".join(["word"] * 50)
    system, user = build_messages(msg)
    # The fixed instructions go to the system prompt; the source post goes to the
    # user turn. The {message_text} placeholder must never leak into either.
    assert "{message_text}" not in system
    assert "{message_text}" not in user
    assert msg in user


@pytest.mark.asyncio
async def test_translate_html_makes_api_call():
    captured = {}

    class FakeMessages:
        @staticmethod
        def create(**kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                stop_reason="end_turn",
                content=[SimpleNamespace(text="translated!")],
            )

    class FakeClient:
        messages = FakeMessages

    payload = {"Html": "hi", "Channel": "x", "Link": "y"}
    result = await translate_html(FakeClient, payload)
    assert result == "translated!"
    # The fixed prompt must be sent as a cache-controlled system block.
    assert captured["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert captured["messages"][0]["role"] == "user"
    # anthropic 1.x removed `temperature` from the messages.create() signature.
    # It must travel in extra_body, never as a top-level kwarg — passing it
    # directly raises TypeError against the real SDK (and TypeError is
    # non-retryable, so it would kill every translation permanently).
    assert "temperature" not in captured
    assert captured["extra_body"] == {"temperature": CONFIG.ANTHROPIC_TEMPERATURE}


@pytest.mark.asyncio
async def test_translate_html_awaits_async_client():
    # An AsyncAnthropic-like client (coroutine `create`) must be awaited directly,
    # not run through asyncio.to_thread — this is the bot's path.
    captured = {}

    class FakeAsyncMessages:
        @staticmethod
        async def create(**kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                stop_reason="end_turn",
                content=[SimpleNamespace(text="async translated!")],
            )

    class FakeAsyncClient:
        messages = FakeAsyncMessages

    payload = {"Html": "hi", "Channel": "x", "Link": "y"}
    result = await translate_html(FakeAsyncClient, payload)
    assert result == "async translated!"
    assert captured["messages"][0]["role"] == "user"
    assert captured["system"][0]["cache_control"] == {"type": "ephemeral"}


@pytest.mark.asyncio
async def test_translate_html_awaits_decorated_async_sdk_client(monkeypatch):
    # Reproduces the real SDK: AsyncAnthropic.messages.create is wrapped by
    # @required_args into a *sync* function returning a coroutine, so
    # inspect.iscoroutinefunction(create) is False. The dispatch must still await it
    # (regression test for the bot posting nothing because resp was an unawaited
    # coroutine -> "'coroutine' object has no attribute 'content'").
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key="test-key")
    captured = {}

    async def _impl(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(text="async translated!")],
        )

    def sync_wrapper(**kwargs):  # mimics @required_args: sync def, returns coroutine
        return _impl(**kwargs)

    assert not inspect.iscoroutinefunction(sync_wrapper)  # the exact trap
    monkeypatch.setattr(client.messages, "create", sync_wrapper)

    payload = {"Html": "hi", "Channel": "x", "Link": "y"}
    result = await translate_html(client, payload)
    assert result == "async translated!"
    assert captured["system"][0]["cache_control"] == {"type": "ephemeral"}


@pytest.mark.asyncio
async def test_translate_html_kwargs_match_the_real_sdk_signature():
    """Bind the kwargs we build against the *installed* SDK's create().

    Every other test here fakes `create(**kwargs)`, which swallows any argument —
    so none of them can notice when the SDK drops a parameter. That is exactly how
    anthropic 1.x removing `temperature` would have reached production: a
    TypeError on every single translation, and non-retryable to boot. Binding the
    real signature turns the next such removal into a failing test instead.
    """
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key="test-key")
    captured = {}

    async def _impl(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(text="ok")],
        )

    real_create = client.messages.create
    try:
        client.messages.create = _impl
        await translate_html(client, {"Html": "hi", "Channel": "x", "Link": "y"})
    finally:
        client.messages.create = real_create

    assert captured, "translate_html did not call messages.create"
    # Raises TypeError if any captured kwarg is no longer accepted by the SDK.
    inspect.signature(real_create).bind(**captured)


@pytest.mark.asyncio
async def test_translate_html_guards_refusal():
    class FakeMessages:
        @staticmethod
        def create(**kwargs):
            # Claude 4+ refusal: stop_reason set, empty content array.
            return SimpleNamespace(stop_reason="refusal", content=[])

    class FakeClient:
        messages = FakeMessages

    payload = {"Html": "hi", "Channel": "x", "Link": "y"}
    with pytest.raises(ValueError):
        await translate_html(FakeClient, payload)
