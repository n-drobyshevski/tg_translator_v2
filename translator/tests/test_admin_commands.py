"""Tests for the admin DM command dispatcher (handle_command)."""

import re
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


async def test_settemp_warns_when_the_model_ignores_it(admin_env, monkeypatch):
    # Sonnet 5 / Opus 4.7+ reject sampling params, so temperature isn't sent.
    # Saving it is still right (it applies if the model is switched back), but
    # the operator must not think they just changed the bot's behaviour.
    await admin_commands.handle_command(Msg("/setmodel claude-sonnet-5"))
    out = await admin_commands.handle_command(Msg("/settemp 0.5"))
    assert "ANTHROPIC_TEMPERATURE = 0.5" in out
    assert "ignores temperature" in out
    assert "claude-sonnet-5" in out


async def test_settemp_has_no_warning_on_a_sampling_model(admin_env):
    await admin_commands.handle_command(Msg("/setmodel claude-haiku-4-5"))
    out = await admin_commands.handle_command(Msg("/settemp 0.5"))
    assert "ignores temperature" not in out


async def test_setmaxtokens_applies(admin_env):
    await admin_commands.handle_command(Msg("/setmaxtokens 2000"))
    assert CONFIG.ANTHROPIC_MAX_TOKENS == 2000


async def test_setmaxtokens_allows_headroom_above_the_new_default(admin_env):
    # The old ceiling was 8192, only 192 above the 8000 default — with thinking
    # sharing the budget, an operator hitting truncation needs room to raise it.
    await admin_commands.handle_command(Msg("/setmaxtokens 32000"))
    assert CONFIG.ANTHROPIC_MAX_TOKENS == 32000
    out = await admin_commands.handle_command(Msg("/setmaxtokens 200000"))
    assert out.startswith("❌")


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


async def test_logs_command_missing_file(admin_env, monkeypatch):
    monkeypatch.setattr(admin_commands, "LOG_FILE_PATH", str(admin_env / "nope.log"))
    out = await admin_commands.handle_command(Msg("/logs"))
    assert "no log file" in out.lower()


async def test_logs_command_returns_recent_tail(admin_env, monkeypatch):
    log = admin_env / "bot.log"
    log.write_text("\n".join(f"line {i}" for i in range(1, 101)), encoding="utf-8")
    monkeypatch.setattr(admin_commands, "LOG_FILE_PATH", str(log))
    out = await admin_commands.handle_command(Msg("/logs"))
    # Tail keeps the newest lines and drops the oldest (default 30 lines).
    assert "line 100" in out
    assert "line 71" in out
    assert "line 1\n" not in out and "line 70" not in out


def test_cmd_logs_empty_file(admin_env, monkeypatch):
    log = admin_env / "bot.log"
    log.write_text("   \n", encoding="utf-8")
    monkeypatch.setattr(admin_commands, "LOG_FILE_PATH", str(log))
    assert "empty" in admin_commands._cmd_logs().lower()


def test_tail_lines_trims_partial_first_line(admin_env):
    log = admin_env / "big.log"
    log.write_text("\n".join(f"row{i}" for i in range(2000)), encoding="utf-8")
    # A tiny byte budget forces a mid-file start; the (possibly partial) first
    # line is dropped, so every returned line is complete and the newest is kept.
    tail = admin_commands._tail_lines(str(log), 5, max_bytes=40)
    lines = tail.splitlines()
    assert lines[-1] == "row1999"
    assert len(lines) <= 5
    assert all(re.fullmatch(r"row\d+", ln) for ln in lines)


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


# --- Rich messages: every reply carries both renderings -----------------------

from translator.services import admin_menu, rich_html  # noqa: E402


@pytest.mark.parametrize(
    "command",
    [
        "/help", "/status", "/stats", "/stats 99", "/channels", "/prompt", "/logs",
        "/admins", "/reload", "/setmodel claude-x", "/settemp 0.5", "/settemp x",
        "/setmaxtokens 2000", "/seteffort low", "/setloglevel INFO", "/setrich on",
        "/setrich maybe", "/removechannel test", "/bogus", "hello",
    ],
)
async def test_every_reply_has_a_rich_rendering(admin_env, command):
    out = await admin_commands.handle_command(Msg(command))
    assert isinstance(out, rich_html.RichText), command
    assert out.rich, f"{command} has no rich rendering"
    assert len(out) <= rich_html.CLASSIC_LIMIT
    assert "\n" not in out.rich.split("<pre")[0], "layout must not rely on newlines"


async def test_outcomes_are_structured(admin_env):
    ok = await admin_commands.handle_command(Msg("/settemp 0.5"))
    bad = await admin_commands.handle_command(Msg("/settemp 9"))
    assert ok.status is True and ok.startswith("✅")
    assert bad.status is False and bad.startswith("❌")
    assert rich_html.outcome(ok) is True and rich_html.outcome(bad) is False


def test_help_groups_cover_every_published_command_exactly_once():
    grouped = [n for _, names in admin_commands.COMMAND_GROUPS for n in names]
    published = [n for n, _ in admin_commands.COMMAND_SPECS]
    assert sorted(grouped) == sorted(published)


async def test_help_is_collapsible_per_group(admin_env):
    out = await admin_commands.handle_command(Msg("/help"))
    assert out.rich.count("<details>") == len(admin_commands.COMMAND_GROUPS)
    assert "<code>/setrich</code>" in out.rich
    # Classic fallback: bold group name + expandable quote per group.
    assert out.count("<blockquote expandable>") == len(admin_commands.COMMAND_GROUPS)


async def test_logs_show_more_in_rich_than_in_classic(admin_env, monkeypatch):
    log = admin_env / "bot.log"
    log.write_text("\n".join(f"line {i}" for i in range(1, 301)), encoding="utf-8")
    monkeypatch.setattr(admin_commands, "LOG_FILE_PATH", str(log))
    out = await admin_commands.handle_command(Msg("/logs"))
    assert "line 151" in out.rich and "line 150\n" not in out.rich
    assert "line 271" in out and "line 270" not in out


async def test_prompt_is_complete_in_rich_and_fitted_in_classic(admin_env, monkeypatch):
    prompt = admin_env / "prompt.txt"
    body = "\n".join(f"rule {i} {'x' * 60}" for i in range(120))  # ≈ 8 KB
    prompt.write_text(body, encoding="utf-8")
    monkeypatch.setattr(admin_commands, "PROMPT_TEMPLATE_PATH", prompt)
    out = await admin_commands.handle_command(Msg("/prompt"))
    assert "rule 119" in out.rich  # nothing cut from the rich message
    assert "rule 0 " in out and "rule 119" not in out  # classic keeps the start
    assert len(out) <= rich_html.CLASSIC_LIMIT
    assert "/setprompt" in out  # the footer survives truncation


async def test_setrich_persists_the_kill_switch(admin_env):
    out = await admin_commands.handle_command(Msg("/setrich off"))
    assert out.startswith("✅")
    assert "ADMIN_RICH_MESSAGES=0" in (admin_env / ".env").read_text("utf-8")
    assert rich_html.rich_env_enabled() is False
    out = await admin_commands.handle_command(Msg("/setrich on"))
    assert rich_html.rich_env_enabled() is True
    assert "ADMIN_RICH_MESSAGES=1" in (admin_env / ".env").read_text("utf-8")


async def test_setrich_rejects_other_values(admin_env):
    out = await admin_commands.handle_command(Msg("/setrich maybe"))
    assert out.startswith("❌")


async def test_setrich_on_warns_when_this_kurigram_cannot(admin_env, monkeypatch):
    monkeypatch.setattr(admin_menu, "HAS_RICH_MESSAGES", False)
    out = await admin_commands.handle_command(Msg("/setrich on"))
    assert out.startswith("✅") and "can't send rich messages" in out


async def test_reload_picks_up_an_out_of_band_rich_switch(admin_env):
    (admin_env / ".env").write_text("ADMIN_RICH_MESSAGES=0\n", encoding="utf-8")
    assert rich_html.rich_env_enabled() is True
    out = await admin_commands.handle_command(Msg("/reload"))
    assert out.startswith("✅")
    assert rich_html.rich_env_enabled() is False


def test_rich_toggle_in_settings_routes_through_setrich(admin_env):
    from translator.services import admin_menu as menu

    _title, rows = menu.build_menu("settings")
    data = [cd for row in rows for _, cd in row]
    assert "set:rich:off" in data  # on by default, so the button turns it off
    res = menu.handle_callback("set:rich:off")
    assert res.alert == "Saved"
    assert rich_html.rich_env_enabled() is False
    assert "nav:settings" in [cd for row in res.rows for _, cd in row]
    _title, rows = menu.build_menu("settings")
    assert "set:rich:on" in [cd for row in rows for _, cd in row]


async def test_wizard_shows_progress(admin_env):
    u = _user(111)
    admin_wizard.start(111)
    first = admin_wizard.prompt(111)
    assert "1/3" in first and "▶️" in first.rich
    r1 = await admin_commands.handle_command(Msg("news", from_user=u))
    assert "✅ Name: <code>news</code>" in r1.rich
    assert "▶️ <b>Source channel id</b>" in r1.rich


async def test_richcheck_outside_the_dm_dispatcher_is_not_unknown(admin_env):
    out = await admin_commands.handle_command(Msg("/richcheck"))
    assert out.startswith("❌") and "Unknown" not in out


def test_every_model_preset_has_a_price_row():
    for _label, value in admin_menu.MODEL_PRESETS:
        assert value in admin_menu.MODEL_PRICING, value


async def test_belarusian_screens_render(admin_env):
    u = _user(111)
    await admin_commands.handle_command(Msg("/setlang be", from_user=u))
    from translator.services import admin_i18n

    keys = [k for k in admin_i18n._EN if "_" in k]
    for command in ("/status", "/help", "/stats", "/admins", "/settemp x"):
        out = await admin_commands.handle_command(Msg(command, from_user=u))
        assert out.rich, command
        # t() returns the raw key on a miss; none may reach the operator.
        leaked = [k for k in keys if k in out or k in out.rich]
        assert not leaked, f"{command}: {leaked}"
