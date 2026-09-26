"""Suite-wide isolation for the rich-message switch.

Importing ``translator.config`` runs ``load_dotenv()``, so a developer's real
``.env`` leaks into ``os.environ`` for the whole run — an ``ADMIN_RICH_MESSAGES=0``
(or the legacy ``ADMIN_RICH_MENUS=0``) there would silently flip every test that
expects the shipped default (rich on). The circuit breaker is module state too,
and a test that makes rich sends fail would otherwise trip it for later tests.
"""

import pytest

from translator.services import admin_menu, rich_html


@pytest.fixture(autouse=True)
def _rich_defaults(monkeypatch):
    for name in (rich_html.RICH_ENV, rich_html.LEGACY_RICH_ENV):
        # setenv first so monkeypatch records the original state and restores it
        # afterwards — /setrich writes os.environ (as every DM setter does), and
        # a bare delenv of an unset variable would register nothing to undo.
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name)
    admin_menu._breaker.reset()
    yield
    admin_menu._breaker.reset()
