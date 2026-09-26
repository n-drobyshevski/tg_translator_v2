"""Tests for the dual (rich + classic) renderer behind every admin DM message.

Telegram validates the rich dialect server-side only, so what is pinned down
here is everything that *can* be checked locally: each block's two renderings,
escaping, the size limits of both targets, tag balance after truncation, the
kill switch, and that every tag we can emit has a /richcheck probe.
"""

from html.parser import HTMLParser

import pytest

from translator.services import rich_html
from translator.services.rich_html import (
    KV,
    Bullets,
    Details,
    Doc,
    Footer,
    Heading,
    Hr,
    Note,
    Para,
    Pre,
    Quote,
    RawQuote,
    RichText,
    Setting,
    Status,
    Table,
)

_VOID = {"br", "hr", "img", "input"}


class _Tags(HTMLParser):
    """Collects tag names (+ attribute names) and checks nesting balance."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.tags = set()
        self.attrs = set()
        self.balanced = True

    def handle_starttag(self, tag, attrs):
        self.tags.add(tag)
        self.attrs |= {(tag, name) for name, _ in attrs}
        if tag not in _VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.tags.add(tag)
        self.attrs |= {(tag, name) for name, _ in attrs}

    def handle_endtag(self, tag):
        if tag in _VOID:
            return
        if not self.stack or self.stack.pop() != tag:
            self.balanced = False


def _parse(markup: str) -> _Tags:
    p = _Tags()
    p.feed(markup)
    p.close()
    return p


def _balanced(markup: str) -> bool:
    p = _parse(markup)
    return p.balanced and not p.stack


def _outside_pre(markup: str) -> str:
    """The markup with every <pre>…</pre> body removed."""
    out, rest = [], markup
    while "<pre" in rest:
        before, _, after = rest.partition("<pre")
        out.append(before)
        rest = after.partition("</pre>")[2]
    out.append(rest)
    return "".join(out)


# --------------------------------------------------------------------------- #
# Blocks
# --------------------------------------------------------------------------- #


def test_heading_and_para():
    out = Doc(Heading("Title"), Para("a", "b")).render()
    assert out == "<b>Title</b>\na\nb"  # heading is "tight": one newline after it
    assert out.rich == "<h3>Title</h3><p>a<br>b</p>"


def test_kv_renders_label_colon_value_in_classic():
    out = Doc(KV([("Relayed events", 2), ("Model", "<code>x</code>")])).render()
    assert out == "Relayed events: 2\nModel: <code>x</code>"
    assert out.rich.startswith("<table compact><tr><td><b>Relayed events</b></td><td>2</td>")


def test_setting_renders_key_equals_value():
    out = Doc(Setting("ANTHROPIC_TEMPERATURE", 0.5)).render()
    assert out == "ANTHROPIC_TEMPERATURE = 0.5"
    assert out.rich == "<p><code>ANTHROPIC_TEMPERATURE</code> = <b>0.5</b></p>"


def test_table_uses_classic_row_and_drops_the_header():
    table = Table(["", "When"], [["✅", "10:00"], ["❌", "11:00"]],
                  classic_row=lambda r: f"{r[0]} {r[1]} UTC")
    out = Doc(table).render()
    assert out == "✅ 10:00 UTC\n❌ 11:00 UTC"
    assert "<th>When</th>" in out.rich and out.rich.count("<tr>") == 3


def test_empty_table_shows_its_placeholder():
    out = Doc(Table(["a"], [], empty="(none)")).render()
    assert out == "(none)"
    assert out.rich == "<p>(none)</p>"


def test_table_caps_rows_in_rich():
    rows = [[str(i)] for i in range(rich_html.MAX_TABLE_ROWS + 5)]
    out = Doc(Table(["n"], rows)).render()
    assert out.rich.count("<tr>") == rich_html.MAX_TABLE_ROWS + 1  # + header
    assert "+5" in out.rich


def test_cells_never_carry_a_newline():
    out = Doc(Table(["a"], [["x\ny"]]), KV([("k", "v\nw")])).render()
    assert "\n" not in out.rich


def test_bullets():
    out = Doc(Bullets(["a", "b"]), Bullets(["c"], ordered=True)).render()
    assert out == "• a\n• b\n\n1. c"
    assert out.rich == "<ul><li>a</li><li>b</li></ul><ol><li>c</li></ol>"


def test_status_puts_the_outcome_icon_first():
    assert str(Doc(Status(True, "Saved")).render()).startswith("✅")
    assert str(Doc(Status(False, "Nope")).render()).startswith("❌")
    assert str(Doc(Status(None, "Hm")).render()).startswith("❓")
    out = Doc(Status(True, "Saved")).render()
    assert out.status is True and out.rich == "<h4>✅ Saved</h4>"


def test_doc_status_comes_from_the_first_status_block():
    out = Doc(Para("x"), Status(False, "a"), Status(True, "b")).render()
    assert out.status is False


def test_details_classic_is_bold_summary_plus_expandable_quote():
    out = Doc(Details("More", Para("inside"), Pre("<x>"))).render()
    assert out == "<b>More</b>\n<blockquote expandable>inside\n&lt;x&gt;</blockquote>"
    assert out.rich == "<details><summary>More</summary><p>inside</p><pre>&lt;x&gt;</pre></details>"
    assert Doc(Details("s", open=True)).render().rich.startswith("<details open>")


def test_quotes_notes_hr_footer():
    out = Doc(Quote("a", "b", expandable=True), Note("careful"), Hr(), Footer("f")).render()
    assert out.rich == (
        "<blockquote expandable>a<br>b</blockquote>"
        "<blockquote>⚠️ careful</blockquote><hr/><footer>f</footer>"
    )
    assert "<blockquote expandable>a\nb</blockquote>" in out
    assert "⚠️ careful" in out and "<i>f</i>" in out


def test_raw_blocks_escape_their_text():
    out = Doc(Pre("<script>&"), RawQuote("a<b>\nc")).render()
    assert "<script>" not in out and "<script>" not in out.rich
    assert "&lt;script&gt;&amp;" in out.rich
    assert "<blockquote expandable>a&lt;b&gt;<br>c</blockquote>" in out.rich


def test_pre_with_a_language():
    out = Doc(Pre("x", lang="python")).render()
    assert out.rich == '<pre><code class="language-python">x</code></pre>'
    assert out == "<pre>x</pre>"


def test_rich_never_uses_a_bare_newline_for_layout():
    doc = Doc(
        Heading("h\nx"), Para("a\nb"), KV([("k", "v")]), Bullets(["a\nb"]),
        Quote("q\nr"), RawQuote("1\n2"), Details("s", Para("p\nq")), Footer("f\ng"),
        Note("n\nm"), Status(True, "t\nu"), Pre("keep\nthese"),
    )
    assert "\n" not in _outside_pre(doc.render().rich)


# --------------------------------------------------------------------------- #
# Limits & truncation
# --------------------------------------------------------------------------- #


def _log(n):
    return "\n".join(f"line {i}" for i in range(n))


def test_tail_is_kept_for_logs():
    out = Doc(Heading("Logs"), Pre(_log(20000)), Footer("end")).render()
    assert "line 19999" in out and "line 19999" in out.rich
    assert "line 0\n" not in out
    assert out.endswith("<i>end</i>") and out.rich.endswith("<footer>end</footer>")
    assert len(out) <= rich_html.CLASSIC_LIMIT
    assert len(out.rich.encode()) <= rich_html.RICH_LIMIT


def test_head_is_kept_for_a_prompt():
    out = Doc(Pre(_log(20000), keep="head")).render()
    assert "line 0\n" in out and "line 19999" not in out
    assert out.rich.startswith("<pre>line 0")


def test_classic_max_lines_limits_only_the_fallback():
    out = Doc(Pre(_log(150), classic_max_lines=30)).render()
    assert "line 149" in out and "line 120" in out and "line 119" not in out
    assert "line 0\n" in out.rich


@pytest.mark.parametrize("char", ["é", "ф", "😀", "<"])
def test_limits_hold_for_multibyte_and_escaped_text(char):
    out = Doc(Heading("x"), Pre(char * 100_000), RawQuote(char * 50_000), Footer("f")).render()
    assert len(out) <= rich_html.CLASSIC_LIMIT
    assert len(out.rich.encode("utf-8")) <= rich_html.RICH_LIMIT
    assert _balanced(out) and _balanced(out.rich)


def test_oversized_fixed_content_drops_trailing_blocks_but_stays_balanced():
    doc = Doc(*[Para("p" * 500) for _ in range(20)])
    out = doc.render()
    assert len(out) <= rich_html.CLASSIC_LIMIT
    assert out.endswith("…") and _balanced(out)


def test_last_resort_is_plain_escaped_text():
    out = Doc(Para("<b>" + "x" * 10_000 + "</b>")).render(classic_limit=100)
    assert len(out) <= 100 and "<" not in out.replace("&lt;", "")


def test_truncation_leaves_elastic_blocks_reusable():
    doc = Doc(Pre(_log(20000)))
    first = doc.render()
    assert doc.render() == first  # budgets are reset after each render


# --------------------------------------------------------------------------- #
# RichText & helpers
# --------------------------------------------------------------------------- #


def test_richtext_is_a_str_of_the_classic_rendering():
    out = rich_html.status_ok("Saved", Setting("A", 1))
    assert isinstance(out, str) and isinstance(out, RichText)
    assert out.startswith("✅") and "A = 1" in out and out.rich


def test_outcome_reads_status_then_prefix():
    assert rich_html.outcome(rich_html.status_ok("x")) is True
    assert rich_html.outcome(rich_html.status_err("x")) is False
    assert rich_html.outcome("✅ legacy") is True
    assert rich_html.outcome("❌ legacy") is False
    assert rich_html.outcome("plain") is None
    assert rich_html.outcome(None) is None


def test_from_classic_builds_paragraphs():
    out = rich_html.from_classic("<b>A</b>\nline\n\nsecond")
    assert out == "<b>A</b>\nline\n\nsecond"
    assert out.rich == "<p><b>A</b><br>line</p><p>second</p>"


def test_from_classic_stays_classic_around_block_tags():
    assert rich_html.from_classic("x\n<pre>y</pre>").rich is None


def test_as_content_accepts_doc_richtext_and_str():
    doc = Doc(Para("x"))
    rendered = doc.render()
    assert rich_html.as_content(rendered) is rendered
    assert rich_html.as_content(doc).rich == "<p>x</p>"
    assert rich_html.as_content("x").rich == "<p>x</p>"


def test_extend_keeps_blocks_and_status():
    doc = Doc(Para("before")).extend(Doc(Status(False, "x")))
    out = doc.render()
    assert out.status is False and out.startswith("before")


# --------------------------------------------------------------------------- #
# Kill switch
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "new,legacy,expected",
    [
        (None, None, True),  # default: on
        ("0", None, False),
        ("off", None, False),
        ("1", None, True),
        (None, "0", False),  # an explicit legacy opt-out is honoured
        (None, "1", True),
        ("1", "0", True),  # the new name wins
        ("0", "1", False),
        ("", "0", False),  # empty means "not set"
        ("  ", None, True),
    ],
)
def test_env_matrix(monkeypatch, new, legacy, expected):
    for name, value in ((rich_html.RICH_ENV, new), (rich_html.LEGACY_RICH_ENV, legacy)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    assert rich_html.rich_env_enabled() is expected


def test_env_source_names_the_deciding_setting(monkeypatch):
    assert rich_html.rich_env_source() == "default"
    monkeypatch.setenv(rich_html.LEGACY_RICH_ENV, "0")
    assert "deprecated" in rich_html.rich_env_source()
    monkeypatch.setenv(rich_html.RICH_ENV, "1")
    assert rich_html.rich_env_source() == f"{rich_html.RICH_ENV}=1"


# --------------------------------------------------------------------------- #
# Probes cover everything we emit
# --------------------------------------------------------------------------- #


def test_every_emitted_tag_has_a_probe():
    """``/richcheck`` is the only real validation of the dialect, so a tag or
    attribute the renderer can emit must not be missing from the probes."""
    from translator.services import admin_menu

    kitchen_sink = Doc(
        Heading("h3"), Heading("h4", 4), Para("<b>b</b> <i>i</i> <code>c</code>", "l2"),
        KV([("k", "v")]), Setting("K", "v"), Table(["a"], [["1"]], caption="c"),
        Bullets(["a"]), Bullets(["b"], ordered=True), Quote("q"), Quote("q", expandable=True),
        RawQuote("r"), Pre("p"), Pre("p", lang="text"), Details("s", Para("x")),
        Details("s", open=True), Hr(), Footer("f"), Status(True, "ok"), Note("n"),
    ).render().rich
    buttons = admin_menu.rich_button_rows(
        [[("a", "nav:a"), ("b", "rmchok:x"), ("c", "copy:t"), ("d", "x:nav:a")]]
    )
    emitted = _parse(kitchen_sink + buttons)
    probed = _parse("".join(html for _, html in rich_html.PROBES))
    assert emitted.tags <= probed.tags, emitted.tags - probed.tags
    assert emitted.attrs <= probed.attrs, emitted.attrs - probed.attrs


def test_probes_are_balanced_and_small():
    for name, html in rich_html.PROBES:
        assert _balanced(html), name
        assert len(html.encode()) < 1000, name


def test_tight_para_keeps_its_list_on_the_next_line():
    out = Doc(Para("Options:", tight=True), Bullets(["a"]), Para("after")).render()
    assert out == "Options:\n• a\n\nafter"
