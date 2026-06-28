from typing import Any, Dict
from anthropic import Anthropic
import logging
import re
from translator.config import  load_prompt_template

PROMPT_TEMPLATE = load_prompt_template()

def build_prompt(html_text: str, channel: str, link: str) -> str:
    """Build translation prompt for the LLM."""
    short = len(html_text.split()) < 7 or len(html_text) < 20
    intro = (
        "Translate the following HTML message without duplicating original message:"
        if short
        else ""
    )
    body = html_text if short else PROMPT_TEMPLATE.format(message_text=html_text)
    return f"{intro}\n\n{body}".strip()

async def translate_html(client: Anthropic, payload: Dict[str, Any]) -> str:
    """Send payload to Anthropic and return translated text."""
    prompt = build_prompt(payload["Html"], payload["Channel"], payload["Link"])
    # logging.info(f"Generated prompt: {prompt}")
    resp = client.messages.create(
        model="claude-3-haiku-20240307",
        max_tokens=1500,
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
    )
    # strip out non-HTML tags like <translation>, <example>, <source>, <user>, <instructions>, <system>
    raw = resp.content[0].text
    cleaned = re.sub(r"</?(?:translation|example|source|user|instructions|system)>", "", raw)
    return cleaned
