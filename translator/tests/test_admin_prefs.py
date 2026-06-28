"""Tests for the per-admin language preference store."""

import pytest

from translator.services import admin_prefs


@pytest.fixture
def prefs_path(tmp_path, monkeypatch):
    path = tmp_path / "prefs.json"
    monkeypatch.setattr(admin_prefs, "_prefs_path", lambda: path)
    return path


def test_default_when_unset(prefs_path):
    assert admin_prefs.get_lang(111) == "en"


def test_set_and_get_roundtrip(prefs_path):
    ok, val = admin_prefs.set_lang(111, "be")
    assert ok and val == "be"
    assert admin_prefs.get_lang(111) == "be"
    # Other ids are unaffected.
    assert admin_prefs.get_lang(222) == "en"


def test_set_rejects_unknown_locale(prefs_path):
    ok, _ = admin_prefs.set_lang(111, "xx")
    assert not ok
    assert admin_prefs.get_lang(111) == "en"


def test_corrupt_file_returns_default(prefs_path):
    prefs_path.write_text("{ not json", encoding="utf-8")
    assert admin_prefs.get_lang(111) == "en"


def test_stringified_id_keys(prefs_path):
    admin_prefs.set_lang(111, "be")
    # int and str ids resolve to the same stored entry.
    assert admin_prefs.get_lang("111") == "be"
