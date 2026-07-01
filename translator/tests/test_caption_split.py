"""Unit tests for the HTML-safe caption splitter used to relay photos whose
translated text exceeds Telegram's 1024-char caption limit."""

from translator.utils.message_utils import (
    CAPTION_LIMIT,
    split_caption_html,
    _tags_balanced,
)


def test_short_text_stays_whole():
    text = "<b>Short.</b>\n<p>One paragraph.</p>"
    caption, remainder = split_caption_html(text)
    assert caption == text
    assert remainder == ""


def test_splits_at_paragraph_boundary_under_limit():
    lead = "<b>Lead sentence.</b>"
    paras = "\n".join(f"<p>Paragraph {i} with body text here.</p>" for i in range(60))
    text = f"{lead}\n\n{paras}"
    assert len(text) > CAPTION_LIMIT

    caption, remainder = split_caption_html(text)
    assert 0 < len(caption) <= CAPTION_LIMIT
    assert remainder
    # Neither side has a dangling tag.
    assert _tags_balanced(caption)
    assert _tags_balanced(remainder)
    # Caption leads with the bold sentence and ends on a closed paragraph.
    assert caption.startswith(lead)
    assert caption.rstrip().endswith("</p>") or caption.rstrip().endswith("</b>")


def test_never_cuts_inside_a_multiline_tag():
    # A <p> that wraps across a newline: the split must not break after the
    # inner newline (which would leave <p> unclosed in the caption).
    inner = "first physical line\nsecond physical line still same paragraph."
    text = "<b>Lead.</b>\n\n" + ("<p>%s</p>\n" % inner) * 30
    assert len(text) > CAPTION_LIMIT

    caption, remainder = split_caption_html(text)
    assert _tags_balanced(caption)
    assert _tags_balanced(remainder)
    # No caption line should end in the middle of a <p> block.
    assert caption.count("<p>") == caption.count("</p>")


def test_giant_first_paragraph_gives_empty_caption():
    # One paragraph with no newline and longer than the limit → nothing can go
    # in the caption without cutting a tag, so caption is empty and everything
    # is relayed as the reply (photo sent without a caption).
    text = "<p>" + ("x" * (CAPTION_LIMIT + 500)) + "</p>"
    caption, remainder = split_caption_html(text)
    assert caption == ""
    assert remainder == text


def test_link_is_not_split():
    lead = "<b>Lead.</b>"
    link_para = "<p>See <a href='https://example.org/very/long/path'>this link</a> here.</p>"
    text = lead + "\n\n" + "\n".join([link_para] * 25)
    caption, remainder = split_caption_html(text)
    # An <a> tag must never be left half-open in either side.
    assert _tags_balanced(caption)
    assert _tags_balanced(remainder)
    assert caption.count("<a") == caption.count("</a>")
