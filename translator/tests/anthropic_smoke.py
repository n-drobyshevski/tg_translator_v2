"""Manual Anthropic connectivity smoke check — NOT a pytest test.

Run directly:  python translator/tests/anthropic_smoke.py

Renamed from `anthropic_test.py` so pytest's default `*_test.py` glob no longer
collects it (it previously fired a live API call at import during the suite).
The live call is now guarded behind __main__ and uses the configured model.
"""

import os
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '..', '.env'))

import requests
from translator.config import CONFIG


def main() -> None:
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": CONFIG.ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    data = {
        "model": CONFIG.ANTHROPIC_MODEL,
        "max_tokens": 10,
        "messages": [{"role": "user", "content": "Hello!"}],
    }
    response = requests.post(url, headers=headers, json=data)
    print("Status:", response.status_code)
    print("Body:", response.text)


if __name__ == "__main__":
    main()
