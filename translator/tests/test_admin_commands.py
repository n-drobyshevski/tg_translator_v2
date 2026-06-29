"""Tests for the admin DM command dispatcher (handle_command)."""

import types

import pytest

import translator.config as config
from translator.config import CONFIG
from translator.services import (
    admin_commands,
    admin_prefs,
    admin_store,
    admin_wizard,
    env_store,
)


class Msg:
    """Minimal stand-in for a Pyrogram message."""

    def __init__(self, text, reply_to_message=None, from_user=None):
        self.text = text
        self.reply_to_message = reply_to_message
        self.from_user = from_user


def _user(uid):
    return types.SimpleNamespace(id=uid)


class _Reply:
    def __init__(self, text):
        self.text = text


@pytest.fixture
def admin_env(tmp_path, monkeypatch):
    # Route .env writes to a temp file.
    monkeypatch.setattr(env_store, "_root_env_path", lambda: tmp_path / ".env")
    # Keep admin labels in a temp file and avoid real getChat network calls.
    monkeypatch.setattr(admin_store, "_labels_path", lambda: tmp_path / "labels.json")
    monkeypatch.setattr(admin_store, "resolve_name", lambda uid: None)
    admin_store._name_cache.clear()
    # Keep per-admin language prefs in a temp file; reset wizard state.
    monkeypatch.setattr(admin_prefs, "_prefs_path", lambda: tmp_path / "prefs.json")
    admin_wizard._PENDING.clear()
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
    assert "admin menu" in out.lower()
    # The simplified help describes the 3 top-level menus.
    assert "status" in out.lower()
    assert "ai settings" in out.lower()
    assert "settings" in out.lower()


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


async def test_admins_lists(admin_env):
    out = await admin_commands.handle_command(Msg("/admins"))
    assert "Admins" in out
    assert "111" in out and "222" in out


async def test_addadmin_command(admin_env):
    out = await admin_commands.handle_command(Msg("/addadmin 333 Alice"))
    assert out.startswith("✅")
    assert CONFIG.ADMIN_CHAT_IDS == [111, 222, 333]
    assert admin_store.get_labels() == {"333": "Alice"}


async def test_addadmin_rejects_bad_id(admin_env):
    out = await admin_commands.handle_command(Msg("/addadmin notanid"))
    assert out.startswith("❌")
    assert CONFIG.ADMIN_CHAT_IDS == [111, 222]


class _FakePyro:
    """Stand-in for the Pyrogram client's async get_users."""

    def __init__(self, user=None, exc=None):
        self._user = user
        self._exc = exc

    async def get_users(self, uname):
        if self._exc is not None:
            raise self._exc
        return self._user


def test_add_shared_users_name_label(admin_env):
    users = [
        types.SimpleNamespace(id=501, first_name="Bob", last_name="Lee", username="boblee")
    ]
    out = admin_commands._add_shared_users(users)
    assert out.startswith("✅")
    assert 501 in CONFIG.ADMIN_CHAT_IDS
    assert admin_store.get_labels()["501"] == "Bob Lee"


def test_add_shared_users_username_fallback(admin_env):
    users = [
        types.SimpleNamespace(id=502, first_name=None, last_name=None, username="onlyuser")
    ]
    admin_commands._add_shared_users(users)
    assert admin_store.get_labels()["502"] == "@onlyuser"


def test_add_shared_users_empty(admin_env):
    assert admin_commands._add_shared_users([]).startswith("❌")


async def test_addadmin_username_resolves(admin_env):
    user = types.SimpleNamespace(
        id=777, first_name="Alice", last_name=None, username="alice"
    )
    out = await admin_commands.handle_command(
        Msg("/addadmin @alice"), pyro=_FakePyro(user=user)
    )
    assert out.startswith("✅")
    assert 777 in CONFIG.ADMIN_CHAT_IDS
    assert admin_store.get_labels()["777"] == "Alice"


async def test_addadmin_username_explicit_label_wins(admin_env):
    user = types.SimpleNamespace(
        id=778, first_name="Alice", last_name=None, username="alice"
    )
    await admin_commands.handle_command(
        Msg("/addadmin @alice Chief Editor"), pyro=_FakePyro(user=user)
    )
    assert admin_store.get_labels()["778"] == "Chief Editor"


async def test_addadmin_username_unresolvable(admin_env):
    out = await admin_commands.handle_command(
        Msg("/addadmin @ghost"), pyro=_FakePyro(exc=RuntimeError("USERNAME_NOT_OCCUPIED"))
    )
    assert out.startswith("❌")
    assert CONFIG.ADMIN_CHAT_IDS == [111, 222]


async def test_addadmin_username_without_pyro(admin_env):
    out = await admin_commands.handle_command(Msg("/addadmin @alice"))
    assert out.startswith("❌")
    assert CONFIG.ADMIN_CHAT_IDS == [111, 222]


async def test_removeadmin_command(admin_env):
    out = await admin_commands.handle_command(Msg("/removeadmin 222"))
    assert out.startswith("✅")
    assert CONFIG.ADMIN_CHAT_IDS == [111]


async def test_removeadmin_last_blocked(admin_env, monkeypatch):
    monkeypatch.setenv("ADMIN_CHAT_ID", "111")
    CONFIG.reload()
    out = await admin_commands.handle_command(Msg("/removeadmin 111"))
    assert out.startswith("❌") and "last admin" in out
    assert CONFIG.ADMIN_CHAT_IDS == [111]


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


async def test_status_lists_recent_events(admin_env, monkeypatch):
    from translator.db import events_dao

    monkeypatch.setattr(
        events_dao,
        "load_messages",
        lambda since_iso=None, event_type=None: [
            {
                "posting_success": True,
                "exception_message": "",
                "source_channel_name": "ok_chan",
                "media_type": "photo",
                "timestamp": "2026-06-28T10:00:00+00:00",
            },
            {
                "posting_success": False,
                "exception_message": "Anthropic credits exhausted. Top up under Plans & Billing.",
                "source_channel_name": "test_source",
                "timestamp": "2026-06-28T22:12:01+00:00",
            },
        ],
    )
    out = await admin_commands.handle_command(Msg("/status"))
    # One unified feed; no more split successes/failures sections.
    assert "Recent events" in out
    assert "Recent successes" not in out
    assert "Recent failures" not in out
    # The successful event renders with ✅ and its media type.
    assert "✅" in out
    assert "ok_chan" in out
    assert "photo" in out
    # The failed event renders with ❌ and its humanized reason.
    assert "❌" in out
    assert "test_source" in out
    assert "Anthropic credits exhausted" in out


async def test_status_shows_only_latest_six_events(admin_env, monkeypatch):
    from translator.db import events_dao

    # 8 events, oldest-first (as load_messages returns them); only the newest 6
    # should render, newest at the top.
    events = [
        {
            "posting_success": True,
            "exception_message": "",
            "source_channel_name": f"chan{i}",
            "media_type": "text",
            "timestamp": f"2026-06-28T10:0{i}:00+00:00",
        }
        for i in range(8)
    ]
    monkeypatch.setattr(
        events_dao, "load_messages", lambda since_iso=None, event_type=None: events
    )
    out = await admin_commands.handle_command(Msg("/status"))
    # Oldest two are dropped; newest six are shown.
    assert "chan0" not in out
    assert "chan1" not in out
    assert "chan2" in out
    assert "chan7" in out
    # The header still reports the full window count, not the display cap.
    assert "(last 7d) — 8" in out


async def test_status_humanizes_legacy_raw_error(admin_env, monkeypatch):
    # Events recorded before humanize_error stored the raw SDK dump; /status must
    # still render them cleanly (humanize_text at display time).
    from translator.db import events_dao

    raw = (
        "Error code: 400 - {'type': 'error', 'error': {'type': "
        "'invalid_request_error', 'message': 'Your credit balance is too low to "
        "access the Anthropic API. Please go to Plans & Billing.'}, "
        "'request_id': 'req_x'}"
    )
    monkeypatch.setattr(
        events_dao,
        "load_messages",
        lambda since_iso=None, event_type=None: [
            {
                "posting_success": False,
                "exception_message": raw,
                "source_channel_name": "test_source",
                "timestamp": "2026-06-28T20:12:00+00:00",
            }
        ],
    )
    out = await admin_commands.handle_command(Msg("/status"))
    assert "Anthropic credits exhausted" in out
    assert "Error code:" not in out  # the raw dump is no longer shown


async def test_status_no_events(admin_env, monkeypatch):
    from translator.db import events_dao

    monkeypatch.setattr(
        events_dao, "load_messages", lambda since_iso=None, event_type=None: []
    )
    out = await admin_commands.handle_command(Msg("/status"))
    assert "Recent events" in out
    assert "None in the last 7 days" in out


# --- Add-channel wizard -------------------------------------------------------


async def test_wizard_happy_path_adds_channel(admin_env):
    u = _user(111)
    admin_wizard.start(111)
    r1 = await admin_commands.handle_command(Msg("news", from_user=u))
    assert "2/3" in r1  # advanced to the source-id prompt
    r2 = await admin_commands.handle_command(Msg("55", from_user=u))
    assert "3/3" in r2  # advanced to the destination-id prompt
    r3 = await admin_commands.handle_command(Msg("56", from_user=u))
    assert r3.startswith("✅")
    assert not admin_wizard.is_active(111)
    assert CONFIG.get_channel_id("news") == 55
    assert CONFIG.get_channel_id("news_en") == 56


async def test_wizard_bad_name_reprompts(admin_env):
    u = _user(111)
    admin_wizard.start(111)
    out = await admin_commands.handle_command(Msg("Bad Name", from_user=u))
    assert out.startswith("❌")
    assert admin_wizard.is_active(111)  # still on the name step


async def test_wizard_duplicate_name_rejected(admin_env):
    u = _user(111)
    admin_wizard.start(111)
    out = await admin_commands.handle_command(Msg("test", from_user=u))
    assert out.startswith("❌")
    assert admin_wizard.is_active(111)


async def test_wizard_non_int_src_reprompts(admin_env):
    u = _user(111)
    admin_wizard.start(111)
    await admin_commands.handle_command(Msg("news", from_user=u))
    out = await admin_commands.handle_command(Msg("notanint", from_user=u))
    assert out.startswith("❌")
    assert admin_wizard.is_active(111)  # still awaiting the source id


async def test_wizard_cancel_command(admin_env):
    u = _user(111)
    admin_wizard.start(111)
    out = await admin_commands.handle_command(Msg("/cancel", from_user=u))
    assert out.startswith("✅")
    assert not admin_wizard.is_active(111)


async def test_wizard_button_tap_escapes(admin_env):
    u = _user(111)
    admin_wizard.start(111)
    # Tapping a reply-keyboard button mid-wizard abandons it and runs the command.
    out = await admin_commands.handle_command(Msg("📊 Status", from_user=u))
    assert not admin_wizard.is_active(111)
    assert "Status" in out


# --- Per-admin language -------------------------------------------------------


async def test_setlang_persists_and_localizes(admin_env):
    u = _user(111)
    out = await admin_commands.handle_command(Msg("/setlang be", from_user=u))
    assert out.startswith("✅")
    assert admin_prefs.get_lang(111) == "be"
    # A subsequent reply for this admin renders in Belarusian.
    be_help = await admin_commands.handle_command(Msg("/help", from_user=u))
    en_help = await admin_commands.handle_command(Msg("/help"))
    assert be_help != en_help
    assert "адмінскае меню" in be_help


async def test_setlang_rejects_unknown(admin_env):
    u = _user(111)
    out = await admin_commands.handle_command(Msg("/setlang xx", from_user=u))
    assert out.startswith("❌")
    assert admin_prefs.get_lang(111) == "en"
