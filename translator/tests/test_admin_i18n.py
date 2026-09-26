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
    assert t("h_stats", "en", days=7) == "📈 Stats — last 7d"


def test_bad_placeholder_does_not_raise():
    # Missing/extra kwargs must degrade to the un-formatted string, not crash.
    out = t("h_stats", "en", wrong="x")
    assert out == admin_i18n._EN["h_stats"]


def test_every_belarusian_key_exists_in_english():
    # Guards against typo'd / orphaned keys in the be table.
    assert set(admin_i18n._BE).issubset(set(admin_i18n._EN))


def test_no_string_carries_a_newline():
    # Layout comes from rich_html blocks. How the rich dialect treats a bare "\n"
    # is undocumented, so a newline inside a fragment is a layout bug waiting.
    for lang, table in admin_i18n.STRINGS.items():
        for key, value in table.items():
            assert "\n" not in value, f"{lang}:{key} contains a newline"


def test_every_key_used_in_the_code_exists_in_english():
    """``t()`` returns the raw key on a miss, so a typo'd key renders silently."""
    import pathlib
    import re

    services = pathlib.Path(admin_i18n.__file__).parent
    pattern = re.compile(r"""\bt\(\s*["']([a-z0-9_]+)["']""")
    used = set()
    for path in services.glob("*.py"):
        used |= set(pattern.findall(path.read_text(encoding="utf-8")))
    assert used, "the scan found nothing -- the pattern is broken"
    missing = sorted(k for k in used if k not in admin_i18n._EN)
    assert not missing, f"keys used in code but missing from _EN: {missing}"
