import asyncio
import inspect
from typing import Any, Dict, Tuple, Union
from anthropic import Anthropic, AsyncAnthropic
import logging
import re
from translator.config import CONFIG, load_prompt_template

PROMPT_TEMPLATE = load_prompt_template()


def reload_prompt_template() -> str:
    """Re-read prompt_template.txt into the module global used by build_messages.

    The bot loads ``PROMPT_TEMPLATE`` once at import, so a live edit (the
    ``/setprompt`` DM command) must call this to take effect without a restart.
    ``build_messages`` reads the global at call time, so the next translation
    picks up the new template immediately.
    """
    global PROMPT_TEMPLATE
    PROMPT_TEMPLATE = load_prompt_template()
    return PROMPT_TEMPLATE

# Instruction used for very short posts, which bypass the full template.
SHORT_SYSTEM = (
    "You are a translator. Translate the user's HTML message literally from "
    "Russian to English. Preserve every HTML tag, link href, hashtag and emoji "
    "exactly. Do not add commentary and do not duplicate the original."
)


def build_messages(html_text: str) -> Tuple[str, str]:
    """Split a post into ``(system_prompt, user_text)`` for the Messages API.

    The fixed instructions/example live in the ``system`` prompt (a stable prefix
    that can be prompt-cached and is the idiomatic place for instructions), while
    the variable source post goes in the ``user`` turn. For long posts the
    operator-editable ``PROMPT_TEMPLATE`` is partitioned at its ``{message_text}``
    placeholder: everything before it becomes the system prefix, and the source
    text plus any trailing template text becomes the user turn — preserving the
    exact text order the model used to see in the single-message form.
    """
    short = len(html_text.split()) < 7 or len(html_text) < 20
    if short:
        return SHORT_SYSTEM, html_text
    before, sep, after = PROMPT_TEMPLATE.partition("{message_text}")
    if not sep:
        # Template without the placeholder: treat the whole thing as instructions.
        return PROMPT_TEMPLATE.rstrip(), html_text
    system = before.rstrip()
    user = f"{html_text}{after}"
    return system, user


async def translate_html(
    client: Union[Anthropic, AsyncAnthropic], payload: Dict[str, Any]
) -> str:
    """Send payload to Anthropic and return translated text.

    Works with either SDK client and never blocks the event loop:

    * an ``AsyncAnthropic`` (the bot path) is awaited directly — no thread;
    * a synchronous ``Anthropic`` (the Flask path, which can't share an async
      client across its per-request loops) is run via ``asyncio.to_thread``.

    The two are told apart by whether ``messages.create`` is a coroutine
    function, so test doubles work without subclassing the SDK.

    Model and params come from ``CONFIG`` so they can be changed via env vars
    without touching code (e.g. when a model is deprecated).

    The fixed prompt is sent as the ``system`` parameter with an ephemeral
    ``cache_control`` block. NOTE: Haiku's minimum cacheable prefix is 4096
    tokens, so at the current template size (~hundreds of tokens) caching is a
    no-op — the structural win (instructions in the system role) applies now, and
    caching engages automatically if the template later grows past the minimum.
    """
    system_prompt, user_text = build_messages(payload["Html"])
    create = client.messages.create
    kwargs = dict(
        model=CONFIG.ANTHROPIC_MODEL,
        max_tokens=CONFIG.ANTHROPIC_MAX_TOKENS,
        temperature=CONFIG.ANTHROPIC_TEMPERATURE,
        system=[
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_text}],
    )
    if inspect.iscoroutinefunction(create):
        resp = await create(**kwargs)
    else:
        resp = await asyncio.to_thread(create, **kwargs)
    # Claude 4+ can return stop_reason="refusal" with an EMPTY content array;
    # indexing resp.content[0] would then raise IndexError. Guard explicitly and
    # raise a non-retryable ValueError (a refusal is deterministic for the same
    # input, so run_with_retries must not burn attempts/budget on it).
    if getattr(resp, "stop_reason", None) == "refusal" or not resp.content:
        raise ValueError(
            "Anthropic returned no usable content "
            f"(stop_reason={getattr(resp, 'stop_reason', None)})"
        )
    # strip out non-HTML tags like <translation>, <example>, <source>, <user>, <instructions>, <system>
    raw = resp.content[0].text
    cleaned = re.sub(r"</?(?:translation|example|source|user|instructions|system)>", "", raw)
    return cleaned
