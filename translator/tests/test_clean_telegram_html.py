"""Tests for the admin manager's Telegram HTML sanitizer.

The manual-post path runs model output through nh3 before handing it to the Bot
API, so anything this drops or mangles is lost (or rejected outright) on the way
to the channel.
"""

import pytest

from app.admin_manager import clean_telegram_html


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("<strong>x</strong>", "<b>x</b>"),
        ("<em>x</em>", "<i>x</i>"),
        ("<ins>x</ins>", "<u>x</u>"),
        ("<del>x</del>", "<s>x</s>"),
        ("<strike>x</strike>", "<s>x</s>"),
    ],
)
def test_html5_synonyms_normalize_to_telegram_tags(raw, expected):
    assert clean_telegram_html(raw) == expected


def test_code_block_survives_intact():
    """Regression: `<p[^>]*>` also matched `<pre>`, so a code block lost its
    opening tag and kept its `</pre>` — malformed HTML that Telegram rejects
    with "Can't parse entities"."""
    raw = '<pre><code class="language-python">x = 1</code></pre>'
    assert clean_telegram_html(raw) == raw


def test_code_block_between_paragraphs():
    out = clean_telegram_html("<p>Intro</p><pre><code>code</code></pre><p>Outro</p>")
    assert "<pre><code>code</code></pre>" in out
    assert out.count("</pre>") == 1
    assert out.count("<pre>") == 1


def test_paragraphs_become_line_breaks():
    """Regression: nh3 strips <p> as a disallowed tag, so converting it to a
    newline *after* cleaning found nothing and glued paragraphs together."""
    assert clean_telegram_html("<p>one</p><p>two</p>") == "one\ntwo"


@pytest.mark.parametrize("br", ["<br>", "<br/>", "<br />"])
def test_br_becomes_newline(br):
    assert clean_telegram_html(f"a{br}b") == "a\nb"


def test_span_spoiler_spelling_is_preserved():
    # <span class="tg-spoiler"> is the other spelling Telegram documents; it used
    # to be stripped, silently un-spoilering the text.
    assert clean_telegram_html('<span class="tg-spoiler">s</span>') == "<tg-spoiler>s</tg-spoiler>"


def test_tg_spoiler_tag_passes_through():
    assert clean_telegram_html("<tg-spoiler>s</tg-spoiler>") == "<tg-spoiler>s</tg-spoiler>"


def test_other_spans_are_stripped_without_orphan_tags():
    # Rewriting only the closing </span> would leave an orphan </tg-spoiler>.
    out = clean_telegram_html('<span style="color:red">plain</span>')
    assert out == "plain"
    assert "tg-spoiler" not in out


def test_expandable_blockquote_keeps_its_attribute():
    out = clean_telegram_html("<blockquote expandable>q</blockquote>")
    assert out.startswith("<blockquote expandable")
    assert "q</blockquote>" in out


def test_links_keep_href_and_gain_no_rel():
    # Telegram's <a> must not carry rel="noopener noreferrer".
    out = clean_telegram_html('<a href="https://t.me/x">link</a>')
    assert out == '<a href="https://t.me/x">link</a>'


def test_disallowed_tags_keep_their_text():
    assert clean_telegram_html("<div><h1>Title</h1></div>") == "Title"


def test_custom_emoji_stripped_by_default(monkeypatch):
    monkeypatch.delenv("PRESERVE_CUSTOM_EMOJI", raising=False)
    assert clean_telegram_html('<tg-emoji emoji-id="5368">X</tg-emoji>') == "X"


def test_custom_emoji_preserved_when_enabled(monkeypatch):
    # Bot API 9.4 lets bots send custom emoji directly; opt-in because the bot
    # must actually have access to the emoji or Telegram rejects the message.
    monkeypatch.setenv("PRESERVE_CUSTOM_EMOJI", "1")
    out = clean_telegram_html('<tg-emoji emoji-id="5368">X</tg-emoji>')
    assert out == '<tg-emoji emoji-id="5368">X</tg-emoji>'


def test_empty_input():
    assert clean_telegram_html("") == ""
