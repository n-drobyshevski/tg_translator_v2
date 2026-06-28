import sys
from flask import (
    Blueprint,
    request,
    render_template,
    session,
    redirect,
    url_for,
    jsonify,
)
from flask_login import login_required
import os
import requests
from translator.config import PROMPT_TEMPLATE_PATH
from translator.bot import translate_html  # use the actual translate function
from anthropic import Anthropic

admin_prompt_bp = Blueprint("admin_prompt_bp", __name__)


@admin_prompt_bp.route("/admin/prompt", methods=["GET"])
@login_required
def modify_prompt():
    current_prompt = PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")
    return render_template(
        "admin_prompt_edit.html",
        current_prompt=current_prompt,
        message="",
        active_page="config",  # Since it's part of config section
    )


@admin_prompt_bp.route("/admin/save_prompt", methods=["POST"])
@login_required
def save_prompt():
    new_prompt = request.form.get("prompt_text", "")
    if not new_prompt:
        return jsonify(error="No prompt provided"), 400
    PROMPT_TEMPLATE_PATH.write_text(new_prompt, encoding="utf-8")
    return jsonify(message="Prompt template updated successfully.")


@admin_prompt_bp.route("/admin/get_last_telegram_post", methods=["POST"])
@login_required
def get_last_telegram_post():
    api_id = int(os.getenv("TELEGRAM_API_ID") or 0)
    api_hash = os.getenv("TELEGRAM_API_HASH") or ""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")

    try:
        channel_env = os.getenv("CHRISTIANVISION_CHANNEL")
        if not channel_env:
            raise ValueError("CHRISTIANVISION_CHANNEL environment variable is not set")
        channel_id = int(channel_env)
    except Exception as e:
        sample_data = f"Invalid channel id: {e}"
        current_prompt = PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")
        return render_template(
            "admin_prompt_edit.html",
            current_prompt=current_prompt,
            message="",
            sample_data=sample_data,
        )

    try:
        url = f"https://api.telegram.org/bot{bot_token}/getUpdates?limit=1&allowed_updates=%5B%22channel_post%22%5D"
        response = requests.get(url)
        data = response.json()
        # print("Data returned by retrieve post action:", data)  # Added line
        if data.get("ok") and data.get("result"):
            updates = data.get("result")
            for update in updates:
                # Corrected logic
                post = update.get("edited_channel_post") or update.get("channel_post")
                last_post = (
                    post.get("caption")
                    or post.get("text")
                    or "No caption in last post."
                )
                break
            else:
                last_post = (
                    "No channel posts found. Ensure the bot is added as an admin to the channel "
                    "and that new channel posts are available."
                )
        else:
            last_post = "No updates found."
    except Exception as e:
        last_post = f"Error retrieving last post: {e}"

    current_prompt = PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")
    return render_template(
        "admin_prompt_edit.html",
        current_prompt=current_prompt,
        message="",
        sample_data=last_post,
    )


@admin_prompt_bp.route("/admin/test_translation", methods=["POST"])
@login_required
def test_translation():
    input_text = request.form.get("test_message", "").strip()
    if not input_text:
        translation_result = "No input provided for translation."
    else:
        try:
            anthropic_client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
            payload = {
                "Channel": "Test Channel",
                "Text": input_text,
                "Html": input_text,
                "Link": "https://example.com",
            }
            import asyncio

            translation_result = asyncio.run(
                translate_html(anthropic_client, payload)
            )
        except Exception as e:
            translation_result = f"Error during translation: {e}"

    current_prompt = PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")
    return render_template(
        "admin_prompt_edit.html",
        current_prompt=current_prompt,
        message="",
        sample_data=input_text,
        translation_result=translation_result,
    )
