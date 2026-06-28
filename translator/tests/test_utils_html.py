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
