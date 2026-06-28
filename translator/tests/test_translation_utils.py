import pytest
from unittest.mock import patch
from types import SimpleNamespace
from translator.utils import translation_utils
from translator.utils.translation_utils import translate_html, build_prompt


def test_build_prompt_short_message():
    res = build_prompt("hello", "testchan", "link")
    assert "Translate the following HTML message" in res


def test_build_prompt_long_message():
    with patch("pathlib.Path.exists", return_value=False):
        msg = " ".join(["word"] * 50)
        res = translation_utils.build_prompt(msg, "testchan", "link")
        assert "{message_text}" not in res
        assert msg in res


@pytest.mark.asyncio
async def test_translate_html_makes_api_call():
    class FakeMessages:
        @staticmethod
        def create(**kwargs):
            return SimpleNamespace(content=[SimpleNamespace(text="translated!")])

    class FakeClient:
        messages = FakeMessages

    payload = {"Html": "hi", "Channel": "x", "Link": "y"}
    result = await translate_html(FakeClient, payload)
    assert result == "translated!"
