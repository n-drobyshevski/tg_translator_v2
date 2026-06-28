"""Tests for the button-driven admin menu (pure layer, no Pyrogram)."""

import pytest

from translator.config import CONFIG
from translator.services import admin_menu, env_store


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


def _flat_data(rows):
    """All callback_data strings in a rows spec."""
    return [cd for row in rows for _label, cd in row]


def test_resolve_button_label_maps_to_commands():
    assert admin_menu.resolve_button_label("📊 Status") == "/status"
    assert admin_menu.resolve_button_label("🛠️ Settings") == "/settings"
    assert admin_menu.resolve_button_label("  📈 Stats  ") == "/stats"


def test_resolve_button_label_unknown_is_none():
    assert admin_menu.resolve_button_label("/status") is None
    assert admin_menu.resolve_button_label("hello") is None
    assert admin_menu.resolve_button_label("") is None


def test_config_button_merged_into_settings():
    # The standalone Config button is gone; Settings is the merged hub.
    assert admin_menu.resolve_button_label("⚙️ Config") is None
    labels = [lbl for row in admin_menu.build_reply_keyboard() for lbl in row]
    assert "⚙️ Config" not in labels
    assert "🛠️ Settings" in labels


def test_settings_menu_shows_current_values(admin_env):
    res = admin_menu.handle_callback("nav:settings")
    assert "Model:" in res.text
    assert CONFIG.ANTHROPIC_MODEL in res.text
    assert "Pick a setting to change." in res.text


def test_nav_settings_returns_settings_rows(admin_env):
    res = admin_menu.handle_callback("nav:settings")
    assert res.rows is not None
    data = _flat_data(res.rows)
    assert "nav:model" in data
    assert "nav:rmch" in data
    assert "nav:close" in data


@pytest.mark.parametrize("target", ["model", "temp", "tokens", "log", "rmch"])
def test_nav_submenus_have_back(admin_env, target):
    res = admin_menu.handle_callback(f"nav:{target}")
    assert res.rows is not None
    assert "nav:settings" in _flat_data(res.rows)


def test_nav_close_clears_keyboard(admin_env):
    res = admin_menu.handle_callback("nav:close")
    assert res.rows is None
    assert "closed" in res.text.lower()


def test_set_log_applies(admin_env):
    res = admin_menu.handle_callback("set:log:DEBUG")
    assert res.alert == "Saved"
    assert CONFIG.LOG_LEVEL == "DEBUG"
    assert "DEBUG" in (admin_env / ".env").read_text("utf-8")
    assert "nav:settings" in _flat_data(res.rows)


def test_set_temp_applies(admin_env):
    res = admin_menu.handle_callback("set:temp:0.3")
    assert res.alert == "Saved"
    assert CONFIG.ANTHROPIC_TEMPERATURE == 0.3


def test_set_tokens_applies(admin_env):
    res = admin_menu.handle_callback("set:tokens:2000")
    assert res.alert == "Saved"
    assert CONFIG.ANTHROPIC_MAX_TOKENS == 2000


def test_set_model_applies(admin_env):
    res = admin_menu.handle_callback("set:model:claude-sonnet-4-6")
    assert res.alert == "Saved"
    assert CONFIG.ANTHROPIC_MODEL == "claude-sonnet-4-6"


def test_rmch_menu_excludes_protected(admin_env):
    res = admin_menu.handle_callback("nav:rmch")
    data = _flat_data(res.rows)
    assert "rmch:christianvision" in data
    assert "rmch:shaltnotkill" in data
    assert "rmch:test" not in data  # protected


def test_rmch_shows_confirm(admin_env):
    res = admin_menu.handle_callback("rmch:christianvision")
    data = _flat_data(res.rows)
    assert "rmchok:christianvision" in data
    assert "nav:rmch" in data  # the "no, back" button


def test_rmchok_removes_channel(admin_env):
    res = admin_menu.handle_callback("rmchok:shaltnotkill")
    assert res.alert == "Removed"
    assert "shaltnotkill" not in admin_menu.admin_commands._logical_names()


def test_unknown_callback_falls_back(admin_env):
    res = admin_menu.handle_callback("garbage:data")
    assert res.rows is None
    assert "expired" in res.text.lower()
