import pytest
from unittest.mock import patch
from types import SimpleNamespace
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
