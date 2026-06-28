import os
from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '..', '.env'))

import requests
from translator.config import CONFIG

url = "https://api.anthropic.com/v1/messages"
headers = {
    "x-api-key": CONFIG.ANTHROPIC_API_KEY,
    "anthropic-version": "2023-06-01",
    "content-type": "application/json",
}
data = {
    "model": "claude-3-haiku-20240307",  # or another available model
    "max_tokens": 10,
    "messages": [{"role": "user", "content": "Hello!"}],
}

response = requests.post(url, headers=headers, json=data)

print("Status:", response.status_code)
print("Body:", response.text)
