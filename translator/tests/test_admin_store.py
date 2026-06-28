"""Tests for the admin allow-list store (add/remove/list + labels + resolve)."""

import types

import pytest

from translator.config import CONFIG
from translator.services import admin_store, env_store


@pytest.fixture
def admin_env(tmp_path, monkeypatch):
    # Route .env and the labels file to temp paths.
    monkeypatch.setattr(env_store, "_root_env_path", lambda: tmp_path / ".env")
    monkeypatch.setattr(admin_store, "_labels_path", lambda: tmp_path / "labels.json")
    # Required config env for CONFIG.reload().
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
    admin_store._name_cache.clear()
    CONFIG.reload()
    return tmp_path


# --- add / remove ------------------------------------------------------------


def test_add_admin_persists_and_reloads(admin_env):
    ok, msg = admin_store.add_admin("333")
    assert ok and "333" in msg
    assert CONFIG.ADMIN_CHAT_IDS == [111, 222, 333]
    assert "ADMIN_CHAT_ID=111,222,333" in (admin_env / ".env").read_text("utf-8")


def test_add_admin_dedupe(admin_env):
    ok, msg = admin_store.add_admin("111")
    assert not ok and "already" in msg
    assert CONFIG.ADMIN_CHAT_IDS == [111, 222]


def test_add_admin_dedupe_updates_label(admin_env):
    ok, msg = admin_store.add_admin("111", "Boss")
    assert ok and "label" in msg
    assert admin_store.get_labels() == {"111": "Boss"}


@pytest.mark.parametrize("bad", ["abc", "", "-", "12a", "  "])
def test_add_admin_rejects_non_numeric(admin_env, bad):
    ok, _ = admin_store.add_admin(bad)
    assert not ok
    assert CONFIG.ADMIN_CHAT_IDS == [111, 222]


def test_add_admin_accepts_negative(admin_env):
    ok, _ = admin_store.add_admin("-100123")
    assert ok
    assert -100123 in CONFIG.ADMIN_CHAT_IDS


def test_add_admin_with_label(admin_env):
    ok, _ = admin_store.add_admin("333", "Alice")
    assert ok
    assert admin_store.get_labels() == {"333": "Alice"}


def test_remove_admin(admin_env):
    ok, _ = admin_store.remove_admin("222")
    assert ok
    assert CONFIG.ADMIN_CHAT_IDS == [111]
    assert "ADMIN_CHAT_ID=111" in (admin_env / ".env").read_text("utf-8")


def test_remove_last_admin_blocked(admin_env, monkeypatch):
    monkeypatch.setenv("ADMIN_CHAT_ID", "111")
    CONFIG.reload()
    ok, msg = admin_store.remove_admin("111")
    assert not ok and "last admin" in msg
    assert CONFIG.ADMIN_CHAT_IDS == [111]


def test_remove_nonexistent(admin_env):
    ok, msg = admin_store.remove_admin("999")
    assert not ok and "not an admin" in msg


def test_remove_drops_label(admin_env):
    admin_store.set_label("222", "Bob")
    assert admin_store.get_labels() == {"222": "Bob"}
    ok, _ = admin_store.remove_admin("222")
    assert ok
    assert admin_store.get_labels() == {}


# --- labels ------------------------------------------------------------------


def test_set_label_roundtrip_and_clear(admin_env):
    admin_store.set_label("111", "Alice")
    assert admin_store.get_labels()["111"] == "Alice"
    admin_store.set_label("111", "")  # blank clears
    assert "111" not in admin_store.get_labels()


# --- name resolution ---------------------------------------------------------


def _fake_response(status=200, payload=None):
    return types.SimpleNamespace(
        status_code=status, json=lambda: (payload or {})
    )


def test_resolve_name_username_and_cache(admin_env, monkeypatch):
    calls = {"n": 0}

    def fake_get(url, params=None, timeout=None):
        calls["n"] += 1
        return _fake_response(200, {"result": {"username": "alice"}})

    monkeypatch.setattr(admin_store.requests, "get", fake_get)
    assert admin_store.resolve_name(111) == "@alice"
    assert admin_store.resolve_name(111) == "@alice"  # served from cache
    assert calls["n"] == 1


def test_resolve_name_full_name(admin_env, monkeypatch):
    monkeypatch.setattr(
        admin_store.requests,
        "get",
        lambda *a, **k: _fake_response(200, {"result": {"first_name": "Jane", "last_name": "Doe"}}),
    )
    assert admin_store.resolve_name(222) == "Jane Doe"


def test_resolve_name_fallback_on_error(admin_env, monkeypatch):
    monkeypatch.setattr(
        admin_store.requests, "get", lambda *a, **k: _fake_response(400, {})
    )
    assert admin_store.resolve_name(222) is None

    def boom(*a, **k):
        raise RuntimeError("network down")

    admin_store._name_cache.clear()
    monkeypatch.setattr(admin_store.requests, "get", boom)
    assert admin_store.resolve_name(222) is None


def test_list_admins_priority(admin_env, monkeypatch):
    admin_store.set_label("111", "Boss")
    monkeypatch.setattr(admin_store, "resolve_name", lambda uid: "@resolved")
    rows = admin_store.list_admins()
    assert rows[0]["display"] == "Boss"  # manual label wins
    assert rows[1]["display"] == "@resolved"  # else resolved name


def test_list_admins_falls_back_to_id(admin_env, monkeypatch):
    monkeypatch.setattr(admin_store, "resolve_name", lambda uid: None)
    rows = admin_store.list_admins()
    assert [r["display"] for r in rows] == ["111", "222"]
