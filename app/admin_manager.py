import os
import re
from datetime import datetime, timezone
from flask import Blueprint, render_template, request, jsonify, session, flash, redirect, url_for, abort
import requests
import asyncio
import traceback
from flask_login import login_required
import bleach
from anthropic import Anthropic
from translator.services.event_logger import EventRecorder
from translator.config import BOT_TOKEN

admin_manager_bp = Blueprint("admin_manager_bp", __name__)


def fetch_channel_title(channel_id, bot_token=None):
    """Fetch the Telegram channel's current title via Bot API."""
    if not channel_id:
        return {"title": str(channel_id), "username": ""}
    if not bot_token:
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    url = f"https://api.telegram.org/bot{bot_token}/getChat"
    try:
        resp = requests.get(url, params={"chat_id": channel_id}, timeout=6)
        if resp.status_code == 200 and resp.json().get("ok"):
            result = resp.json()["result"]
            title = result.get("title", "") or str(channel_id)
            username = result.get("username", "")
            return {"title": title, "username": username}
    except Exception as e:
        print(f"[WARN] Could not fetch channel info for {channel_id}: {e}")
    return {"title": str(channel_id), "username": ""}


def get_available_channels():
    """Build a list of available channels with real Telegram titles."""
    ids = [
        os.getenv("CHRISTIANVISION_CHANNEL"),
        os.getenv("SHALTNOTKILL_CHANNEL"),
        os.getenv("TEST_CHANNEL"),
        os.getenv("CHRISTIANVISION_EN_CHANNEL_ID"),
        os.getenv("SHALTNOTKILL_EN_CHANNEL_ID"),
        os.getenv("TEST_EN_CHANNEL_ID"),
    ]
    ids = [i for i in ids if i]
    seen = set()
    channels = []
    for id_ in ids:
        if id_ in seen:
            continue
        seen.add(id_)
        info = fetch_channel_title(id_)
        is_en = id_ in [
            os.getenv("CHRISTIANVISION_EN_CHANNEL_ID"),
            os.getenv("SHALTNOTKILL_EN_CHANNEL_ID"),
            os.getenv("TEST_EN_CHANNEL_ID"),
        ]
        channels.append(
            {
                "name": info["title"] or id_,
                "id": id_,
                "is_en": is_en,
                "username": info["username"],
            }
        )
    return channels


def get_target_channels():
    return [
        {
            "name": fetch_channel_title(os.getenv("CHRISTIANVISION_EN_CHANNEL_ID"))[
                "title"
            ],
            "id": os.getenv("CHRISTIANVISION_EN_CHANNEL_ID"),
            "type": "christianvision",
        },
        {
            "name": fetch_channel_title(os.getenv("SHALTNOTKILL_EN_CHANNEL_ID"))[
                "title"
            ],
            "id": os.getenv("SHALTNOTKILL_EN_CHANNEL_ID"),
            "type": "shaltnotkill",
        },
        {
            "name": fetch_channel_title(os.getenv("TEST_EN_CHANNEL_ID"))["title"],
            "id": os.getenv("TEST_EN_CHANNEL_ID"),
            "type": "test",
        },
    ]


def clean_telegram_html(content: str) -> str:
    """Clean and format HTML content specifically for Telegram API.
    
    This function produces HTML that works well with the existing TelegramSender.
    It's conservative to avoid the 'B' (Bad Request) error from Telegram API.
    
    Args:
        content: Raw HTML content
        
    Returns:
        str: Cleaned content safe for Telegram
    """
    if not content:
        return ""
    
    # Pre-process: Convert strong/em to b/i before cleaning
    # This ensures they're preserved during bleach cleaning
    content = re.sub(r'<strong>(.*?)</strong>', r'<b>\1</b>', content)
    content = re.sub(r'<em>(.*?)</em>', r'<i>\1</i>', content)
    
    # Be more conservative with allowed tags to avoid API errors
    # Only use the most basic and well-supported Telegram HTML tags
    telegram_allowed_tags = ['b', 'i', 'u', 'a', 'code']
    telegram_allowed_attributes = {
        'a': ['href']
    }
    
    # Clean with bleach - this removes unsupported tags and attributes
    cleaned = bleach.clean(
        content,
        tags=telegram_allowed_tags,
        attributes=telegram_allowed_attributes,
        strip=True
    )
    
    # Convert <p> to line breaks (compatible with existing sanitize_html)
    cleaned = re.sub(r'<p[^>]*>', '', cleaned)
    cleaned = re.sub(r'</p>', '\n', cleaned)
    
    # Convert <br> variants to newlines (compatible with existing sanitize_html)
    cleaned = re.sub(r'<br[^>]*/?>', '\n', cleaned)
    
    # Remove empty tags that might cause issues
    cleaned = re.sub(r'<([a-z]+)></\1>', '', cleaned)
    cleaned = re.sub(r'<([a-z]+)\s*/>(?!</)', '', cleaned)
    
    # Remove nested identical tags to prevent API issues
    for tag in ['b', 'i', 'u', 'code']:
        pattern = f'<{tag}>(<{tag}>.*?</{tag}>)</{tag}>'
        while re.search(pattern, cleaned):
            cleaned = re.sub(pattern, r'\1', cleaned)
    
    # Clean up multiple consecutive line breaks
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    
    # Remove leading/trailing whitespace
    cleaned = cleaned.strip()
    
    # Final safety check: if cleaning resulted in empty content, use original text-only version
    if not cleaned:
        text_only = bleach.clean(content, tags=[], strip=True)
        return text_only.strip()
    
    return cleaned


def validate_message_content(message_content: str) -> tuple[bool, str]:
    """Validate message content before sending to Telegram.

    Args:
        message_content: The message content to validate

    Returns:
        tuple[bool, str]: (is_valid, error_message)
    """
    print(f"\n{'='*20} MESSAGE VALIDATION {'='*20}")
    print(f"Input content length: {len(message_content) if message_content else 0}")
    print(f"Content preview: {message_content[:100]}..." if message_content else "EMPTY")

    if not message_content:
        print("VALIDATION FAILED: Empty content")
        return False, "Message content is empty"

    # Clean the content for Telegram
    cleaned_content = clean_telegram_html(message_content)
    print(f"Cleaned content length: {len(cleaned_content)}")
    print(f"Cleaned content preview: {cleaned_content[:100]}..." if cleaned_content else "EMPTY")

    # Check if message is just whitespace after cleaning
    text_only = bleach.clean(cleaned_content, tags=[], strip=True)
    if not text_only.strip():
        print("VALIDATION FAILED: No visible text after cleaning")
        return False, "Message contains no visible text"

    # Check Telegram message length limits
    if len(cleaned_content) > 4096:
        print("VALIDATION FAILED: Message too long after cleaning")
        return False, "Message exceeds Telegram's 4096 character limit"

    # Additional Telegram-specific validations
    if cleaned_content != message_content:
        print(f"VALIDATION INFO: Content was cleaned for Telegram compatibility")
        print(f"Original length: {len(message_content)}, Cleaned length: {len(cleaned_content)}")

    # Check for problematic patterns that might cause Telegram API errors
    if re.search(r'<[^>]*[<>][^>]*>', cleaned_content):
        print("VALIDATION WARNING: Potentially malformed HTML detected")
        # Try to fix by removing the problematic tags
        cleaned_content = re.sub(r'<[^>]*[<>][^>]*>', '', cleaned_content)
        print(f"Fixed content length: {len(cleaned_content)}")

    print("VALIDATION PASSED")
    print(f"{'='*50}\n")
    return True, ""


def prepare_message_content(translation_result: str, raw_html_result: str) -> tuple[bool, str, str]:
    """Prepare and validate message content before sending.
    
    Args:
        translation_result: The translated message content
        raw_html_result: The raw HTML version of the message
        
    Returns:
        tuple[bool, str, str]: (is_valid, message_to_send, error_message)
    """
    print(f"\n{'='*20} MESSAGE PREPARATION {'='*20}")
    print(f"Translation result length: {len(translation_result) if translation_result else 0}")
    print(f"Raw HTML result length: {len(raw_html_result) if raw_html_result else 0}")
    
    # First try raw_html_result, fall back to translation_result
    message_to_send = raw_html_result or translation_result
    print(f"Selected content length: {len(message_to_send) if message_to_send else 0}")
    print(f"Content preview: {message_to_send[:100]}..." if message_to_send else "EMPTY")
    
    # Basic validation
    if not message_to_send:
        print("PREPARATION FAILED: Empty content")
        return False, "", "Message content is empty"
    
    # Clean the content for Telegram
    cleaned_message = clean_telegram_html(message_to_send)
    print(f"Cleaned message length: {len(cleaned_message)}")
    print(f"Cleaned message preview: {cleaned_message[:100]}..." if cleaned_message else "EMPTY")
    
    # Validate the cleaned content
    text_only = bleach.clean(cleaned_message, tags=[], strip=True)
    if not text_only.strip():
        print("PREPARATION FAILED: No visible text after cleaning")
        return False, "", "Message contains no visible text after cleaning"
        
    # Check Telegram message length limits
    if len(cleaned_message) > 4096:
        print("PREPARATION FAILED: Message too long after cleaning")
        return False, "", "Message exceeds Telegram's 4096 character limit"
        
    print("PREPARATION PASSED")
    print(f"Using cleaned message: {cleaned_message != message_to_send}")
    print(f"{'='*50}\n")
    return True, cleaned_message, ""


def select_message_to_send(translation_result: str, raw_html_result: str) -> tuple[bool, str, str]:
    """Select the appropriate message content to send, prioritizing translated content.
    
    Args:
        translation_result: The translated message content (primary source)
        raw_html_result: The sanitized HTML version (fallback)
        
    Returns:
        tuple[bool, str, str]: (is_valid, message_to_send, error_message)
    """
    print(f"\n{'='*20} MESSAGE SELECTION {'='*20}")
    
    # Log both versions for debugging
    print("Translation Result:")
    print(f"  Length: {len(translation_result) if translation_result else 0}")
    print(f"  Preview: {translation_result[:100]}..." if translation_result else "EMPTY")
    print(f"  Has HTML: {'<' in translation_result and '>' in translation_result if translation_result else False}")
    
    print("\nRaw HTML Result:")
    print(f"  Length: {len(raw_html_result) if raw_html_result else 0}")
    print(f"  Preview: {raw_html_result[:100]}..." if raw_html_result else "EMPTY")
    print(f"  Has HTML: {'<' in raw_html_result and '>' in raw_html_result if raw_html_result else False}")
    
    # First try translation_result, fall back to raw_html_result
    message_to_send = translation_result or raw_html_result
    
    if not message_to_send:
        print("SELECTION FAILED: No content available")
        return False, "", "No translated content available"
    
    # Clean the message for Telegram
    cleaned_message = clean_telegram_html(message_to_send)
    
    # Make sure we're not sending the source message
    if message_to_send == raw_html_result and translation_result:
        print("WARNING: Using raw_html_result when translation_result is available")
    
    print(f"\nSelected Message:")
    print(f"  Length: {len(cleaned_message)}")
    print(f"  Preview: {cleaned_message[:100]}...")
    print(f"  Source: {'translation_result' if message_to_send == translation_result else 'raw_html_result'}")
    print(f"  Has HTML: {'<' in cleaned_message and '>' in cleaned_message}")
    print(f"  Was cleaned: {cleaned_message != message_to_send}")
    
    if '<' in cleaned_message and '>' in cleaned_message:
        tags = re.findall(r'</?([a-zA-Z0-9]+)[^>]*>', cleaned_message)
        print(f"  HTML tags: {list(set(tags))}")
    
    print(f"{'='*50}\n")
    return True, cleaned_message, ""


@admin_manager_bp.route("/admin/manager", methods=["GET", "POST"])
@login_required
def channel_translate():
    channels = get_available_channels()
    target_channels = get_target_channels()
    selected_channel_id = (
        request.form.get("source_channel") if request.method == "POST" else None
    )
    selected_message_id = (
        request.form.get("message_id") if request.method == "POST" else None
    )
    selected_target_type = (
        request.form.get("target_channel") if request.method == "POST" else None
    )
    action = request.form.get("action") if request.method == "POST" else None
    selected_target_channel_id = (
        request.form.get("target_channel_id") if request.method == "POST" else None
    )

    # Extract translation results from form for post action
    form_translation_result = (
        request.form.get("translation_result") if request.method == "POST" else None
    )
    form_raw_html_result = (
        request.form.get("raw_html_result") if request.method == "POST" else None
    )

    translation_result = ""
    raw_html_result = ""
    rendered_html_result = ""
    post_result = ""
    delete_result = ""
    recent_messages = []
    selected_message_text = ""

    # Check if selected channel is English
    selected_channel_is_en = False
    for ch in channels:
        if ch["id"] == selected_channel_id:
            selected_channel_is_en = ch.get("is_en", False)
            break

    # NEW: custom message state
    message_option = request.form.get("message_option")
    custom_message_text = request.form.get("custom_message_text", "")
    
    # DEBUG: Log all form data for custom message debugging
    if message_option == "custom" or action == "translate_custom":
        print(f"\n{'='*20} CUSTOM MESSAGE DEBUG {'='*20}")
        print(f"message_option: '{message_option}'")
        print(f"action: '{action}'")
        print(f"custom_message_text length: {len(custom_message_text)}")
        print(f"custom_message_text content: {custom_message_text[:200]}..." if custom_message_text else "EMPTY")
        print(f"selected_channel_id: {selected_channel_id}")
        print(f"All form data:")
        for key, value in request.form.items():
            if len(str(value)) > 100:
                print(f"  {key}: [LENGTH:{len(str(value))}] {str(value)[:100]}...")
            else:
                print(f"  {key}: {value}")
        print(f"{'='*50}")

    recorder = EventRecorder()

    # To fetch recent messages for a channel, filter from event_recorder.stats
    def get_recent_messages(channel_id):
        from datetime import datetime

        msgs = [
            m for m in recorder.stats.get("messages", [])
            if str(m.get("source_channel_id")) == str(channel_id)
        ]
        # Sort by timestamp descending
        msgs = sorted(msgs, key=lambda m: m.get("timestamp", ""), reverse=True)
        
        print(f"\n{'='*20} GET_RECENT_MESSAGES DEBUG {'='*20}")
        print(f"Channel ID: {channel_id}")
        print(f"Total messages in recorder: {len(recorder.stats.get('messages', []))}")
        print(f"Filtered messages for channel: {len(msgs)}")
        
        # Group messages by message_id and keep the best one (with content and successful posting)
        message_groups = {}
        for m in msgs:
            msg_id = m.get("message_id")
            if msg_id not in message_groups:
                message_groups[msg_id] = []
            message_groups[msg_id].append(m)
        
        result = []
        for msg_id, msg_group in message_groups.items():
            print(f"Message ID {msg_id}: {len(msg_group)} entries")
            
            # Find the best entry: prioritize ones with content and successful posting
            best_msg = None
            for m in msg_group:
                source_content = m.get("source_message", "")
                is_successful = m.get("posting_success", False)
                
                print(f"  Entry: content_len={len(source_content)}, success={is_successful}")
                
                if not best_msg:
                    best_msg = mbest_msg = m
                elif len(source_content) > len(best_msg.get("source_message", "")) and is_successful:
                    # Better entry: has more content and is successful
                    best_msg = m
                elif len(source_content) > 0 and len(best_msg.get("source_message", "")) == 0:
                    # Better entry: has content when best doesn't
                    best_msg = m
            
            if best_msg:
                html_content = best_msg.get("source_message", "")
                
                print(f"  Selected best entry: content_len={len(html_content)}")
                if html_content:
                    print(f"  Content preview: '{html_content[:100]}...'")
                else:
                    print(f"  No content found for message {msg_id}")
                
                result.append({
                    "id": msg_id,
                    "html": html_content,
                    "timestamp": datetime.fromisoformat(best_msg.get("timestamp")) if best_msg.get("timestamp") else None,
                    "chat_title": best_msg.get("source_channel_name", ""),
                    "chat_username": best_msg.get("source_channel_username", ""),
                })
        
        # Sort by timestamp descending
        result = sorted(result, key=lambda x: x["timestamp"] or datetime.min, reverse=True)
        
        print(f"Returning {len(result)} unique messages")
        print(f"{'='*50}")
        return result

    # Step 1: Select channel and fetch recent messages
    if (
        selected_channel_id
        and not selected_message_id
        and not (message_option == "custom" and action == "translate_custom")
    ):
        recent_messages = get_recent_messages(selected_channel_id)

    # ---- CUSTOM MESSAGE HANDLING ----
    print(f"\n{'='*20} CUSTOM MESSAGE CONDITION CHECK {'='*20}")
    print(f"selected_channel_id: {bool(selected_channel_id)} ({selected_channel_id})")
    print(f"message_option == 'custom': {message_option == 'custom'} ({message_option})")
    print(f"action == 'translate_custom': {action == 'translate_custom'} ({action})")
    print(f"custom_message_text not empty: {bool(custom_message_text)} (length: {len(custom_message_text)})")
    
    custom_conditions_met = (
        selected_channel_id
        and message_option == "custom"
        and action == "translate_custom"
        and custom_message_text
    )
    print(f"All custom conditions met: {custom_conditions_met}")
    print(f"{'='*50}")
    
    if custom_conditions_met:
        selected_message_text = custom_message_text.strip()
        selected_message_id = None
        chat_title = ""
        chat_username = ""
        for ch in channels:
            if selected_channel_id == ch["id"]:
                chat_title = ch.get("name", "")
                chat_username = ch.get("username", "")
                break
        
        print(f"\n{'='*20} CUSTOM MESSAGE TRANSLATION CONDITIONS {'='*20}")
        print(f"selected_channel_is_en: {selected_channel_is_en}")
        print(f"selected_message_text: {bool(selected_message_text)} (length: {len(selected_message_text)})")
        print(f"chat_title: {chat_title}")
        print(f"chat_username: {chat_username}")
        print(f"{'='*50}")
        
        if not selected_channel_is_en and selected_message_text:
            print(f"\n{'='*20} CUSTOM TRANSLATION ATTEMPT {'='*20}")
            print(f"Selected message text length: {len(selected_message_text)}")
            print(f"Selected message preview: {selected_message_text[:200]}...")
            print(f"Channel is English: {selected_channel_is_en}")
            print(f"Chat title: {chat_title}")
            print(f"Chat username: {chat_username}")
            
            try:
                from translator.bot import translate_html

                if chat_username:
                    source_channel_link = (
                        f'<a href="https://t.me/{chat_username}">{chat_title}</a>'
                    )
                    html_with_source = f"{selected_message_text}\n\nSource channel: {source_channel_link}"
                else:
                    html_with_source = (
                        f"{selected_message_text}\n\nSource channel: {chat_title}"
                    )
                
                payload = {
                    "Channel": chat_title,
                    "Text": selected_message_text,
                    "Html": html_with_source,
                    "Link": f"https://t.me/{chat_title}/0",
                    "Meta": {},
                }
                
                print(f"Payload created:")
                print(f"  Channel: {payload['Channel']}")
                print(f"  Text length: {len(payload['Text'])}")
                print(f"  Html length: {len(payload['Html'])}")
                print(f"  Link: {payload['Link']}")
                
                # Check API key
                api_key = os.getenv("ANTHROPIC_API_KEY", "")
                print(f"API key present: {bool(api_key)}")
                print(f"API key length: {len(api_key) if api_key else 0}")
                print(f"API key starts with: {api_key[:10]}..." if api_key else "NO KEY")
                
                anthropic_client = Anthropic(api_key=api_key)
                print("Anthropic client created successfully")
                
                print("Calling translate_html...")
                translation_result = asyncio.run(
                    translate_html(anthropic_client, payload)
                )
                print(f"Translation completed. Result length: {len(translation_result) if translation_result else 0}")
                print(f"Translation preview: {translation_result[:200]}..." if translation_result else "EMPTY")
                
                import re
                translation_result = re.sub(r"(</[a-z]+>)+$", "", translation_result)
                raw_html_result = clean_telegram_html(translation_result)
                rendered_html_result = translation_result
                
                print(f"Final results:")
                print(f"  translation_result length: {len(translation_result) if translation_result else 0}")
                print(f"  raw_html_result length: {len(raw_html_result) if raw_html_result else 0}")
                print(f"  rendered_html_result length: {len(rendered_html_result) if rendered_html_result else 0}")
                print(f"{'='*50}")
                
            except Exception as e:
                print(f"CUSTOM TRANSLATION ERROR: {e}")
                print(f"Error type: {type(e)}")
                print(f"Traceback: {traceback.format_exc()}")
                translation_result = f"Error during translation: {e}"
                raw_html_result = clean_telegram_html(translation_result)
                rendered_html_result = translation_result
                print(f"Set error results, translation_result: {translation_result}")
        else:
            print(f"\n{'='*20} CUSTOM TRANSLATION SKIPPED {'='*20}")
            print(f"Channel is English: {selected_channel_is_en}")
            print(f"Selected message text present: {bool(selected_message_text)}")
            print(f"Reason: {'Channel is English' if selected_channel_is_en else 'No message text'}")
            print(f"{'='*50}")
        recent_messages = get_recent_messages(selected_channel_id)
    else:
        print(f"\n{'='*20} CUSTOM MESSAGE HANDLING SKIPPED {'='*20}")
        print(f"Reason: Custom conditions not met")
        print(f"{'='*50}")

    # ---- EXISTING MESSAGE HANDLING ----
    if (
        selected_channel_id
        and selected_message_id
        and (not message_option or message_option == "existing")
    ):
        if action == "delete":
            try:
                print(
                    f"[ADMIN] Attempting to delete message {selected_message_id} from channel {selected_channel_id}"
                )
                url = f"https://api.telegram.org/bot{BOT_TOKEN}/deleteMessage"
                resp = requests.post(
                    url,
                    data={
                        "chat_id": selected_channel_id,
                        "message_id": selected_message_id,
                    },
                )
                if resp.status_code == 200 and resp.json().get("ok"):
                    delete_result = "Message deleted successfully."
                    # Remove from event log
                    recorder.stats["messages"] = [
                        m for m in recorder.stats["messages"]
                        if str(m.get("message_id")) != str(selected_message_id)
                    ]
                    recorder.finalize()
                else:
                    delete_result = f"Failed to delete message: {resp.text}"
            except Exception as e:
                delete_result = f"Error deleting message: {e}"
            recent_messages = get_recent_messages(selected_channel_id)
            return render_template(
                "admin_manager.html",
                channels=channels,
                target_channels=target_channels,
                selected_channel_id=selected_channel_id,
                recent_messages=recent_messages,
                selected_message_id=None,
                selected_message_text="",
                translation_result="",
                raw_html_result="",
                rendered_html_result="",
                post_result=post_result,
                selected_target_type=selected_target_type,
                delete_result=delete_result,
                selected_channel_is_en=selected_channel_is_en,
                custom_message_text=custom_message_text,
                message_option=message_option,
                active_page="manager",
            )

        recent_messages = get_recent_messages(selected_channel_id)
        selected_message_text = ""
        chat_title = ""
        chat_username = ""
        
        print(f"\n{'='*20} MESSAGE LOOKUP DEBUG {'='*20}")
        print(f"Looking for message ID: {selected_message_id}")
        print(f"Recent messages count: {len(recent_messages)}")
        
        for i, msg in enumerate(recent_messages):
            print(f"Message {i}:")
            print(f"  id: {msg.get('id')}")
            print(f"  html length: {len(msg.get('html', ''))}")
            print(f"  html preview: {msg.get('html', '')[:100]}...")
            print(f"  timestamp: {msg.get('timestamp')}")
            print(f"  Match: {str(msg.get('id')) == str(selected_message_id)}")
            
            if str(msg.get("id")) == str(selected_message_id):
                selected_message_text = msg.get("html", "")
                chat_title = msg.get("chat_title", "")
                chat_username = msg.get("chat_username", "")
                print(f"  FOUND MATCH!")
                print(f"  Selected text length: {len(selected_message_text)}")
                print(f"  Chat title: {chat_title}")
                print(f"  Chat username: {chat_username}")
                break
        
        print(f"Final selected_message_text length: {len(selected_message_text)}")
        
        # If we found the message ID but no content, this shouldn't happen with the improved lookup
        if not selected_message_text and selected_message_id:
            print(f"\n{'='*20} NO CONTENT FOUND {'='*20}")
            print(f"Warning: No content found for message {selected_message_id}")
            print(f"This indicates a data issue - the message exists but has no source content")
            print(f"Channel ID: {selected_channel_id}")
            print(f"{'='*50}")
        
        print(f"{'='*50}")

        edited_source = (
            request.form.get("edited_source") if request.method == "POST" else None
        )
        if edited_source:
            selected_message_text = edited_source

        if (
            selected_message_text
            and not selected_channel_is_en
            and action in ["translate", "save-translate"]
        ):
            print(f"\n{'='*20} TRANSLATION ATTEMPT {'='*20}")
            print(f"Selected message text length: {len(selected_message_text)}")
            print(f"Selected message preview: {selected_message_text[:200]}...")
            print(f"Channel is English: {selected_channel_is_en}")
            print(f"Action: {action}")
            print(f"Chat title: {chat_title}")
            print(f"Chat username: {chat_username}")
            
            try:
                from translator.bot import translate_html

                if chat_username:
                    source_channel_link = (
                        f'<a href="https://t.me/{chat_username}">{chat_title}</a>'
                    )
                    html_with_source = f"{selected_message_text}\n\nSource channel: {source_channel_link}"
                else:
                    html_with_source = (
                        f"{selected_message_text}\n\nSource channel: {chat_title}"
                    )
                
                payload = {
                    "Channel": chat_title,
                    "Text": selected_message_text,
                    "Html": html_with_source,
                    "Link": f"https://t.me/{chat_title}/{selected_message_id}",
                    "Meta": {},
                }
                
                print(f"Payload created:")
                print(f"  Channel: {payload['Channel']}")
                print(f"  Text length: {len(payload['Text'])}")
                print(f"  Html length: {len(payload['Html'])}")
                print(f"  Link: {payload['Link']}")
                
                # Check API key
                api_key = os.getenv("ANTHROPIC_API_KEY", "")
                print(f"API key present: {bool(api_key)}")
                print(f"API key length: {len(api_key) if api_key else 0}")
                print(f"API key starts with: {api_key[:10]}..." if api_key else "NO KEY")
                
                anthropic_client = Anthropic(api_key=api_key)
                print("Anthropic client created successfully")
                
                print("Calling translate_html...")
                translation_result = asyncio.run(
                    translate_html(anthropic_client, payload)
                )
                print(f"Translation completed. Result length: {len(translation_result) if translation_result else 0}")
                print(f"Translation preview: {translation_result[:200]}..." if translation_result else "EMPTY")
                
                import re
                translation_result = re.sub(r"(</[a-z]+>)+$", "", translation_result)
                raw_html_result = clean_telegram_html(translation_result)
                rendered_html_result = translation_result
                
                print(f"Final results:")
                print(f"  translation_result length: {len(translation_result) if translation_result else 0}")
                print(f"  raw_html_result length: {len(raw_html_result) if raw_html_result else 0}")
                print(f"  rendered_html_result length: {len(rendered_html_result) if rendered_html_result else 0}")
                print(f"{'='*50}")
                
            except Exception as e:
                print(f"TRANSLATION ERROR: {e}")
                print(f"Error type: {type(e)}")
                print(f"Traceback: {traceback.format_exc()}")
                translation_result = f"Error during translation: {e}"
                raw_html_result = clean_telegram_html(translation_result)
                rendered_html_result = translation_result
                print(f"Set error results, translation_result: {translation_result}")
        else:
            print(f"\n{'='*20} TRANSLATION SKIPPED {'='*20}")
            print(f"Selected message text present: {bool(selected_message_text)}")
            print(f"Channel is English: {selected_channel_is_en}")
            print(f"Action: {action}")
            print(f"Action in translate/save-translate: {action in ['translate', 'save-translate']}")
            print(f"{'='*50}")

        recent_messages = get_recent_messages(selected_channel_id)

    # Step 3: Post to target channel if requested
    if action == "post":
        print(f"\n{'='*20} POST ACTION START {'='*20}")
        print(f"selected_target_type: '{selected_target_type}'")
        print(f"selected_target_channel_id: '{selected_target_channel_id}'")
        print(f"form_translation_result available: {bool(form_translation_result)}")
        print(f"form_raw_html_result available: {bool(form_raw_html_result)}")
        print(f"{'='*50}")
        
        try:
            from translator.services.telegram_sender import TelegramSender

            sender = TelegramSender()
            if not selected_target_type:
                print(f"[ERROR] Post failed: Target channel not found")
                post_result = {"success": False, "message": "Error posting: Target channel not found."}
            else:
                print(f"\n{'='*20} POST ACTION DEBUG {'='*20}")
                print(f"Form translation_result length: {len(form_translation_result) if form_translation_result else 0}")
                print(f"Form raw_html_result length: {len(form_raw_html_result) if form_raw_html_result else 0}")
                print(f"Form translation_result preview: {form_translation_result[:100]}..." if form_translation_result else "EMPTY")
                print(f"Form raw_html_result preview: {form_raw_html_result[:100]}..." if form_raw_html_result else "EMPTY")
                
                # Select the translated message to send (handle None values)
                is_valid, message_to_send, error_message = select_message_to_send(
                    form_translation_result or "", 
                    form_raw_html_result or ""
                )
                if not is_valid:
                    print(f"[ERROR] Message selection failed: {error_message}")
                    return jsonify({
                        "post_result": {
                            "success": False,
                            "message": f"Error posting: {error_message}",
                            "code": "SELECTION_ERROR",
                            "suggestion": "Please ensure the message was translated successfully."
                        }
                    })
                
                # Additional validation of the selected message
                is_valid, error_message = validate_message_content(message_to_send)
                if not is_valid:
                    print(f"[ERROR] Message validation failed: {error_message}")
                    return jsonify({
                        "post_result": {
                            "success": False,
                            "message": f"Error posting: {error_message}",
                            "code": "VALIDATION_ERROR",
                            "suggestion": "Please ensure your message contains valid content."
                        }
                    })

                edit_mode = request.form.get("edit_mode")
                if edit_mode:
                    # Find the message to edit in the event log
                    msg_id = None
                    for m in recorder.stats["messages"]:
                        if (
                            str(m.get("source_channel_id")) == str(selected_channel_id)
                            and str(m.get("source_message_id")) == str(selected_message_id)
                        ):
                            msg_id = m.get("message_id")
                            break
                    if msg_id:
                        ok = sender.edit_message(
                            selected_target_channel_id, msg_id, message_to_send, recorder
                        )
                        post_result = (
                            "Edited matching message."
                            if ok
                            else "Failed to edit message."
                        )
                    else:
                        post_result = "No matching message to edit in target channel."
                else:
                    print(f"\n{'='*20} ATTEMPTING TO SEND MESSAGE {'='*20}")
                    print(f"Target channel: {selected_target_channel_id}")
                    print(f"Message length: {len(message_to_send)}")
                    print(f"Message preview: {message_to_send[:200]}...")
                    
                    # Clear any previous recorder state for this send
                    recorder.set(
                        dest_channel_name=selected_target_type,
                        dest_channel_id=selected_target_channel_id,
                        api_error_code=None,
                        exception_message=None,
                        posting_success=False
                    )
                    
                    ok = asyncio.run(
                        sender.send_message(message_to_send, recorder)
                    )
                    
                    print(f"Send result: {ok}")
                    
                    # Get detailed error information from the recorder
                    api_error = recorder.get("api_error_code")[0] if recorder.get("api_error_code") else None
                    exception_msg = recorder.get("exception_message")[0] if recorder.get("exception_message") else None
                    
                    print(f"API error code: {api_error}")
                    print(f"Exception message: {exception_msg}")
                    print(f"{'='*50}")
                    
                    if ok:
                        post_result = "Posted successfully."
                        # Log the event
                        target_obj = next(
                            (
                                ch
                                for ch in target_channels
                                if ch["type"] == selected_target_type
                            ),
                            {},
                        )
                        msg_id = getattr(sender, "last_message_id", None)
                        recorder.set(
                            event_type="create",
                            source_channel=selected_channel_id,
                            dest_channel=selected_target_channel_id,
                            original_size=len(message_to_send),
                            translated_size=len(message_to_send),
                            translation_time=0,
                            posting_success=True,
                            message_id=msg_id,
                            source_channel_name=chat_title,
                            dest_channel_name=target_obj.get("name", ""),
                            source_message=message_to_send,
                            translated_message=message_to_send,
                        )
                    else:
                        # Create detailed error message
                        error_details = f"Failed to post message"
                        if exception_msg:
                            error_details += f": {exception_msg}"
                        if api_error:
                            error_details += f" (API Error: {api_error})"
                        
                        post_result = {
                            "success": False, 
                            "message": error_details,
                            "code": f"TELEGRAM_API_ERROR_{api_error}" if api_error else "TELEGRAM_SEND_FAILED",
                            "suggestion": "Check bot permissions, channel ID, and message format"
                        }
        except Exception as e:
            print(f"\n{'='*20} POST EXCEPTION {'='*20}")
            print(f"Exception type: {type(e)}")
            print(f"Exception message: {str(e)}")
            print(f"Traceback: {traceback.format_exc()}")
            
            # Get any recorder error information
            api_error = recorder.get("api_error_code")[0] if recorder.get("api_error_code") else None
            exception_msg = recorder.get("exception_message")[0] if recorder.get("exception_message") else None
            
            error_details = f"Exception during posting: {str(e)}"
            if exception_msg and exception_msg != str(e):
                error_details += f" | Telegram error: {exception_msg}"
            if api_error:
                error_details += f" | API Error: {api_error}"
                
            print(f"Detailed error: {error_details}")
            print(f"{'='*50}")
            
            post_result = {
                "success": False,
                "message": error_details,
                "code": f"TELEGRAM_API_ERROR_{api_error}" if api_error else "POST_EXCEPTION",
                "suggestion": "Check bot configuration, API token, and channel permissions"
            }

    # Debug what we're returning to the template
    print(f"\n{'='*20} RETURNING TO TEMPLATE {'='*20}")
    print(f"translation_result: {translation_result[:200] if translation_result else 'EMPTY'}...")
    print(f"raw_html_result: {raw_html_result[:200] if raw_html_result else 'EMPTY'}...")
    print(f"rendered_html_result: {rendered_html_result[:200] if rendered_html_result else 'EMPTY'}...")
    print(f"translation_result length: {len(translation_result) if translation_result else 0}")
    print(f"raw_html_result length: {len(raw_html_result) if raw_html_result else 0}")
    print(f"action: {action}")
    print(f"selected_message_id: {selected_message_id}")
    print(f"selected_channel_id: {selected_channel_id}")
    print(f"{'='*50}")

    return render_template(
        "admin_manager.html",
        channels=channels,
        target_channels=target_channels,
        selected_channel_id=selected_channel_id,
        recent_messages=recent_messages,
        selected_message_id=selected_message_id,
        selected_message_text=selected_message_text,
        translation_result=translation_result,
        raw_html_result=raw_html_result,
        rendered_html_result=rendered_html_result,
        post_result=post_result,
        selected_target_type=selected_target_type,
        delete_result=delete_result,
        selected_channel_is_en=selected_channel_is_en,
        custom_message_text=custom_message_text,
        message_option=message_option,
        active_page="manager",
    )


def log_recorder_message(m: dict, action: str, **extra_info):
    """Helper to log message details from the event recorder"""
    log_data = {
        "action": action,
        "message_id": m.get("message_id"),
        "source_channel_id": m.get("source_channel_id"),
        "source_message_id": m.get("source_message_id"),
        "posting_success": m.get("posting_success"),
        "event_type": m.get("event_type"),
        "original_size": m.get("original_size"),
        "translated_size": m.get("translated_size"),
        "translation_time": m.get("translation_time"),
        "source_channel_name": m.get("source_channel_name"),
        "dest_channel_name": m.get("dest_channel_name"),
        "timestamp": m.get("timestamp"),
        **extra_info
    }
    print(f"\n{'='*20} EVENT RECORDER MESSAGE {'='*20}")
    for key, value in log_data.items():
        if isinstance(value, str) and len(value) > 100:
            print(f"{key}:")
            print(f"  Length: {len(value)}")
            print(f"  Preview: {value[:100]}...")
        else:
            print(f"{key}: {value}")
    print(f"{'='*50}\n")


def log_message_state(prefix: str, **kwargs):
    """Helper function to log message state with consistent formatting"""
    now = datetime.now(timezone.utc).isoformat()
    print(f"\n{'='*20} {prefix} @ {now} {'='*20}")
    for key, value in kwargs.items():
        if isinstance(value, str) and len(value) > 100:
            print(f"{key}:")
            print(f"  Length: {len(value)}")
            print(f"  Preview: {value[:100]}...")
            print(f"  Has HTML: {'<' in value and '>' in value}")
            # Log HTML tag information if present
            if '<' in value and '>' in value:
                tags = re.findall(r'</?([a-zA-Z0-9]+)[^>]*>', value)
                print(f"  HTML tags: {list(set(tags))}")
        elif isinstance(value, (list, dict)):
            print(f"{key}:")
            print(f"  Type: {type(value)}")
            print(f"  Length/Size: {len(value)}")
            print(f"  Preview: {str(value)[:200]}...")
        else:
            print(f"{key}: {value}")
    print(f"{'='*50}\n")


async def get_error_details(error, context=None):
    """Get detailed error information in a structured format"""
    error_info = {
        'code': 'POST-ERR-000',
        'message': str(error) if error else 'Unknown error occurred',
        'details': None,
        'severity': 'error',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'suggestions': [],
        'context': context
    }

    if isinstance(error, Exception):
        error_str = str(error).lower()
        error_info['traceback'] = traceback.format_exc() if error else None
        
        # Common Telegram API errors
        if 'flood' in error_str:
            error_info.update({
                'code': 'POST-ERR-001',
                'message': 'Rate limit exceeded',
                'severity': 'warning',
                'details': 'The channel has temporarily restricted message posting',
                'suggestions': [
                    'Wait a few minutes before retrying',
                    'Consider spacing out your posts'
                ]
            })
        elif 'not found' in error_str:
            error_info.update({
                'code': 'POST-ERR-002',
                'message': 'Channel or message not found',
                'severity': 'error',
                'suggestions': [
                    'Verify the channel exists and is accessible',
                    'Check if you have posting permissions',
                    'Ensure the message ID is valid'
                ]
            })
        elif 'permission' in error_str:
            error_info.update({
                'code': 'POST-ERR-003',
                'message': 'Insufficient permissions',
                'severity': 'error',
                'suggestions': [
                    'Verify bot admin status in the channel',
                    'Check channel posting permissions'
                ]
            })
        elif 'message to edit not found' in error_str:
            error_info.update({
                'code': 'POST-ERR-004',
                'message': 'Message to edit not found',
                'severity': 'error',
                'suggestions': [
                    'Verify the message still exists',
                    'Check if the message was already deleted',
                    'Confirm the message ID is correct'
                ]
            })
        elif 'message is not modified' in error_str:
            error_info.update({
                'code': 'POST-ERR-005',
                'message': 'No changes in message content',
                'severity': 'warning',
                'suggestions': [
                    'Make sure the content is different from the existing message',
                    'Try editing again with different content'
                ]
            })
        elif 'bad request' in error_str:
            error_info.update({
                'code': 'POST-ERR-006',
                'message': 'Invalid request format',
                'severity': 'error',
                'details': str(error),
                'suggestions': [
                    'Check message formatting and length',
                    'Ensure all required parameters are provided',
                    'Verify HTML formatting is valid'
                ]
            })
        
        # Log the error details
        log_message_state("ERROR DETAILS", 
            error_code=error_info['code'],
            error_message=error_info['message'],
            severity=error_info['severity'],
            details=error_info['details'],
            suggestions=error_info['suggestions'],
            context=context,
            traceback=error_info['traceback']
        )

    return error_info


@admin_manager_bp.route("/post_translation", methods=["POST"])
@login_required
async def post_translation():
    """Handle post translation requests with detailed logging"""
    # Log all form data
    form_data = {}
    # Convert form data to dict and handle special fields
    for key, value in request.form.items():
        if key in ["translation_result", "raw_html_result"]:
            form_data[f"{key}_length"] = str(len(value))
            form_data[key] = value[:100] + "..." if value else ""
        else:
            form_data[key] = value
    
    log_message_state("INCOMING REQUEST DATA", **form_data)

    # Initialize recorder early to track all events
    from translator.services.event_logger import EventRecorder
    recorder = EventRecorder()
    
    # Log current event recorder state
    log_message_state("INITIAL EVENT RECORDER STATE",
        message_count=len(recorder.stats.get("messages", [])),
        stats=recorder.stats
    )

    # Get message content and validate early
    translation_result = request.form.get("translation_result", "").strip()
    raw_html_result = request.form.get("raw_html_result", "").strip()
    
    log_message_state("MESSAGE CONTENT STATE",
        translation_result_empty=not bool(translation_result),
        raw_html_result_empty=not bool(raw_html_result),
        translation_length=len(translation_result),
        raw_html_length=len(raw_html_result),
        translation_preview=translation_result[:100] if translation_result else None,
        raw_html_preview=raw_html_result[:100] if raw_html_result else None
    )

    # Early validation of message content
    is_valid, message_to_send, error_message = prepare_message_content(
        translation_result, raw_html_result
    )
    
    log_message_state("VALIDATION RESULT",
        is_valid=is_valid,
        error_message=error_message,
        message_length=len(message_to_send) if message_to_send else 0,
        message_preview=message_to_send[:100] if message_to_send else None
    )

    if not is_valid:
        log_message_state("VALIDATION FAILED", error=error_message)
        return jsonify({
            "post_result": {
                "success": False,
                "message": f"Error posting: {error_message}",
                "code": "VALIDATION_ERROR",
                "suggestion": "Please ensure your message contains valid content and try translating again."
            }
        })

    action = request.form.get("action")
    if action == "post":
        try:
            from translator.services.telegram_sender import TelegramSender
            
            sender = TelegramSender()
            selected_target_type = request.form.get("target_channel")
            selected_target_channel_id = request.form.get("target_channel_id")
            edit_mode = request.form.get("edit_mode")
            selected_channel_id = request.form.get("source_channel")
            selected_message_id = request.form.get("message_id")

            log_message_state("SENDING CONFIGURATION",
                target_type=selected_target_type,
                target_channel_id=selected_target_channel_id,
                edit_mode=edit_mode,
                source_channel_id=selected_channel_id,
                message_id=selected_message_id
            )

            if edit_mode:
                msg_id = None
                # Log all messages in recorder for debugging
                log_message_state("EVENT RECORDER MESSAGES",
                    messages=recorder.stats.get("messages", [])
                )
                
                for m in recorder.stats.get("messages", []):
                    log_message_state("CHECKING MESSAGE MATCH",
                        recorder_message=m,
                        source_channel_match=str(m.get("source_channel_id")) == str(selected_channel_id),
                        message_id_match=str(m.get("source_message_id")) == str(selected_message_id)
                    )
                    
                    if (str(m.get("source_channel_id")) == str(selected_channel_id) 
                        and str(m.get("source_message_id")) == str(selected_message_id)):
                        msg_id = m.get("message_id")
                        break
                
                if msg_id:
                    log_message_state("EDITING MESSAGE",
                        target_channel=selected_target_channel_id,
                        message_id=msg_id,
                        content_length=len(message_to_send)
                    )
                    
                    ok = sender.edit_message(
                        selected_target_channel_id, msg_id, message_to_send, recorder
                    )
                    
                    log_message_state("EDIT RESULT",
                        success=ok,
                        updated_stats=recorder.stats
                    )
                    
                    if ok:
                        post_result = {"success": True, "message": "Message edited successfully."}
                    else:
                        error_info = await get_error_details(None)
                        log_message_state("EDIT FAILED", error_info=error_info)
                        post_result = {
                            "success": False,
                            "message": "Failed to edit message.",
                            "error": error_info
                        }
                else:
                    log_message_state("NO MATCHING MESSAGE FOUND",
                        source_channel_id=selected_channel_id,
                        message_id=selected_message_id
                    )
                    post_result = {
                        "success": False,
                        "message": "No matching message to edit in target channel."
                    }
            else:
                log_message_state("SENDING NEW MESSAGE",
                    content_length=len(message_to_send),
                    target_channel=selected_target_channel_id
                )
                
                ok = asyncio.run(sender.send_message(message_to_send, recorder))
                
                log_message_state("SEND RESULT",
                    success=ok,
                    updated_stats=recorder.stats
                )
                
                if ok:
                    post_result = {"success": True, "message": "Posted successfully."}
                else:
                    message_context = {
                        "target_channel_id": selected_target_channel_id,
                        "message_content": message_to_send,
                        "source_channel_id": selected_channel_id,
                        "message_id": selected_message_id
                    }
                    error_info = await get_error_details(None, context=message_context)
                    log_message_state("SEND FAILED", error_info=error_info)
                    post_result = {
                        "success": False,
                        "message": "Failed to post.",
                        "error": error_info
                    }

        except Exception as e:
            error_info = await get_error_details(e)
            log_message_state("EXCEPTION", 
                error=str(e),
                error_info=error_info,
                traceback=traceback.format_exc()
            )
            post_result = {
                "success": False,
                "message": "Failed to post.",
                "error": error_info
            }

        # Log final state before returning
        log_message_state("FINAL STATE",
            post_result=post_result,
            final_stats=recorder.stats
        )
        
        return jsonify({"post_result": post_result})

    # Return empty success response for non-post actions
    return jsonify({"post_result": {"success": True}})


async def edit_message(recorder: EventRecorder, edit_context: dict):
    """Handle message editing with detailed logging"""
    try:
        from translator.services.telegram_sender import TelegramSender
        sender = TelegramSender()
        msg_id = None
        
        # Log all messages for debugging
        log_message_state("EDIT - SEARCHING MESSAGES",
            message_count=len(recorder.stats.get("messages", [])),
            source_channel=edit_context['source_channel_id'],
            message_id=edit_context['message_id']
        )
        
        # Check each recorder message for a match
        for m in recorder.stats.get("messages", []):
            log_recorder_message(m, "EDIT - CHECKING MATCH",
                source_match=str(m.get("source_channel_id")) == str(edit_context['source_channel_id']),
                id_match=str(m.get("source_message_id")) == str(edit_context['message_id'])
            )
            
            if (str(m.get("source_channel_id")) == str(edit_context['source_channel_id']) 
                and str(m.get("source_message_id")) == str(edit_context['message_id'])):
                msg_id = m.get("message_id")
                break
        
        if msg_id:
            log_message_state("EDIT - ATTEMPTING UPDATE",
                target_channel=edit_context['target_channel_id'],
                message_id=msg_id,
                message_length=len(edit_context['message_content'])
            )
            
            ok = sender.edit_message(
                edit_context['target_channel_id'], 
                msg_id, 
                edit_context['message_content'], 
                recorder
            )
            
            if ok:
                log_message_state("EDIT - SUCCESS",
                    target_channel=edit_context['target_channel_id'],
                    message_id=msg_id,
                    recorder_state=recorder.stats
                )
                return {"success": True, "message": "Message edited successfully."}
            else:
                error_info = await get_error_details(None, context=edit_context)
                log_message_state("EDIT - FAILED", error_info=error_info)
                return {
                    "success": False,
                    "message": "Failed to edit message.",
                    "error": error_info
                }
        else:
            log_message_state("EDIT - NO MESSAGE FOUND", 
                source_channel=edit_context['source_channel_id'],
                message_id=edit_context['message_id']
            )
            return {
                "success": False,
                "message": "No matching message found to edit.",
                "code": "EDIT-ERR-001"
            }
            
    except Exception as e:
        error_info = await get_error_details(e, context=edit_context)
        log_message_state("EDIT - EXCEPTION",
            error=str(e),
            error_info=error_info,
            context=edit_context
        )
        return {
            "success": False,
            "message": "Failed to edit message.",
            "error": error_info
        }


async def send_new_message(recorder: EventRecorder, message_context: dict):
    """Handle sending new messages with detailed logging"""
    try:
        from translator.services.telegram_sender import TelegramSender
        sender = TelegramSender()
        
        log_message_state("NEW MESSAGE - ATTEMPTING SEND",
            target_channel=message_context['target_channel_id'],
            message_length=len(message_context['message_content']),
            has_html='<' in message_context['message_content']
        )
        
        ok = asyncio.run(
            sender.send_message(message_context['message_content'], recorder)
        )
        
        if ok:
            log_message_state("NEW MESSAGE - SUCCESS",
                target_channel=message_context['target_channel_id'],
                message_id=getattr(sender, "last_message_id", None),
                recorder_state=recorder.stats
            )
            return {"success": True, "message": "Posted successfully."}
        else:
            error_info = await get_error_details(None, context=message_context)
            log_message_state("NEW MESSAGE - FAILED", error_info=error_info)
            return {
                "success": False,
                "message": "Failed to post message.",
                "error": error_info
            }
            
    except Exception as e:
        error_info = await get_error_details(e, context=message_context)
        log_message_state("NEW MESSAGE - EXCEPTION",
            error=str(e),
            error_info=error_info,
            context=message_context
        )
        return {
            "success": False,
            "message": "Failed to post message.",
            "error": error_info
        }
