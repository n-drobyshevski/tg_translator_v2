"""Admin DM messages authored once, rendered as a rich message *and* classic HTML.

Bot API 10.1–10.3 added **rich messages** (``sendRichMessage`` / ``rich_message``
on ``editMessageText``): headings, tables, lists, collapsible ``<details>``,
footers and buttons inside the message body. The admin DM sends every message
that way — but the rich HTML dialect is validated **only by Telegram's servers**
(kurigram passes ``html=`` straight through), so nothing in CI can prove a
payload is accepted. Every message therefore also carries a classic Telegram
HTML rendering, which is what gets sent when the rich send is refused.

Rather than writing each screen twice, a screen is a :class:`Doc` of a few block
types. Each block renders itself for both targets:

* **rich** — real blocks (``<h3>``, ``<table>``, ``<details>`` …), never a bare
  ``"\\n"`` for layout (how the dialect treats newlines is undocumented), capped
  at :data:`RICH_LIMIT` UTF-8 bytes;
* **classic** — the layout operators already know (``label: value``,
  ``KEY = value``, ``✅ …`` first), capped at :data:`CLASSIC_LIMIT` characters.

:meth:`Doc.render` returns a :class:`RichText`: a ``str`` whose value is the
classic HTML (so every existing ``_cmd_*`` caller and ``startswith("✅")`` test
keeps working against exactly what the fallback sends), carrying the rich HTML
on ``.rich`` and the outcome on ``.status``. Concatenating a ``RichText`` with
``+`` yields a plain ``str`` and silently drops ``.rich`` — compose with
:meth:`Doc.add` instead.

Escaping convention: block constructors take **trusted inline HTML** (callers
``esc()`` data before interpolating, as the command code always has). The bulk
data blocks — :class:`Pre` and :class:`RawQuote` — take raw text and escape it
themselves, because they are also the ones that get truncated.

This module is stdlib-only and Pyrogram-free, so all of it is unit-testable.
"""

from __future__ import annotations

import html
import os
import re
from typing import Callable, Iterable, List, Optional, Sequence, Tuple

# Classic sendMessage caps text at 4096 characters; keep headroom.
CLASSIC_LIMIT = 4000
# Rich messages allow "32768 UTF-8 characters". Measured in *bytes* here, which
# is safe whichever of characters or bytes Telegram actually means.
RICH_LIMIT = 32000
# Well clear of the 500-blocks limit (each table row counts as a block).
MAX_TABLE_ROWS = 50

# Kill switch. On by default; read live on every call.
RICH_ENV = "ADMIN_RICH_MESSAGES"
# The opt-in flag from when only menus could be rich. Still honoured — an
# explicit ``ADMIN_RICH_MENUS=0`` was a deliberate opt-out — but the new name wins.
LEGACY_RICH_ENV = "ADMIN_RICH_MENUS"
_FALSEY = frozenset({"0", "false", "no", "off"})

_ELLIPSIS = "…"


def esc(value) -> str:
    """HTML-escape any value for interpolation into a block (text or attribute)."""
    return html.escape(str(value), quote=True)


# --- Kill switch --------------------------------------------------------------


def _env_value(name: str) -> Optional[str]:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None  # unset and empty both mean "not decided here"
    return raw.strip().lower()


def rich_env_enabled() -> bool:
    """True unless the env turns rich messages off (new name first, then legacy)."""
    for name in (RICH_ENV, LEGACY_RICH_ENV):
        value = _env_value(name)
        if value is not None:
            return value not in _FALSEY
    return True


def rich_env_source() -> str:
    """Which setting decided :func:`rich_env_enabled`, for the startup log."""
    for name, suffix in ((RICH_ENV, ""), (LEGACY_RICH_ENV, " (deprecated)")):
        raw = (os.getenv(name) or "").strip()
        if raw:
            return f"{name}={raw}{suffix}"
    return "default"


# --- Measures & truncation ----------------------------------------------------


def _rich_len(s: str) -> int:
    return len(s.encode("utf-8"))


def _classic_len(s: str) -> int:
    return len(s)


def _cut_escaped(line: str, budget: int, keep: str, measure) -> str:
    """Longest end (or start) of ``line`` whose *escaped* form fits ``budget``."""
    chars = line[::-1] if keep == "tail" else line
    out: List[str] = []
    used = 0
    for ch in chars:
        cost = measure(esc(ch))
        if used + cost > budget:
            break
        out.append(ch)
        used += cost
    piece = "".join(out)
    return esc(piece[::-1] if keep == "tail" else piece)


def _slice_lines(
    text: str,
    budget: Optional[int],
    *,
    keep: str,
    measure,
    joiner: str,
) -> str:
    """Escape ``text`` line by line and join it, fitting ``budget`` if given.

    Keeps whole lines from the tail (logs, tracebacks: the newest / the
    exception is at the bottom) or the head (a prompt template), marking the cut
    with ``…``. A single over-long line is cut mid-line rather than dropped.
    """
    lines = text.split("\n")
    full = joiner.join(esc(line) for line in lines)
    if budget is None or measure(full) <= budget:
        return full
    avail = budget - measure(_ELLIPSIS) - measure(joiner)
    if avail <= 0:
        return _ELLIPSIS
    ordered = list(reversed(lines)) if keep == "tail" else lines
    picked: List[str] = []
    used = 0
    for line in ordered:
        rendered = esc(line)
        cost = measure(rendered) + (measure(joiner) if picked else 0)
        if used + cost > avail:
            break
        picked.append(rendered)
        used += cost
    if not picked:
        picked = [_cut_escaped(ordered[0], avail, keep, measure)]
    if keep == "tail":
        return joiner.join([_ELLIPSIS] + list(reversed(picked)))
    return joiner.join(picked + [_ELLIPSIS])


def _inline_rich(fragment: str) -> str:
    """Inline HTML for the rich body: a stray newline becomes an explicit break."""
    return fragment.replace("\n", "<br>")


def _inline_cell(fragment: str) -> str:
    """Table cells hold inline content only — no line breaks at all."""
    return " ".join(str(fragment).split("\n"))


# --- Blocks -------------------------------------------------------------------


class Block:
    """One layout unit that knows how to render itself for both targets."""

    # Classic output: joined to the *next* block by "\n" instead of "\n\n".
    tight = False
    # Elastic blocks absorb whatever budget is left when a message is too long.
    elastic = False

    def rich(self) -> str:  # pragma: no cover - abstract
        raise NotImplementedError

    def classic(self) -> str:  # pragma: no cover - abstract
        raise NotImplementedError

    def flat(self) -> str:
        """Classic HTML that is safe *inside* a classic ``<blockquote>``."""
        return self.classic()

    def children(self) -> Sequence["Block"]:
        return ()


class Heading(Block):
    tight = True

    def __init__(self, html_: str, level: int = 3):
        self.html = html_
        self.level = min(max(int(level), 1), 6)

    def rich(self) -> str:
        return f"<h{self.level}>{_inline_rich(self.html)}</h{self.level}>"

    def classic(self) -> str:
        return f"<b>{self.html}</b>"


class Para(Block):
    """A paragraph; several arguments become lines separated by a break.

    ``tight=True`` keeps the next block on the following line in the classic
    rendering — for an intro such as "Options:" directly above its list.
    """

    def __init__(self, *lines: str, tight: bool = False):
        self.lines = [ln for ln in lines if ln]
        self.tight = tight

    def rich(self) -> str:
        if not self.lines:
            return ""
        return "<p>" + "<br>".join(_inline_rich(ln) for ln in self.lines) + "</p>"

    def classic(self) -> str:
        return "\n".join(self.lines)


class KV(Block):
    """Label/value pairs: a compact two-column table, or ``label: value`` lines."""

    def __init__(self, pairs: Iterable[Tuple[str, str]]):
        self.pairs = [(str(k), str(v)) for k, v in pairs]

    def rich(self) -> str:
        if not self.pairs:
            return ""
        rows = "".join(
            f"<tr><td><b>{_inline_cell(k)}</b></td><td>{_inline_cell(v)}</td></tr>"
            for k, v in self.pairs
        )
        return f"<table compact>{rows}</table>"

    def classic(self) -> str:
        return "\n".join(f"{k}: {v}" for k, v in self.pairs)


class Setting(Block):
    """One persisted env setting: ``KEY = value``."""

    def __init__(self, key: str, value_html: str):
        self.key = key
        self.value = str(value_html)

    def rich(self) -> str:
        return f"<p><code>{esc(self.key)}</code> = <b>{_inline_rich(self.value)}</b></p>"

    def classic(self) -> str:
        return f"{esc(self.key)} = {self.value}"


class Table(Block):
    """A data table. Classic drops the header and prints one line per row."""

    def __init__(
        self,
        header: Sequence[str],
        rows: Iterable[Sequence[str]],
        *,
        classic_row: Optional[Callable[[Sequence[str]], str]] = None,
        caption: Optional[str] = None,
        empty: Optional[str] = None,
    ):
        self.header = [str(h) for h in header]
        self.rows = [[str(c) for c in row] for row in rows]
        self.classic_row = classic_row
        self.caption = caption
        self.empty = empty

    def rich(self) -> str:
        if not self.rows:
            return f"<p>{_inline_rich(self.empty)}</p>" if self.empty else ""
        parts = ["<table striped compact>"]
        if self.caption:
            parts.append(f"<caption>{_inline_cell(self.caption)}</caption>")
        if any(self.header):
            parts.append(
                "<tr>" + "".join(f"<th>{_inline_cell(h)}</th>" for h in self.header) + "</tr>"
            )
        for row in self.rows[:MAX_TABLE_ROWS]:
            parts.append("<tr>" + "".join(f"<td>{_inline_cell(c)}</td>" for c in row) + "</tr>")
        parts.append("</table>")
        if len(self.rows) > MAX_TABLE_ROWS:
            parts.append(f"<p>{_ELLIPSIS} +{len(self.rows) - MAX_TABLE_ROWS}</p>")
        return "".join(parts)

    def classic(self) -> str:
        if not self.rows:
            return self.empty or ""
        fmt = self.classic_row or (lambda cells: " · ".join(c for c in cells if c))
        return "\n".join(fmt(row) for row in self.rows)


class Bullets(Block):
    def __init__(self, items: Iterable[str], *, ordered: bool = False):
        self.items = [str(i) for i in items]
        self.ordered = ordered

    def rich(self) -> str:
        if not self.items:
            return ""
        tag = "ol" if self.ordered else "ul"
        body = "".join(f"<li>{_inline_rich(i)}</li>" for i in self.items)
        return f"<{tag}>{body}</{tag}>"

    def classic(self) -> str:
        if self.ordered:
            return "\n".join(f"{n}. {i}" for n, i in enumerate(self.items, 1))
        return "\n".join(f"• {i}" for i in self.items)


class Quote(Block):
    """A block quotation of trusted inline HTML lines."""

    def __init__(self, *lines: str, expandable: bool = False):
        self.lines = [ln for ln in lines if ln]
        self.expandable = expandable

    def _open(self) -> str:
        return "<blockquote expandable>" if self.expandable else "<blockquote>"

    def rich(self) -> str:
        if not self.lines:
            return ""
        body = "<br>".join(_inline_rich(ln) for ln in self.lines)
        return f"{self._open()}{body}</blockquote>"

    def classic(self) -> str:
        if not self.lines:
            return ""
        return f"{self._open()}" + "\n".join(self.lines) + "</blockquote>"

    def flat(self) -> str:
        return "\n".join(self.lines)


class _Elastic(Block):
    """Raw text that is escaped here and cut to fit whatever budget is left."""

    elastic = True

    def __init__(self, text: str, *, keep: str = "tail"):
        self.text = str(text)
        self.keep = keep
        # Set by the fitter for the render in progress; None = unlimited.
        self._budget: Optional[int] = None
        self._measure = _classic_len

    def _body(self, joiner: str, text: Optional[str] = None) -> str:
        return _slice_lines(
            self.text if text is None else text,
            self._budget,
            keep=self.keep,
            measure=self._measure,
            joiner=joiner,
        )


class Pre(_Elastic):
    """Preformatted raw text (logs, the prompt template)."""

    def __init__(
        self,
        text: str,
        *,
        lang: Optional[str] = None,
        keep: str = "tail",
        classic_max_lines: Optional[int] = None,
    ):
        super().__init__(text, keep=keep)
        self.lang = lang
        self.classic_max_lines = classic_max_lines

    def _classic_text(self) -> str:
        if not self.classic_max_lines:
            return self.text
        lines = self.text.split("\n")
        n = self.classic_max_lines
        lines = lines[-n:] if self.keep == "tail" else lines[:n]
        return "\n".join(lines)

    def rich(self) -> str:
        body = self._body("\n")
        if self.lang:
            return f'<pre><code class="language-{esc(self.lang)}">{body}</code></pre>'
        return f"<pre>{body}</pre>"

    def classic(self) -> str:
        return f"<pre>{self._body(chr(10), self._classic_text())}</pre>"

    def flat(self) -> str:
        return self._body("\n", self._classic_text())


class RawQuote(_Elastic):
    """Raw text as a (default: expandable) block quotation — e.g. a traceback."""

    def __init__(self, text: str, *, expandable: bool = True, keep: str = "tail"):
        super().__init__(text, keep=keep)
        self.expandable = expandable

    def _open(self) -> str:
        return "<blockquote expandable>" if self.expandable else "<blockquote>"

    def rich(self) -> str:
        return f"{self._open()}{self._body('<br>')}</blockquote>"

    def classic(self) -> str:
        return f"{self._open()}{self._body(chr(10))}</blockquote>"

    def flat(self) -> str:
        return self._body("\n")


class Details(Block):
    """Collapsible section. Classic: bold summary + an expandable quotation."""

    def __init__(self, summary_html: str, *blocks: Block, open: bool = False):
        self.summary = summary_html
        self.blocks = [b for b in blocks if b is not None]
        self.open = open

    def children(self) -> Sequence[Block]:
        return self.blocks

    def rich(self) -> str:
        head = "<details open>" if self.open else "<details>"
        body = "".join(b.rich() for b in self.blocks)
        return f"{head}<summary>{_inline_rich(self.summary)}</summary>{body}</details>"

    def _inner_flat(self) -> str:
        return "\n".join(s for s in (b.flat() for b in self.blocks) if s)

    def classic(self) -> str:
        inner = self._inner_flat()
        if not inner:
            return f"<b>{self.summary}</b>"
        return f"<b>{self.summary}</b>\n<blockquote expandable>{inner}</blockquote>"

    def flat(self) -> str:
        inner = self._inner_flat()
        return f"<b>{self.summary}</b>" + (f"\n{inner}" if inner else "")


class Hr(Block):
    def rich(self) -> str:
        return "<hr/>"

    def classic(self) -> str:
        return "──────────"


class Footer(Block):
    def __init__(self, html_: str):
        self.html = html_

    def rich(self) -> str:
        return f"<footer>{_inline_rich(self.html)}</footer>" if self.html else ""

    def classic(self) -> str:
        return f"<i>{self.html}</i>" if self.html else ""


_STATUS_ICONS = {True: "✅", False: "❌", None: "❓"}


class Status(Block):
    """Outcome line. Classic output *starts with* ✅ / ❌ / ❓ — alert detection
    and a lot of tests rely on that — and the doc's ``.status`` is set from it."""

    tight = True

    def __init__(self, ok: Optional[bool], title_html: str, *, icon: Optional[str] = None):
        self.ok = ok
        self.title = title_html
        self.icon = icon or _STATUS_ICONS[ok]

    def rich(self) -> str:
        return f"<h4>{self.icon} {_inline_rich(self.title)}</h4>"

    def classic(self) -> str:
        return f"{self.icon} <b>{self.title}</b>"


class Note(Block):
    """A call-out (warning / info) under the main content."""

    def __init__(self, html_: str, *, icon: str = "⚠️"):
        self.html = html_
        self.icon = icon

    def rich(self) -> str:
        return f"<blockquote>{self.icon} {_inline_rich(self.html)}</blockquote>"

    def classic(self) -> str:
        return f"{self.icon} {self.html}"


# --- Document & rendered result ----------------------------------------------


class RichText(str):
    """Rendered message: the ``str`` value is classic HTML; ``.rich`` is the
    rich-message HTML (None → classic only); ``.status`` is True / False / None."""

    rich: Optional[str]
    status: Optional[bool]
    doc: Optional["Doc"]

    def __new__(cls, classic: str, rich: Optional[str] = None, status=None, doc=None):
        obj = super().__new__(cls, classic)
        obj.rich = rich
        obj.status = status
        obj.doc = doc
        return obj


def _walk(blocks: Iterable[Block]):
    for b in blocks:
        yield b
        yield from _walk(b.children())


def _join(blocks: Sequence[Block], mode: str) -> str:
    if mode == "rich":
        return "".join(b.rich() for b in blocks)
    out = ""
    prev: Optional[Block] = None
    for b in blocks:
        piece = b.classic()
        if not piece:
            continue
        if prev is not None:
            out += "\n" if prev.tight else "\n\n"
        out += piece
        prev = b
    return out


def _strip_tags(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s))


def _hard_cut(text: str, limit: int, measure) -> str:
    out = esc(text)
    while out and measure(out) > limit - measure(_ELLIPSIS):
        text = text[: max(0, len(text) - max(1, len(text) // 20))]
        out = esc(text)
    return out + _ELLIPSIS


def _fit(blocks: Sequence[Block], mode: str, limit: int) -> str:
    """Render ``blocks`` for ``mode`` within ``limit``, keeping tags balanced."""
    measure = _rich_len if mode == "rich" else _classic_len
    elastic = [b for b in _walk(blocks) if b.elastic]

    def with_budget(budget):
        for b in elastic:
            b._budget = budget
            b._measure = measure

    try:
        with_budget(None)
        out = _join(blocks, mode)
        if measure(out) <= limit:
            return out

        # Give what the fixed part leaves over to the elastic blocks.
        with_budget(0)
        fixed = measure(_join(blocks, mode))
        spare = limit - fixed - 16
        if elastic and spare > 0:
            with_budget(spare // len(elastic))
            out = _join(blocks, mode)
            if measure(out) <= limit:
                return out

        # The fixed part alone is too big: drop trailing blocks.
        with_budget(0)
        kept = list(blocks)
        while len(kept) > 1:
            kept.pop()
            out = _join(kept + [Para(_ELLIPSIS)], mode)
            if measure(out) <= limit:
                return out

        # Last resort: plain escaped text, which is tag-safe by construction.
        return _hard_cut(_strip_tags(_join(blocks, "classic")), limit, measure)
    finally:
        with_budget(None)


class Doc:
    """An ordered list of blocks — one admin message."""

    def __init__(self, *blocks: Optional[Block], status: Optional[bool] = None):
        self.blocks: List[Block] = [b for b in blocks if b is not None]
        self._status = status

    def add(self, *blocks: Optional[Block]) -> "Doc":
        self.blocks.extend(b for b in blocks if b is not None)
        return self

    def extend(self, other: "Doc") -> "Doc":
        self.blocks.extend(other.blocks)
        if self._status is None:
            self._status = other._status
        return self

    @property
    def status(self) -> Optional[bool]:
        if self._status is not None:
            return self._status
        for b in self.blocks:
            if isinstance(b, Status):
                return b.ok
        return None

    def render(
        self, *, classic_limit: int = CLASSIC_LIMIT, rich_limit: int = RICH_LIMIT
    ) -> RichText:
        classic = _fit(self.blocks, "classic", classic_limit)
        rich = _fit(self.blocks, "rich", rich_limit)
        return RichText(classic, rich or None, self.status, self)


def status_ok(title_html: str, *blocks: Block) -> RichText:
    return Doc(Status(True, title_html), *blocks).render()


def status_err(title_html: str, *blocks: Block) -> RichText:
    return Doc(Status(False, title_html), *blocks).render()


def outcome(value) -> Optional[bool]:
    """True / False / None for a reply — structured status first, then the prefix."""
    status = getattr(value, "status", None)
    if status is not None:
        return status
    text = str(value or "")
    if text.startswith("✅"):
        return True
    if text.startswith("❌"):
        return False
    return None


def from_classic(text: str) -> RichText:
    """Best-effort rich rendering of a legacy classic-HTML string.

    A safety net for any reply that was not built as a :class:`Doc`: blank lines
    become paragraphs and single newlines become breaks. Text containing block
    tags (``pre`` / ``blockquote``) stays classic-only rather than risk an
    invalid nesting.
    """
    text = str(text)
    if "<pre" in text or "<blockquote" in text:
        return RichText(text, None, outcome(text))
    paras = [p for p in text.split("\n\n") if p.strip()]
    rich = "".join(f"<p>{p.strip(chr(10)).replace(chr(10), '<br>')}</p>" for p in paras)
    return RichText(text, rich or None, outcome(text))


def as_content(value) -> RichText:
    """Normalise a Doc / RichText / str into a :class:`RichText`."""
    if isinstance(value, RichText):
        return value
    if isinstance(value, Doc):
        return value.render()
    return from_classic(value)


# --- Dialect probes -----------------------------------------------------------
#
# One minimal document per rich feature this module (or the button rows in
# admin_menu) can emit. ``/richcheck`` sends each one to the operator and reports
# which ones Telegram accepts — the only way to validate the dialect for real.
# A unit test renders every block type and asserts its tags are covered here, so
# a new tag cannot ship without a probe.
PROBES: Tuple[Tuple[str, str], ...] = (
    ("inline", "<p><b>b</b> <i>i</i> <u>u</u> <s>s</s> <code>c</code> "
               '<a href="https://t.me">a</a> <tg-spoiler>x</tg-spoiler><br>line 2</p>'),
    ("heading", "<h3>h3</h3><h4>h4</h4><p>body</p>"),
    ("table", "<table compact><tr><td><b>k</b></td><td>v</td></tr></table>"),
    ("table_striped", "<table striped compact><caption>c</caption>"
                      "<tr><th>a</th><th>b</th></tr><tr><td>1</td><td>2</td></tr></table>"),
    ("lists", "<ul><li>a</li></ul><ol><li>b</li></ol>"),
    ("quote", "<blockquote>q<br>q2</blockquote>"),
    ("quote_expandable", "<blockquote expandable>q<br>q2</blockquote>"),
    ("pre", '<pre>x = 1</pre><pre><code class="language-text">y</code></pre>'),
    ("details", "<details><summary>s</summary><p>body</p></details>"
                "<details open><summary>s</summary><p>body</p></details>"),
    ("hr_footer", "<p>a</p><hr/><footer>f</footer>"),
    ("buttons", '<p>b</p><tg-button-row>'
                '<tg-button type="callback_data" data="noop">cb</tg-button>'
                '<tg-button type="callback_data" style="danger" data="noop">danger</tg-button>'
                "</tg-button-row>"),
    ("buttons_copy_disabled", '<p>b</p><tg-button-row>'
                              '<tg-button type="copy_text" text="copied">copy</tg-button>'
                              '<tg-button type="disabled">off</tg-button>'
                              "</tg-button-row>"),
)
