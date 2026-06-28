"""Tests for the admin string catalog and the t() lookup helper."""

from translator.services import admin_i18n
from translator.services.admin_i18n import t


def test_known_key_english():
    assert t("btn_status", "en") == "📊 Status"


def test_unknown_locale_falls_back_to_english():
    assert t("btn_status", "zz") == t("btn_status", "en")


def test_missing_key_in_locale_falls_back_to_english(monkeypatch):
    # A key present in en but absent in be must render the en string.
    partial_be = {k: v for k, v in admin_i18n._BE.items() if k != "btn_status"}
    monkeypatch.setitem(admin_i18n.STRINGS, "be", partial_be)
    assert t("btn_status", "be") == admin_i18n._EN["btn_status"]


def test_unknown_key_returns_raw_key():
    assert t("__no_such_key__", "en") == "__no_such_key__"
    assert t("__no_such_key__", "be") == "__no_such_key__"


def test_interpolation():
    assert t("setmodel_ok", "en", model="claude-x") == "✅ ANTHROPIC_MODEL = claude-x"


def test_bad_placeholder_does_not_raise():
    # Missing/extra kwargs must degrade to the un-formatted string, not crash.
    out = t("setmodel_ok", "en", wrong="x")
    assert out == admin_i18n._EN["setmodel_ok"]


def test_every_belarusian_key_exists_in_english():
    # Guards against typo'd / orphaned keys in the be table.
    assert set(admin_i18n._BE).issubset(set(admin_i18n._EN))
