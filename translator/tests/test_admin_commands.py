"""Tests for the admin DM command dispatcher (handle_command)."""

import pytest

import translator.config as config
from translator.config import CONFIG
from translator.services import admin_commands, env_store


class Msg:
    """Minimal stand-in for a Pyrogram message."""

    def __init__(self, text, reply_to_message=None):
        self.text = text
        self.reply_to_message = reply_to_message


class _Reply:
    def __init__(self, text):
        self.text = text


@pytest.fixture
def admin_env(tmp_path, monkeypatch):
    # Route .env writes to a temp file.
    monkeypatch.setattr(env_store, "_root_env_path", lambda: tmp_path / ".env")
    # Required config env.
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_API_ID", "1")
    monkeypatch.setenv("TELEGRAM_API_HASH", "hash")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "api")
    monkeypatch.setenv("ADMIN_CHAT_ID", "111,222")
    monkeypatch.delenv("LOGICAL_CHANNELS", raising=False)
    for name, sid, did in (
        ("CHRISTIANVISION", "11", "12"),
        ("SHALTNOTKILL", "22", "23"),
        ("TEST", "33", "34"),
    ):
        monkeypatch.setenv(f"{name}_CHANNEL", sid)
        monkeypatch.setenv(f"{name}_EN_CHANNEL_ID", did)
    CONFIG.reload()
    return tmp_path


async def test_help(admin_env):
    out = await admin_commands.handle_command(Msg("/help"))
    assert "admin commands" in out.lower()


async def test_admin_ids_parsed(admin_env):
    assert CONFIG.ADMIN_CHAT_IDS == [111, 222]


async def test_setmodel_persists_and_applies(admin_env):
    out = await admin_commands.handle_command(Msg("/setmodel claude-test-9"))
    assert "claude-test-9" in out
    assert CONFIG.ANTHROPIC_MODEL == "claude-test-9"
    assert "ANTHROPIC_MODEL=claude-test-9" in (admin_env / ".env").read_text("utf-8")


async def test_settemp_rejects_out_of_range(admin_env):
    out = await admin_commands.handle_command(Msg("/settemp 5"))
    assert "0..1" in out


async def test_setmaxtokens_applies(admin_env):
    await admin_commands.handle_command(Msg("/setmaxtokens 2000"))
    assert CONFIG.ANTHROPIC_MAX_TOKENS == 2000


async def test_setloglevel_validates(admin_env):
    out = await admin_commands.handle_command(Msg("/setloglevel NOPE"))
    assert out.startswith("❌")
    ok = await admin_commands.handle_command(Msg("/setloglevel DEBUG"))
    assert "DEBUG" in ok


async def test_setprompt_inline(admin_env, tmp_path, monkeypatch):
    prompt_file = tmp_path / "prompt_template.txt"
    monkeypatch.setattr(admin_commands, "PROMPT_TEMPLATE_PATH", prompt_file)
    monkeypatch.setattr(config, "PROMPT_TEMPLATE_PATH", prompt_file)
    out = await admin_commands.handle_command(
        Msg("/setprompt\nTranslate {message_text} literally")
    )
    assert out.startswith("✅")
    assert "{message_text}" in prompt_file.read_text("utf-8")


async def test_setprompt_reply_mode(admin_env, tmp_path, monkeypatch):
    prompt_file = tmp_path / "prompt_template.txt"
    monkeypatch.setattr(admin_commands, "PROMPT_TEMPLATE_PATH", prompt_file)
    monkeypatch.setattr(config, "PROMPT_TEMPLATE_PATH", prompt_file)
    msg = Msg("/setprompt", reply_to_message=_Reply("Do {message_text} now"))
    out = await admin_commands.handle_command(msg)
    assert out.startswith("✅")
    assert "Do {message_text} now" in prompt_file.read_text("utf-8")


async def test_setprompt_rejects_missing_placeholder(admin_env, tmp_path, monkeypatch):
    prompt_file = tmp_path / "prompt_template.txt"
    monkeypatch.setattr(admin_commands, "PROMPT_TEMPLATE_PATH", prompt_file)
    monkeypatch.setattr(config, "PROMPT_TEMPLATE_PATH", prompt_file)
    out = await admin_commands.handle_command(Msg("/setprompt\nno placeholder here"))
    assert out.startswith("❌")


async def test_add_and_remove_channel(admin_env):
    out = await admin_commands.handle_command(Msg("/addchannel news 55 56"))
    assert out.startswith("✅")
    assert CONFIG.get_channel_id("news") == 55
    assert CONFIG.get_channel_id("news_en") == 56
    env_text = (admin_env / ".env").read_text("utf-8")
    assert "NEWS_CHANNEL=55" in env_text
    assert "news" in env_text  # LOGICAL_CHANNELS updated

    out2 = await admin_commands.handle_command(Msg("/removechannel news"))
    assert out2.startswith("✅")
    with pytest.raises(ValueError):
        CONFIG.get_channel_id("news")


async def test_add_channel_duplicate_rejected(admin_env):
    out = await admin_commands.handle_command(Msg("/addchannel test 1 2"))
    assert out.startswith("❌")


async def test_remove_protected_rejected(admin_env):
    out = await admin_commands.handle_command(Msg("/removechannel test"))
    assert "protected" in out


async def test_unknown_command(admin_env):
    out = await admin_commands.handle_command(Msg("/bogus"))
    assert "Unknown" in out


async def test_config_command_removed(admin_env):
    # /config was merged into the Settings menu; it's no longer a command.
    out = await admin_commands.handle_command(Msg("/config"))
    assert "Unknown" in out


async def test_stats_uses_events_dao(admin_env, monkeypatch):
    from translator.db import events_dao

    monkeypatch.setattr(
        events_dao,
        "load_messages",
        lambda since_iso=None, event_type=None: [
            {"posting_success": True, "source_channel_name": "cv"},
            {"posting_success": False, "source_channel_name": "cv"},
        ],
    )
    out = await admin_commands.handle_command(Msg("/stats 3"))
    assert "Relayed events: 2" in out
    assert "Failures: 1" in out
