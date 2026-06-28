import html
import re
from typing import Any, List, Optional

from pyrogram.parser.html import HTML
from pyrogram.parser import utils as parser_utils

# kurigram's HTML.unparse renders every entity type (bold, italic, underline,
# strikethrough, spoiler, code, pre, blockquote / expandable blockquote, links,
# mentions, custom emoji, formatted dates) with correct UTF-16 offset handling.
# A few of the tags it emits are MTProto-flavoured and are NOT accepted by the
# Telegram Bot API HTML parser; the regexes below rewrite or drop them.
_SPOILER_OPEN_RE = re.compile(r"<spoiler>")
_SPOILER_CLOSE_RE = re.compile(r"</spoiler>")
_TG_EMOJI_RE = re.compile(r"<tg-emoji\b[^>]*>(.*?)</tg-emoji>", re.DOTALL)
_TG_TIME_RE = re.compile(r"<tg-time\b[^>]*>(.*?)</tg-time>", re.DOTALL)
# A code block carrying a language: kurigram emits ``<pre language="x">…</pre>``,
# which the Bot API rejects. The Bot API expresses a language via a nested
# ``<code class="language-x">`` instead, so rewrite the whole block.
_PRE_LANG_RE = re.compile(r'<pre language="([^"]*)">(.*?)</pre>', re.DOTALL)
# Any remaining ``<pre …>`` (no language, or other stray attrs) → bare ``<pre>``.
_PRE_OPEN_RE = re.compile(r"<pre\b[^>]*>")


def _to_bot_api_html(rendered: str) -> str:
    """Normalize kurigram-rendered HTML to the subset the Bot API accepts.

    - ``<spoiler>`` → ``<tg-spoiler>`` (Bot API spelling).
    - Drop ``<tg-emoji>`` / ``<tg-time>`` wrappers, keeping their inner text.
      This is intentional, not a gap: a bot can't re-send a custom emoji it
      doesn't own, and the Bot API HTML dialect has no date tag — so the inner
      fallback text (the emoji glyph / the formatted date) is the correct output.
    - ``<pre language="x">…</pre>`` → ``<pre><code class="language-x">…</code></pre>``
      so code-block syntax highlighting survives (the Bot API's supported form);
      bare/attribute-only ``<pre>`` tags are flattened to ``<pre>``.
    """
    rendered = _SPOILER_OPEN_RE.sub("<tg-spoiler>", rendered)
    rendered = _SPOILER_CLOSE_RE.sub("</tg-spoiler>", rendered)
    rendered = _TG_EMOJI_RE.sub(r"\1", rendered)
    rendered = _TG_TIME_RE.sub(r"\1", rendered)
    rendered = _PRE_LANG_RE.sub(
        lambda m: f'<pre><code class="language-{html.escape(m.group(1), quote=True)}">'
        f"{m.group(2)}</code></pre>",
        rendered,
    )
    rendered = _PRE_OPEN_RE.sub("<pre>", rendered)
    return rendered


def _escape_outside_entities(
    rendered: str, text: str, entities: List[Any]
) -> str:
    """Escape the text before the first / after the last entity.

    ``HTML.unparse`` escapes text between and inside entities but leaves the
    leading and trailing un-entitied runs verbatim, so a bare ``&``/``<``/``>``
    there would break ``parse_mode="HTML"``. Escape just those two regions,
    matching unparse's UTF-16 (surrogate) offset space.
    """
    surrogated = parser_utils.add_surrogates(text)
    first = min(e.offset for e in entities)
    last = max(e.offset + e.length for e in entities)
    lead = parser_utils.remove_surrogates(surrogated[:first])
    trail = parser_utils.remove_surrogates(surrogated[last:])
    if lead and rendered.startswith(lead):
        rendered = html.escape(lead) + rendered[len(lead):]
    if trail and rendered.endswith(trail):
        rendered = rendered[: len(rendered) - len(trail)] + html.escape(trail)
    return rendered


def entities_to_html(text: str, entities: Optional[List[Any]]) -> str:
    """Convert Telegram message entities to Bot API-compatible HTML.

    Delegates the heavy lifting (UTF-16 offsets, nesting, the full set of
    entity types) to kurigram's own renderer, then normalizes the result to the
    tags the Telegram Bot API accepts.
    """
    if not entities:
        return html.escape(text)
    ents = list(entities)
    rendered = HTML.unparse(text, ents)
    rendered = _escape_outside_entities(rendered, text, ents)
    return _to_bot_api_html(rendered)
