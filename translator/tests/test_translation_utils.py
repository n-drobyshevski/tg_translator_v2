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
    # anthropic 1.x removed `temperature` from the messages.create() signature,
    # so it must never be a top-level kwarg on any model — passing it directly
    # raises TypeError against the real SDK (and TypeError is non-retryable, so
    # it would kill every translation permanently). Whether it is sent at all is
    # model-dependent; that is covered by the two tests below.
    assert "temperature" not in captured


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
@pytest.mark.parametrize("model", ["claude-sonnet-5", "claude-haiku-4-5"])
async def test_translate_html_kwargs_match_the_real_sdk_signature(monkeypatch, model):
    """Bind the kwargs we build against the *installed* SDK's create().

    Every other test here fakes `create(**kwargs)`, which swallows any argument —
    so none of them can notice when the SDK drops a parameter. That is exactly how
    anthropic 1.x removing `temperature` would have reached production: a
    TypeError on every single translation, and non-retryable to boot. Binding the
    real signature turns the next such removal into a failing test instead.

    Run for both request surfaces, since the shape differs by model: the modern
    one sends `thinking`/`output_config`, the older one `extra_body`.
    """
    from anthropic import AsyncAnthropic

    monkeypatch.setattr(CONFIG, "ANTHROPIC_MODEL", model)
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


def _capturing_client(captured, *, content=None, stop_reason="end_turn"):
    """A minimal stand-in that records the kwargs translate_html builds."""

    class FakeMessages:
        @staticmethod
        def create(**kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                stop_reason=stop_reason,
                content=content
                if content is not None
                else [SimpleNamespace(type="text", text="translated!")],
            )

    class FakeClient:
        messages = FakeMessages

    return FakeClient


# The model is switchable at runtime, so these pin it explicitly rather than
# relying on the ambient CONFIG — `env_store.set_env_var` writes straight to
# os.environ, so an earlier /setmodel test can otherwise leak its model here.


@pytest.mark.asyncio
async def test_legacy_model_gets_temperature_and_no_thinking(monkeypatch):
    monkeypatch.setattr(CONFIG, "ANTHROPIC_MODEL", "claude-haiku-4-5")
    monkeypatch.setattr(CONFIG, "ANTHROPIC_TEMPERATURE", 0.0)
    captured = {}
    await translate_html(_capturing_client(captured), {"Html": "hi"})

    # Haiku 4.5 still accepts sampling params; 1.x needs them in extra_body.
    assert captured["extra_body"] == {"temperature": 0.0}
    # ...and rejects the modern-surface knobs, so they must not be sent.
    assert "thinking" not in captured
    assert "output_config" not in captured


@pytest.mark.asyncio
async def test_modern_model_omits_temperature_and_sends_effort(monkeypatch):
    monkeypatch.setattr(CONFIG, "ANTHROPIC_MODEL", "claude-sonnet-5")
    monkeypatch.setattr(CONFIG, "ANTHROPIC_EFFORT", "low")
    captured = {}
    await translate_html(_capturing_client(captured), {"Html": "hi"})

    # Sonnet 5 400s on a non-default temperature — it must not be sent at all.
    assert "temperature" not in captured
    assert "extra_body" not in captured
    # Sent explicitly: omitting `thinking` means adaptive on Sonnet 5 but
    # thinking-OFF on Opus 4.7/4.8, and we want one behaviour across the surface.
    assert captured["thinking"] == {"type": "adaptive"}
    assert captured["output_config"] == {"effort": "low"}


@pytest.mark.asyncio
async def test_text_extracted_past_a_leading_thinking_block(monkeypatch):
    """With adaptive thinking the FIRST content block is a thinking block, which
    has no `.text` — the old `resp.content[0].text` would AttributeError on every
    single translation. thinking.display defaults to "omitted", so the block is
    present with empty text even when reasoning isn't surfaced."""
    monkeypatch.setattr(CONFIG, "ANTHROPIC_MODEL", "claude-sonnet-5")
    captured = {}
    client = _capturing_client(
        captured,
        content=[
            SimpleNamespace(type="thinking", thinking=""),
            SimpleNamespace(type="text", text="<b>Translated.</b>"),
        ],
    )
    assert await translate_html(client, {"Html": "hi"}) == "<b>Translated.</b>"


@pytest.mark.asyncio
async def test_thinking_only_response_is_rejected(monkeypatch):
    # No text block at all -> better to fail the relay than post an empty message.
    monkeypatch.setattr(CONFIG, "ANTHROPIC_MODEL", "claude-sonnet-5")
    client = _capturing_client(
        {}, content=[SimpleNamespace(type="thinking", thinking="…")]
    )
    with pytest.raises(ValueError, match="no text block"):
        await translate_html(client, {"Html": "hi"})


@pytest.mark.asyncio
async def test_truncated_response_is_rejected(monkeypatch):
    """A max_tokens stop means the translation is cut off mid-post. Adaptive
    thinking shares the max_tokens budget, so this is the failure mode of an
    under-sized ANTHROPIC_MAX_TOKENS — never publish the partial text."""
    monkeypatch.setattr(CONFIG, "ANTHROPIC_MODEL", "claude-sonnet-5")
    client = _capturing_client(
        {},
        stop_reason="max_tokens",
        content=[SimpleNamespace(type="text", text="<b>Half a transl")],
    )
    with pytest.raises(ValueError, match="max_tokens"):
        await translate_html(client, {"Html": "hi"})
