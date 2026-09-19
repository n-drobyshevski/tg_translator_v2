"""Tests for the newer Telegram bot features in the admin DM surface.

Three groups, matching three distinct failure modes:

* **Preset freshness** — the menu's model/token presets went stale once already
  (the list still advertised "Haiku 4.5 (default)" after the default moved to
  Sonnet 5). These tests tie the presets to ``config.py`` so that can't repeat
  silently.
* **Button chrome** — disabled buttons, copy buttons and button styles are
  recent Bot API additions that cannot be exercised against live Telegram from
  here, so what is verified is the *encoding* and, above all, that the plain
  fallback leaves every action still reachable.
* **Command menu + chat picker** — the published "/" list must only contain
  commands that actually dispatch, and a channel picked through Telegram's
  native picker must walk the same wizard path a typed id does.
"""

import logging
import os
import sys
import types
from unittest.mock import patch

import pytest

from translator.config import CONFIG
from translator.services import (
    admin_commands,
    admin_i18n,
    admin_menu,
    admin_prefs,
    admin_store,
    admin_wizard,
    env_store,
)


@pytest.fixture(autouse=True)
def _isolated_environ():
    """Snapshot and restore ``os.environ`` around every test in this file.

    ``env_store.set_env_var`` writes to ``os.environ`` as well as ``.env`` — by
    design, since that is how ``CONFIG.reload()`` applies a DM change live — so
    any test that exercises a writable command leaks its value into every later
    test in the run. The preset-freshness tests below assert against the defaults
    in ``config.py``, which a leaked ANTHROPIC_MAX_TOKENS silently defeats (they
    passed alone and failed in the full suite until this fixture existed).
    """
    saved = dict(os.environ)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)


@pytest.fixture
def admin_env(tmp_path, monkeypatch):
    monkeypatch.setattr(env_store, "_root_env_path", lambda: tmp_path / ".env")
    monkeypatch.setattr(admin_store, "_labels_path", lambda: tmp_path / "labels.json")
    monkeypatch.setattr(admin_store, "resolve_name", lambda uid: None)
    admin_store._name_cache.clear()
    monkeypatch.setattr(admin_prefs, "_prefs_path", lambda: tmp_path / "prefs.json")
    admin_wizard._PENDING.clear()
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_API_ID", "1")
    monkeypatch.setenv("TELEGRAM_API_HASH", "hash")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "api")
    monkeypatch.setenv("ADMIN_CHAT_ID", "111,222")
    monkeypatch.delenv("LOGICAL_CHANNELS", raising=False)
    # Drop any leaked model settings so CONFIG falls back to the shipped
    # defaults — which is precisely what the preset tests check against.
    for key in (
        "ANTHROPIC_MODEL",
        "ANTHROPIC_MAX_TOKENS",
        "ANTHROPIC_TEMPERATURE",
        "ANTHROPIC_EFFORT",
    ):
        monkeypatch.delenv(key, raising=False)
    for name, sid, did in (
        ("CHRISTIANVISION", "11", "12"),
        ("SHALTNOTKILL", "22", "23"),
        ("TEST", "33", "34"),
    ):
        monkeypatch.setenv(f"{name}_CHANNEL", sid)
        monkeypatch.setenv(f"{name}_EN_CHANNEL_ID", did)
    CONFIG.reload()
    return tmp_path


class Msg:
    """Minimal stand-in for a Pyrogram message (mirrors test_admin_commands)."""

    def __init__(self, text, reply_to_message=None, from_user=None):
        self.text = text
        self.reply_to_message = reply_to_message
        self.from_user = from_user


def _data(rows):
    """Every callback_data string in a rows spec, flattened."""
    return [cd for row in rows for _label, cd in row]


def _row_data(row):
    """Every callback_data string in a single row."""
    return [cd for _label, cd in row]


# --------------------------------------------------------------------------- #
# A. Preset freshness — tied to config.py, not hand-maintained
# --------------------------------------------------------------------------- #


def test_model_presets_offer_the_configured_default(admin_env):
    """The default model must be one of the presets.

    Regression guard: after the default moved to claude-sonnet-5 the preset list
    still offered Haiku 4.5 / Sonnet 4.6 / Opus 4.8 and labelled Haiku "(default)",
    so the menu actively misinformed the operator about what was running.
    """
    values = [value for _label, value in admin_menu.MODEL_PRESETS]
    assert CONFIG.ANTHROPIC_MODEL in values


def test_no_preset_label_hardcodes_which_one_is_default(admin_env):
    # "(default)" in a label is what went stale; the active one is derived now.
    for label, _value in admin_menu.MODEL_PRESETS:
        assert "default" not in label.lower()


def test_token_and_effort_presets_bracket_the_configured_defaults(admin_env):
    assert str(CONFIG.ANTHROPIC_MAX_TOKENS) in admin_menu.TOKEN_PRESETS
    assert CONFIG.ANTHROPIC_EFFORT in admin_menu.EFFORT_PRESETS


def test_token_presets_stay_within_the_accepted_range(admin_env):
    # /setmaxtokens enforces 1..128000; a preset outside it would be a button
    # that always errors.
    for v in admin_menu.TOKEN_PRESETS:
        assert 1 <= int(v) <= 128000


def test_active_preset_is_disabled_and_others_are_not(admin_env, monkeypatch):
    monkeypatch.setattr(CONFIG, "ANTHROPIC_MODEL", "claude-sonnet-5")
    _title, rows = admin_menu.build_menu("model")
    data = _data(rows)
    assert admin_menu.DISABLED_PREFIX + "set:model:claude-sonnet-5" in data
    assert "set:model:claude-opus-5" in data  # a different preset stays tappable


def test_model_menu_offers_the_live_id_as_a_copy_button(admin_env, monkeypatch):
    # /setmodel accepts any id, so the live one often matches no preset at all.
    monkeypatch.setattr(CONFIG, "ANTHROPIC_MODEL", "claude-something-custom")
    _title, rows = admin_menu.build_menu("model")
    assert admin_menu.COPY_PREFIX + "claude-something-custom" in _data(rows)


# --------------------------------------------------------------------------- #
# B. Knobs the active model ignores are shown as ignored
# --------------------------------------------------------------------------- #


def test_temperature_menu_is_inert_on_the_modern_surface(admin_env, monkeypatch):
    monkeypatch.setattr(CONFIG, "ANTHROPIC_MODEL", "claude-sonnet-5")
    title, rows = admin_menu.build_menu("temp")
    assert "Not in use" in title
    # Every preset greyed out: on this surface temperature is not sent at all,
    # so a tappable value would promise a change that cannot happen.
    assert all(cd.startswith(admin_menu.DISABLED_PREFIX) for cd in _row_data(rows[0]))


def test_temperature_menu_is_live_on_a_sampling_model(admin_env, monkeypatch):
    monkeypatch.setattr(CONFIG, "ANTHROPIC_MODEL", "claude-haiku-4-5")
    title, rows = admin_menu.build_menu("temp")
    assert "Not in use" not in title
    assert "set:temp:0.7" in _data(rows)


def test_effort_menu_is_inert_on_a_sampling_model(admin_env, monkeypatch):
    monkeypatch.setattr(CONFIG, "ANTHROPIC_MODEL", "claude-haiku-4-5")
    title, rows = admin_menu.build_menu("effort")
    assert "Not in use" in title
    assert all(cd.startswith(admin_menu.DISABLED_PREFIX) for cd in _row_data(rows[0]))


def test_effort_menu_is_live_on_the_modern_surface(admin_env, monkeypatch):
    monkeypatch.setattr(CONFIG, "ANTHROPIC_MODEL", "claude-sonnet-5")
    monkeypatch.setattr(CONFIG, "ANTHROPIC_EFFORT", "low")
    _title, rows = admin_menu.build_menu("effort")
    assert "set:effort:high" in _data(rows)


@pytest.mark.parametrize(
    "model,temp_ignored,effort_ignored",
    [("claude-sonnet-5", True, False), ("claude-haiku-4-5", False, True)],
)
def test_ai_summary_flags_the_ignored_knob(
    admin_env, monkeypatch, model, temp_ignored, effort_ignored
):
    monkeypatch.setattr(CONFIG, "ANTHROPIC_MODEL", model)
    title, _rows = admin_menu.build_menu("ai")
    temp_line = next(ln for ln in title.splitlines() if ln.startswith("Temperature:"))
    effort_line = next(ln for ln in title.splitlines() if ln.startswith("Effort:"))
    assert ("(ignored)" in temp_line) is temp_ignored
    assert ("(ignored)" in effort_line) is effort_ignored


def test_ai_menu_links_to_the_effort_submenu(admin_env):
    _title, rows = admin_menu.build_menu("ai")
    assert "nav:effort" in _data(rows)


# --------------------------------------------------------------------------- #
# C. /seteffort
# --------------------------------------------------------------------------- #


async def test_seteffort_persists_and_applies(admin_env):
    out = await admin_commands.handle_command(Msg("/seteffort high"))
    assert out.startswith("✅")
    assert CONFIG.ANTHROPIC_EFFORT == "high"
    assert "ANTHROPIC_EFFORT=high" in (admin_env / ".env").read_text()


async def test_seteffort_rejects_unknown_values(admin_env):
    before = CONFIG.ANTHROPIC_EFFORT
    out = await admin_commands.handle_command(Msg("/seteffort turbo"))
    assert out.startswith("❌")
    assert CONFIG.ANTHROPIC_EFFORT == before


async def test_seteffort_warns_when_the_model_ignores_it(admin_env, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-haiku-4-5")
    CONFIG.reload()
    out = await admin_commands.handle_command(Msg("/seteffort medium"))
    # Still saved — it applies again if the model is switched back — but the
    # operator must not be left thinking they changed the live behaviour.
    assert out.startswith("✅")
    assert "does not take an effort setting" in out
    assert CONFIG.ANTHROPIC_EFFORT == "medium"


async def test_seteffort_has_no_warning_on_the_modern_surface(admin_env, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-sonnet-5")
    CONFIG.reload()
    out = await admin_commands.handle_command(Msg("/seteffort medium"))
    assert "does not take an effort setting" not in out


async def test_effort_button_routes_through_the_same_setter(admin_env):
    res = admin_menu.handle_callback("set:effort:high")
    assert CONFIG.ANTHROPIC_EFFORT == "high"
    assert res.alert == admin_i18n.t("alert_saved", "en")


# --------------------------------------------------------------------------- #
# D. Button chrome and its plain fallback
# --------------------------------------------------------------------------- #


def _buttons(markup):
    return [b for row in markup.inline_keyboard for b in row]


def test_disabled_button_encodes_as_a_disabled_button():
    markup = admin_menu.to_inline_markup([[("Sonnet 5", "x:set:model:claude-sonnet-5")]])
    button = _buttons(markup)[0]
    assert button.disabled is not None
    assert button.callback_data is None


def test_copy_button_encodes_the_payload():
    markup = admin_menu.to_inline_markup([[("Copy", "copy:claude-sonnet-5")]])
    button = _buttons(markup)[0]
    assert button.copy_text.text == "claude-sonnet-5"
    assert button.callback_data is None


def test_destructive_confirmations_render_red():
    from pyrogram import enums

    markup = admin_menu.to_inline_markup(
        [[("Yes, remove", "rmchok:foo"), ("No", "nav:rmch")]]
    )
    yes, no = _buttons(markup)
    assert yes.style is enums.ButtonStyle.DANGER
    assert no.style is enums.ButtonStyle.DEFAULT


def test_plain_fallback_reenables_disabled_buttons():
    """The fallback must not make an action unreachable.

    A disabled button wraps the action it would have performed, so dropping the
    chrome turns it back into an ordinary button rather than removing it —
    re-selecting the current value is harmless.
    """
    markup = admin_menu.to_inline_markup(
        [[("Sonnet 5", "x:set:model:claude-sonnet-5")]], plain=True
    )
    button = _buttons(markup)[0]
    assert button.disabled is None
    assert button.callback_data == "set:model:claude-sonnet-5"


def test_plain_fallback_drops_copy_buttons_and_empty_rows():
    # A copy button has no plain equivalent, so it goes — and a row that held
    # only copy buttons must not be sent as an empty row (Telegram rejects that).
    markup = admin_menu.to_inline_markup(
        [[("Copy", "copy:x")], [("Back", "nav:ai")]], plain=True
    )
    assert [b.callback_data for b in _buttons(markup)] == ["nav:ai"]
    assert len(markup.inline_keyboard) == 1


def test_plain_fallback_drops_styles():
    from pyrogram import enums

    markup = admin_menu.to_inline_markup([[("Yes", "rmchok:foo")]], plain=True)
    assert _buttons(markup)[0].style is enums.ButtonStyle.DEFAULT


async def test_send_with_markup_retries_without_chrome():
    attempts = []

    async def flaky(text, **kwargs):
        attempts.append(kwargs["reply_markup"])
        if len(attempts) == 1:
            raise ValueError("BUTTON_TYPE_INVALID")
        return "sent"

    rows = [[("Sonnet 5", "x:set:model:claude-sonnet-5")]]
    assert await admin_menu.send_with_markup(flaky, "hi", rows) == "sent"
    assert len(attempts) == 2
    # First attempt styled, retry plain — and the action survives the downgrade.
    assert attempts[0].inline_keyboard[0][0].disabled is not None
    assert attempts[1].inline_keyboard[0][0].callback_data == "set:model:claude-sonnet-5"


async def test_send_with_markup_does_not_retry_on_message_not_modified():
    """"Not modified" is a real outcome, not a markup problem.

    Retrying it would send the identical edit a second time and log noise on
    every re-tap of a nav button.
    """
    from pyrogram.errors import MessageNotModified

    calls = []

    async def always_not_modified(text, **kwargs):
        calls.append(kwargs)
        raise MessageNotModified

    with pytest.raises(MessageNotModified):
        await admin_menu.send_with_markup(always_not_modified, "hi", [[("a", "nav:ai")]])
    assert len(calls) == 1


def test_reply_keyboard_stays_open_and_hints_the_input_box():
    markup = admin_menu.to_reply_markup(admin_menu.build_reply_keyboard("en"), "en")
    assert markup.is_persistent is True
    assert markup.placeholder == admin_i18n.t("kbd_placeholder", "en")


# --------------------------------------------------------------------------- #
# E. Native command menu
# --------------------------------------------------------------------------- #


async def test_every_published_command_actually_dispatches(admin_env):
    """A "/" entry that answers "unknown command" is worse than no entry.

    ``/menu`` is the one exception: it is served by the Pyrogram dispatcher
    (it answers with a keyboard, not text) rather than by ``handle_command``.
    """
    unknown = admin_i18n.t("unknown_cmd", "en", cmd="")[:10]
    for name, _key in admin_commands.COMMAND_SPECS:
        if name == "menu":
            assert "/menu" in admin_menu.BUTTON_KEYS.values()
            continue
        out = await admin_commands.handle_command(Msg(f"/{name}"))
        assert not out.startswith(unknown), f"/{name} is published but not handled"


def test_command_names_satisfy_telegrams_rules():
    # 1-32 chars, lowercase letters/digits/underscore only.
    for name, _key in admin_commands.COMMAND_SPECS:
        assert 1 <= len(name) <= 32
        assert name.islower() and name.replace("_", "").isalnum()


@pytest.mark.parametrize("lang", admin_i18n.LOCALES)
def test_command_descriptions_are_present_and_within_the_cap(lang):
    for command in admin_commands.build_bot_commands(lang):
        assert command.description, f"{command.command} has no description in {lang}"
        # A missing key falls back to the raw key name; catch that too.
        assert not command.description.startswith("cmd_desc_")
        assert len(command.description) <= 256


def test_command_list_covers_every_writable_setting():
    """The knobs that change relay behaviour must be discoverable from "/"."""
    names = {name for name, _ in admin_commands.COMMAND_SPECS}
    assert {"setmodel", "seteffort", "setmaxtokens", "settemp"} <= names


class _FakePyroCommands:
    def __init__(self, fail=False):
        self.commands = []
        self.menu_buttons = []
        self._fail = fail

    async def set_bot_commands(self, commands, scope=None, language_code=""):
        if self._fail:
            raise RuntimeError("no network")
        self.commands.append((commands, scope))
        return True

    async def set_chat_menu_button(self, chat_id=None, menu_button=None):
        self.menu_buttons.append((chat_id, menu_button))
        return True


async def test_commands_are_published_per_admin_chat(admin_env):
    """Scoped per chat, never globally — the command list maps the whole
    control surface, so a stranger who DMs the bot must not be handed it."""
    from pyrogram.types import BotCommandScopeChat, MenuButtonCommands

    fake = _FakePyroCommands()
    assert await admin_commands.publish_admin_commands(fake) == 2
    assert len(fake.commands) == 2
    scopes = [scope for _cmds, scope in fake.commands]
    assert all(isinstance(s, BotCommandScopeChat) for s in scopes)
    assert sorted(s.chat_id for s in scopes) == [111, 222]
    assert all(isinstance(b, MenuButtonCommands) for _c, b in fake.menu_buttons)


async def test_publishing_commands_never_breaks_startup(admin_env, caplog):
    """A bot that can't set its command menu must still relay messages."""
    fake = _FakePyroCommands(fail=True)
    with caplog.at_level(logging.WARNING, logger="ADMIN"):
        assert await admin_commands.publish_admin_commands(fake) == 0
    assert any("command menu" in r.getMessage() for r in caplog.records)


async def test_commands_are_published_in_the_admins_language(admin_env):
    admin_prefs.set_lang(111, "be")
    fake = _FakePyroCommands()
    await admin_commands.publish_commands_for(fake, 111)
    descriptions = [c.description for c in fake.commands[0][0]]
    assert admin_i18n.t("cmd_desc_status", "be") in descriptions


# --------------------------------------------------------------------------- #
# F. Native chat picker feeding the add-channel wizard
# --------------------------------------------------------------------------- #


class FakePyro:
    def __init__(self):
        self.msg_handlers = []
        self.cb_handlers = []

    def on_message(self, flt=None, group=0):
        def deco(fn):
            self.msg_handlers.append((flt, group, fn))
            return fn

        return deco

    def on_callback_query(self, flt=None, group=0):
        def deco(fn):
            self.cb_handlers.append((flt, group, fn))
            return fn

        return deco


class _RecordingMsg:
    """A DM stand-in that records replies and the keyboard attached to each."""

    def __init__(self, uid, *, text=None, chat_shared=None):
        self.from_user = types.SimpleNamespace(id=uid)
        self.text = text
        self.reply_to_message = None
        self.users_shared = None
        self.chat_shared = chat_shared
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append((text, kwargs.get("reply_markup")))


def _dispatcher():
    fake = FakePyro()
    admin_commands.register_admin_handlers(fake)
    return next(fn for _f, g, fn in fake.msg_handlers if g == 0)


def _shared(chat_id, title="Мой канал"):
    return types.SimpleNamespace(
        button_id=admin_menu.REQUEST_CHANNEL_BUTTON_ID,
        chat=types.SimpleNamespace(id=chat_id, title=title),
    )


def _is_picker(markup):
    first = markup.keyboard[0][0] if markup is not None else None
    return getattr(first, "request_chat", None) is not None


async def test_chat_picker_walks_the_wizard_to_a_committed_pair(admin_env):
    """A picked channel must travel the same path a typed id does."""
    dispatch = _dispatcher()
    admin_wizard.start(111)
    assert admin_wizard.feed(111, "mychan") and admin_wizard.current_step(111) == "src"

    src = _RecordingMsg(111, chat_shared=_shared(-1001111111111))
    await dispatch(object(), src)
    assert admin_wizard.current_step(111) == "dst"
    text, markup = src.replies[-1]
    assert "-1001111111111" in text  # echo what was picked, ids are unmemorable
    assert _is_picker(markup), "the destination step needs the picker too"

    dst = _RecordingMsg(111, chat_shared=_shared(-1002222222222))
    await dispatch(object(), dst)
    assert admin_wizard.current_step(111) is None
    assert CONFIG.channels["mychan"].channel_id == -1001111111111
    assert CONFIG.channels["mychan_en"].channel_id == -1002222222222
    # The one-shot picker keyboard is replaced by the normal menu once done.
    assert not _is_picker(dst.replies[-1][1])


async def test_typed_ids_still_work_and_get_the_picker_keyboard(admin_env):
    """The picker is an addition, not a replacement — pasting an id still works."""
    dispatch = _dispatcher()
    admin_wizard.start(111)
    await dispatch(object(), _RecordingMsg(111, text="typedchan"))
    assert admin_wizard.current_step(111) == "src"

    msg = _RecordingMsg(111, text="-1003333333333")
    await dispatch(object(), msg)
    assert admin_wizard.current_step(111) == "dst"
    assert _is_picker(msg.replies[-1][1])


async def test_chat_shared_outside_the_wizard_is_ignored(admin_env):
    # No pending wizard means no field is waiting for it; acting on it would
    # write a channel pair nobody asked for.
    dispatch = _dispatcher()
    msg = _RecordingMsg(111, chat_shared=_shared(-1004444444444))
    await dispatch(object(), msg)
    assert msg.replies == []
    assert "mychan" not in CONFIG.channels


async def test_picker_cancel_button_escapes_the_wizard(admin_env):
    """The picker's Cancel sends a *label*, not a command.

    Without a label→command mapping it would be swallowed as the wizard's next
    answer, leaving the operator stuck in a flow they just tried to leave.
    """
    dispatch = _dispatcher()
    admin_wizard.start(111)
    admin_wizard.feed(111, "mychan")
    cancel_label = admin_i18n.t("btn_cancel", "en")
    assert admin_menu.resolve_button_label(cancel_label) == "/cancel"

    msg = _RecordingMsg(111, text=cancel_label)
    await dispatch(object(), msg)
    assert admin_wizard.current_step(111) is None
    assert not _is_picker(msg.replies[-1][1]), "cancelling restores the main menu"


def test_channel_picker_only_offers_channels_the_bot_can_read(admin_env):
    """``bot_is_member`` is the point of the picker, not decoration.

    /addchannel could only warn *after* the fact that the bot must already be in
    the source channel; filtering the picker makes that mistake unmakeable.
    """
    markup = admin_menu.build_channel_picker_keyboard("en")
    request = markup.keyboard[0][0].request_chat
    assert request.chat_is_channel is True
    assert request.bot_is_member is True
    assert request.button_id == admin_menu.REQUEST_CHANNEL_BUTTON_ID


# --------------------------------------------------------------------------- #
# G. Degrading onto an older kurigram
#
# Production installs dependencies by hand and ran the new menu code against
# kurigram 2.2.23, which has no CopyTextButton. The first version of this module
# imported that type unconditionally inside `_to_button`, so the `plain=True`
# fallback re-entered the same import and raised the *identical* ImportError it
# existed to catch — the admin saw nothing at all.
#
# `_accepts` is tested directly; the rest simulate an old kurigram by stubbing
# `pyrogram.types` and/or clearing the HAS_* flags. The stub is what gives these
# teeth: a function-level `from pyrogram.types import CopyTextButton` creeping
# back in fails them even though this container's kurigram *has* the type.
# --------------------------------------------------------------------------- #


def _kurigram_without(*names):
    """A ``pyrogram.types`` stand-in missing ``names``, like an older kurigram."""
    import pyrogram.types as real

    stub = types.ModuleType("pyrogram.types")
    for key, value in vars(real).items():
        if key not in names:
            setattr(stub, key, value)
    return stub


class _Old:
    """A constructor that predates a keyword argument."""

    def __init__(self, text):
        self.text = text


class _New:
    def __init__(self, text, style=None):
        self.text, self.style = text, style


def test_accepts_detects_a_missing_keyword():
    # The probe behind every flag below: a type existing does not mean its
    # constructor takes the newer argument.
    assert admin_menu._accepts(_New, "style") is True
    assert admin_menu._accepts(_Old, "style") is False


def test_accepts_survives_an_unintrospectable_constructor():
    assert admin_menu._accepts(object, "style") in (True, False)  # must not raise


def test_this_kurigram_supports_everything(admin_env):
    """Sanity: the pinned 2.2.26 has it all, so the tests below really are
    testing the degraded path and not silently passing on a stripped runtime."""
    assert admin_menu.HAS_COPY_BUTTON
    assert admin_menu.HAS_DISABLED_BUTTON
    assert admin_menu.HAS_BUTTON_STYLE
    assert admin_menu.HAS_CHAT_PICKER
    assert "copy=yes" in admin_menu.capability_summary()


def _strip(monkeypatch, *flags):
    for flag in flags:
        monkeypatch.setattr(admin_menu, flag, False)


def test_markup_builds_when_the_button_types_are_absent(monkeypatch):
    """The reported crash, as a test.

    Not `plain=True` — this is the *normal* path on an old kurigram, which is
    exactly the case the original fallback never considered.
    """
    _strip(monkeypatch, "HAS_COPY_BUTTON", "HAS_DISABLED_BUTTON", "HAS_BUTTON_STYLE")
    rows = [
        [("Sonnet 5", "x:set:model:claude-sonnet-5")],
        [("Copy", "copy:claude-sonnet-5")],
        [("Yes, remove", "rmchok:foo"), ("No", "nav:rmch")],
    ]
    with patch.dict(
        sys.modules,
        {"pyrogram.types": _kurigram_without("CopyTextButton", "DisabledButton")},
    ):
        markup = admin_menu.to_inline_markup(rows)

    data = [b.callback_data for row in markup.inline_keyboard for b in row]
    # The disabled entry comes back as the action it wrapped — still reachable.
    assert "set:model:claude-sonnet-5" in data
    assert "rmchok:foo" in data and "nav:rmch" in data
    # The copy button has no equivalent, so its row disappears rather than
    # being sent empty (Telegram rejects an empty row).
    assert len(markup.inline_keyboard) == 2


def test_no_unsupported_kwarg_reaches_the_constructor(monkeypatch):
    # An old InlineKeyboardButton has no `style=`; passing it is a TypeError even
    # though the class itself imports fine.
    _strip(monkeypatch, "HAS_BUTTON_STYLE")
    captured = {}

    real = admin_menu.pyro_types.InlineKeyboardButton

    def spy(*args, **kwargs):
        captured.update(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(admin_menu.pyro_types, "InlineKeyboardButton", spy)
    admin_menu.to_inline_markup([[("Yes", "rmchok:foo")]])
    assert "style" not in captured


def test_reply_keyboard_skips_hints_when_unsupported(monkeypatch):
    _strip(monkeypatch, "HAS_KEYBOARD_HINTS")
    markup = admin_menu.to_reply_markup(admin_menu.build_reply_keyboard("en"), "en")
    assert markup.is_persistent is None
    assert markup.placeholder is None
    assert markup.keyboard, "the keyboard itself must still render"


def test_channel_picker_is_none_without_support(monkeypatch):
    _strip(monkeypatch, "HAS_CHAT_PICKER")
    assert admin_menu.build_channel_picker_keyboard("en") is None


async def test_wizard_does_not_promise_a_picker_it_cannot_show(
    admin_env, monkeypatch
):
    """Falling back to typed ids is fine; advertising a missing button is not."""
    _strip(monkeypatch, "HAS_CHAT_PICKER")
    dispatch = _dispatcher()
    admin_wizard.start(111)
    await dispatch(object(), _RecordingMsg(111, text="nopicker"))

    msg = _RecordingMsg(111, text="-1005555555555")
    await dispatch(object(), msg)
    text, markup = msg.replies[-1]
    assert markup is None or not _is_picker(markup)
    assert admin_i18n.t("wiz_pick_hint", "en") not in text
    # ...and the typed id was still accepted.
    assert admin_wizard.current_step(111) == "dst"


async def test_message_is_delivered_even_when_no_markup_works():
    """The operator's text matters more than the buttons.

    "Saw nothing at all" was the actual symptom of the production crash, so the
    last tier drops the markup rather than the message.
    """
    attempts = []

    async def send(text, **kwargs):
        attempts.append(kwargs["reply_markup"])
        if kwargs["reply_markup"] is not None:
            raise ValueError("BUTTON_TYPE_INVALID")
        return "delivered"

    result = await admin_menu.send_with_markup(send, "status", [[("a", "nav:ai")]])
    assert result == "delivered"
    assert attempts[-1] is None
    assert len(attempts) == 3  # styled, plain, bare


async def test_startup_survives_missing_command_types(admin_env, caplog):
    """The worse latent bug: these imports sat OUTSIDE the try, and this runs at
    startup right after pyro.start() — so on an old kurigram the bot would not
    have started at all."""
    fake = _FakePyroCommands()
    with patch.dict(
        sys.modules,
        {"pyrogram.types": _kurigram_without("BotCommandScopeChat", "MenuButtonCommands")},
    ):
        with caplog.at_level(logging.WARNING, logger="ADMIN"):
            published = await admin_commands.publish_admin_commands(fake)

    assert published == 0, "must report failure, not raise"
    assert fake.commands == []
    assert any("command menu" in r.getMessage() for r in caplog.records)
