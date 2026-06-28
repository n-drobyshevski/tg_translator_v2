import pytest
from types import SimpleNamespace
from translator.utils.utils_html import entities_to_html
from pyrogram.enums import MessageEntityType


class DummyEntity(SimpleNamespace):
    pass


def test_entities_to_html_bold():
    ent = DummyEntity(offset=0, length=4, type=MessageEntityType.BOLD)
    result = entities_to_html("Test", [ent])
    assert "<b>Test</b>" == result


def test_entities_to_html_multiple_entities():
    ents = [
        DummyEntity(offset=0, length=4, type=MessageEntityType.BOLD),
        DummyEntity(offset=5, length=2, type=MessageEntityType.ITALIC),
    ]
    result = entities_to_html("Test Xy", ents)
    assert (
        "<b>Test</b> <i>Xy</i>" in result or "<i>Xy</i>" in result
    )  # Adjust as needed


def test_entities_to_html_empty():
    assert entities_to_html("", None) == ""


def ent(offset, length, type_, **kw):
    e = SimpleNamespace(offset=offset, length=length, type=type_)
    for k, v in kw.items():
        setattr(e, k, v)
    return e


def test_entities_to_html_code_and_pre():
    ents = [
        ent(0, 4, MessageEntityType.CODE),
        ent(5, 4, MessageEntityType.PRE, language="python"),
    ]
    text = "code pret"
    result = entities_to_html(text, ents)
    assert "<code>" in result or "language=" in result


def test_entities_to_html_pre_with_language_becomes_code_class():
    # A code block with a language must use the Bot API's supported form
    # (<pre><code class="language-x">), not kurigram's rejected <pre language="x">.
    ents = [ent(0, 4, MessageEntityType.PRE, language="python")]
    result = entities_to_html("code", ents)
    assert result == '<pre><code class="language-python">code</code></pre>'


def test_entities_to_html_pre_without_language_stays_bare():
    ents = [ent(0, 4, MessageEntityType.PRE, language=None)]
    result = entities_to_html("code", ents)
    assert result == "<pre>code</pre>"


def test_entities_to_html_text_link():
    ents = [ent(0, 4, MessageEntityType.TEXT_LINK, url="http://test.com")]
    result = entities_to_html("Test", ents)
    assert '<a href="http://test.com">' in result


def test_entities_to_html_text_mention():
    class DummyUser:
        id = 12345

    ents = [ent(0, 4, MessageEntityType.TEXT_MENTION, user=DummyUser())]
    result = entities_to_html("Test", ents)
    assert 'href="tg://user?id=12345"' in result


def test_entities_to_html_unknown_entity_type():
    ents = [ent(0, 4, "notype")]
    assert entities_to_html("Test", ents) == "Test"


def test_entities_to_html_strikethrough():
    ents = [ent(0, 4, MessageEntityType.STRIKETHROUGH)]
    assert entities_to_html("Test", ents) == "<s>Test</s>"


def test_entities_to_html_underline():
    ents = [ent(0, 4, MessageEntityType.UNDERLINE)]
    assert entities_to_html("Test", ents) == "<u>Test</u>"


def test_entities_to_html_spoiler_uses_tg_spoiler():
    ents = [ent(0, 4, MessageEntityType.SPOILER)]
    # Bot API spelling, not kurigram's <spoiler>.
    assert entities_to_html("Test", ents) == "<tg-spoiler>Test</tg-spoiler>"


def test_entities_to_html_blockquote():
    ents = [ent(0, 4, MessageEntityType.BLOCKQUOTE)]
    assert entities_to_html("Test", ents) == "<blockquote>Test</blockquote>"


def test_entities_to_html_expandable_blockquote():
    ents = [ent(0, 4, MessageEntityType.BLOCKQUOTE, expandable=True)]
    result = entities_to_html("Test", ents)
    assert result == "<blockquote expandable>Test</blockquote>"


def test_entities_to_html_custom_emoji_dropped_to_text():
    ents = [ent(0, 2, MessageEntityType.CUSTOM_EMOJI, custom_emoji_id="555")]
    # Custom emoji wrapper is stripped; inner text is kept.
    assert entities_to_html("Hi", ents) == "Hi"


def test_entities_to_html_escapes_leading_and_trailing_text():
    # "&" before the first entity and "<" after the last must be escaped so the
    # Bot API HTML parser doesn't choke (regression for the old escape/offset bug).
    text = "A & B bold C < D"
    ents = [ent(6, 4, MessageEntityType.BOLD)]  # "bold"
    result = entities_to_html(text, ents)
    assert result == "A &amp; B <b>bold</b> C &lt; D"


def test_entities_to_html_escapes_plain_text_without_entities():
    assert entities_to_html("a < b & c", None) == "a &lt; b &amp; c"
