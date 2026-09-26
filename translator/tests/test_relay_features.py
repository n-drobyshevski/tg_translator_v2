"""Tests for relay coverage: reply links, delete sync, live photos, polls,
checklists, and the custom-emoji fallback.

Handler-level tests reuse the harness from ``test_bot_error_handling``; sender
tests patch ``httpx.AsyncClient.post`` like ``test_telegram_sender`` does.
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pyrogram import enums

from translator import bot, config
from translator.db import connection, events_dao
from translator.services.event_logger import EventRecorder
from translator.services.telegram_sender import TelegramSender, record_sent
from translator.tests.test_bot_error_handling import (
    _FakeChat,
    _FakeMsg,
    _MediaStubs,
    _wire,
)
from translator.utils import custom_emoji
from translator.utils.message_utils import (
    build_poll_request,
    checklist_to_html,
    get_media_info,
    poll_source_fields,
)
from translator.utils.translation_utils import PLAIN_SYSTEM, translate_plain


def _chat():
    return _FakeChat(1, "Channel One", "chan1")


# --------------------------------------------------------------------------- #
# Reply links
# --------------------------------------------------------------------------- #


class _TextSender(_MediaStubs):
    def __init__(self):
        self.calls = []

    async def send_message(self, text, recorder, reply_to_message_id=None):
        self.calls.append((text, reply_to_message_id))
        return True


async def test_reply_in_source_becomes_reply_to_the_translation_head(monkeypatch):
    sender = _TextSender()
    handlers = _wire(monkeypatch, sender)
    monkeypatch.setattr(bot.CONFIG, "get_destination_msg_ids", lambda chat, mid: [900, 901])
    msg = _FakeMsg(10, _chat())
    msg.reply_to_message_id = 5
    await handlers["message"](None, msg)
    assert sender.calls == [("translated", 900)]


async def test_non_reply_and_unmapped_reply_send_unlinked(monkeypatch):
    sender = _TextSender()
    handlers = _wire(monkeypatch, sender)
    monkeypatch.setattr(bot.CONFIG, "get_destination_msg_ids", lambda chat, mid: [])
    plain = _FakeMsg(10, _chat())
    orphan = _FakeMsg(11, _chat())
    orphan.reply_to_message_id = 4
    await handlers["message"](None, plain)
    await handlers["message"](None, orphan)
    assert [r for _, r in sender.calls] == [None, None]


async def test_a_broken_lookup_never_blocks_the_relay(monkeypatch):
    sender = _TextSender()
    handlers = _wire(monkeypatch, sender)

    def boom(chat, mid):
        raise RuntimeError("db locked")

    monkeypatch.setattr(bot.CONFIG, "get_destination_msg_ids", boom)
    msg = _FakeMsg(10, _chat())
    msg.reply_to_message_id = 5
    await handlers["message"](None, msg)
    assert sender.calls == [("translated", None)]


# --------------------------------------------------------------------------- #
# Live photos
# --------------------------------------------------------------------------- #


def test_live_photo_is_detected_before_its_still_photo():
    msg = SimpleNamespace(
        live_photo=SimpleNamespace(file_id="vid", file_size=10),
        photo=SimpleNamespace(file_id="still", file_size=10),
        animation=None, voice=None, video_note=None, audio=None, document=None, video=None,
    )
    assert get_media_info(msg, 20 * 1024 * 1024) == ("vid", 10, "live_photo")


class _LiveSender(_MediaStubs):
    def __init__(self, live_ok=True):
        self.live_ok = live_ok
        self.calls = []

    async def send_live_photo_message(self, video, photo, caption, recorder, reply_to_message_id=None):
        self.calls.append(("live", video, photo, caption))
        return self.live_ok

    async def send_photo_message(self, photo, caption, recorder, reply_to_message_id=None):
        self.calls.append(("photo", photo, caption))
        return True

    async def send_message(self, text, recorder, reply_to_message_id=None):
        self.calls.append(("text", text))
        return True


def _live_msg():
    msg = _FakeMsg(10, _chat())
    msg.photo = SimpleNamespace(file_id="still")
    return msg


async def test_live_photo_relays_through_send_live_photo(monkeypatch):
    sender = _LiveSender()
    handlers = _wire(
        monkeypatch, sender, media=("vid", 10, "live_photo"),
        meta={"file": {}, "file_download_link": "x"}, translated="<b>Cap.</b>",
    )
    await handlers["message"](None, _live_msg())
    assert sender.calls == [("live", "vid", "still", "<b>Cap.</b>")]


async def test_refused_live_photo_falls_back_to_the_still(monkeypatch):
    sender = _LiveSender(live_ok=False)
    handlers = _wire(
        monkeypatch, sender, media=("vid", 10, "live_photo"),
        meta={"file": {}, "file_download_link": "x"}, translated="<b>Cap.</b>",
    )
    await handlers["message"](None, _live_msg())
    assert sender.calls[-1] == ("photo", "still", "<b>Cap.</b>")


async def test_live_photo_in_an_album_carries_its_still(monkeypatch):
    calls = {}

    class _Sender(_MediaStubs):
        async def send_media_group(self, album, caption, recorder, reply_to_message_id=None):
            calls["album"] = album
            return True

        async def send_message(self, *a, **kw):
            return True

    parts = []
    for i in (1, 2):
        m = _FakeMsg(i, _chat())
        m.media_group_id = "g"
        m.photo = SimpleNamespace(file_id=f"still{i}")
        m.text = "подпись" if i == 1 else None
        parts.append(m)
    media = {1: ("vid1", 10, "live_photo"), 2: ("p2", 10, "photo")}
    handlers = _wire(monkeypatch, _Sender(), meta={"file": {}, "file_download_link": "x"})
    monkeypatch.setattr(bot, "get_media_info", lambda msg, max_size: media[msg.id])
    monkeypatch.setenv("MEDIA_GROUP_DEBOUNCE", "0.02")
    for p in parts:
        await handlers["message"](None, p)
    await asyncio.sleep(0.15)
    assert calls["album"] == [("live_photo", "vid1", "still1"), ("photo", "p2")]


# --------------------------------------------------------------------------- #
# Polls
# --------------------------------------------------------------------------- #


def _poll(**kw):
    base = dict(
        question=SimpleNamespace(text="Какой день?"),
        options=[SimpleNamespace(text="Понедельник"), SimpleNamespace(text="Вторник")],
        type=enums.PollType.REGULAR,
        correct_option_ids=None,
        allows_multiple_answers=False,
        allows_revoting=None,
        members_only=None,
        country_codes=None,
        description=None,
        explanation=None,
        close_date=None,
        is_closed=False,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_poll_fields_and_request_basics():
    poll = _poll(description=SimpleNamespace(text="Опрос"))
    fields = poll_source_fields(poll)
    assert fields == {
        "question": "Какой день?",
        "options": ["Понедельник", "Вторник"],
        "description": "Опрос",
        "explanation": "",
    }
    body = build_poll_request(
        poll, {"question": "Which day?", "options": ["Mon", "Tue"], "description": "Poll",
               "explanation": ""}, now_ts=0,
    )
    assert body == {
        "question": "Which day?",
        "options": [{"text": "Mon"}, {"text": "Tue"}],
        "is_anonymous": True,
        "type": "regular",
        "description": "Poll",
    }


def test_quiz_keeps_its_answer_and_explanation():
    poll = _poll(type=enums.PollType.QUIZ, correct_option_ids=[1])
    body = build_poll_request(
        poll, {"question": "Q", "options": ["a", "b"], "description": "", "explanation": "Why"},
        now_ts=0,
    )
    assert body["type"] == "quiz" and body["correct_option_ids"] == [1]
    assert body["explanation"] == "Why"


def test_quiz_without_a_visible_answer_goes_out_as_a_regular_poll():
    poll = _poll(type=enums.PollType.QUIZ, correct_option_ids=[])
    body = build_poll_request(
        poll, {"question": "Q", "options": ["a"], "description": "", "explanation": "x"}, now_ts=0
    )
    assert body["type"] == "regular" and "correct_option_ids" not in body
    assert "explanation" not in body


def test_poll_limits_and_close_date_window():
    now = datetime(2026, 9, 1, tzinfo=timezone.utc)
    soon = _poll(close_date=now + timedelta(hours=1))
    past = _poll(close_date=now - timedelta(hours=1))
    tr = {"question": "q" * 400, "options": ["o" * 150], "description": "", "explanation": ""}
    body = build_poll_request(soon, tr, now.timestamp())
    assert len(body["question"]) == 300 and body["question"].endswith("…")
    assert len(body["options"][0]["text"]) == 100
    assert body["close_date"] == int((now + timedelta(hours=1)).timestamp())
    assert "close_date" not in build_poll_request(past, tr, now.timestamp())


async def test_poll_is_translated_field_by_field_and_sent(monkeypatch):
    sent = {}

    class _Sender(_MediaStubs):
        async def send_poll(self, body, recorder, reply_to_message_id=None):
            sent["body"] = body
            sent["reply_to"] = reply_to_message_id
            return True

    handlers = _wire(monkeypatch, _Sender())
    translated_inputs = []

    async def fake_plain(client, text, usage_out=None):
        translated_inputs.append(text)
        usage_out.update(input_tokens=10, output_tokens=2, model_used="claude-sonnet-5")
        return f"EN:{text}"

    monkeypatch.setattr(bot, "translate_plain", fake_plain)
    msg = _FakeMsg(10, _chat())
    msg.text = None
    msg.poll = _poll()
    await handlers["message"](None, msg)
    assert sent["body"]["question"] == "EN:Какой день?"
    assert sent["body"]["options"] == [{"text": "EN:Понедельник"}, {"text": "EN:Вторник"}]
    # Empty fields (description / explanation) cost no API call.
    assert sorted(translated_inputs) == sorted(["Какой день?", "Понедельник", "Вторник"])


async def test_closing_a_source_poll_closes_the_relayed_one(monkeypatch):
    sender = _MediaStubs()
    sender.stop_poll = AsyncMock(return_value=True)
    handlers = _wire(monkeypatch, sender)
    monkeypatch.setattr(bot.CONFIG, "get_destination_msg_ids", lambda chat, mid: [900])
    msg = _FakeMsg(10, _chat())
    msg.poll = _poll(is_closed=True)
    await handlers["edit"](None, msg)
    sender.stop_poll.assert_awaited_once_with(111, 900)

    sender.stop_poll.reset_mock()
    msg.poll = _poll(is_closed=False)  # a vote-count change is not ours to mirror
    await handlers["edit"](None, msg)
    sender.stop_poll.assert_not_awaited()


async def test_translate_plain_uses_the_plain_prompt_and_strips_markup():
    captured = {}

    class FakeMessages:
        @staticmethod
        def create(**kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                stop_reason="end_turn",
                content=[SimpleNamespace(type="text", text="<b>Mon &amp; Tue</b>\n")],
            )

    class FakeClient:
        messages = FakeMessages

    out = await translate_plain(FakeClient, "Пн и Вт")
    assert out == "Mon & Tue"
    assert captured["system"][0]["text"] == PLAIN_SYSTEM
    assert captured["messages"][0]["content"] == "Пн и Вт"


# --------------------------------------------------------------------------- #
# Checklists
# --------------------------------------------------------------------------- #


def test_checklist_renders_as_escaped_text():
    checklist = SimpleNamespace(
        title="Дела <важно>",
        tasks=[
            SimpleNamespace(text="Купить хлеб", completed_by=SimpleNamespace(id=1), completion_date=None),
            SimpleNamespace(text="A & B", completed_by=None, completion_date=None),
        ],
    )
    assert checklist_to_html(checklist) == (
        "<b>Дела &lt;важно&gt;</b>\n✅ Купить хлеб\n⬜️ A &amp; B"
    )


async def test_checklist_post_is_relayed_as_translated_text(monkeypatch):
    sender = _TextSender()
    handlers = _wire(monkeypatch, sender)
    seen = {}

    async def fake_translate(client, payload, usage=None):
        seen["html"] = payload["Html"]
        return "<b>Chores</b>"

    monkeypatch.setattr(bot, "translate_html", fake_translate)
    msg = _FakeMsg(10, _chat())
    msg.text = None
    msg.checklist = SimpleNamespace(
        title="Дела", tasks=[SimpleNamespace(text="Хлеб", completed_by=None, completion_date=None)]
    )
    await handlers["message"](None, msg)
    assert "<b>Дела</b>" in seen["html"] and "⬜️ Хлеб" in seen["html"]
    assert sender.calls == [("<b>Chores</b>", None)]


# --------------------------------------------------------------------------- #
# Delete sync
# --------------------------------------------------------------------------- #


def _deleted(*pairs):
    return [SimpleNamespace(id=mid, chat=SimpleNamespace(id=chat)) for chat, mid in pairs]


@pytest.fixture
def delete_env(monkeypatch):
    sender = _MediaStubs()
    sender.delete_messages = AsyncMock(return_value=(True, None))
    handlers = _wire(monkeypatch, sender)
    monkeypatch.setattr(bot.CONFIG, "get_source_channel_ids", lambda: {1})
    monkeypatch.setattr(
        bot.CONFIG, "get_channel_name", lambda c: {1: "src1", 111: "dest1"}.get(c)
    )
    mapping = {(1, 10): [900, 901, 902], (1, 11): []}
    monkeypatch.setattr(bot.CONFIG, "get_destination_msg_ids", lambda c, m: mapping.get((c, m), []))
    alert = AsyncMock()
    monkeypatch.setattr(bot, "send_alert", alert)
    monkeypatch.delenv("SYNC_DELETES", raising=False)
    return handlers, sender, alert


async def test_deleting_a_source_post_deletes_every_part_of_its_translation(delete_env):
    handlers, sender, alert = delete_env
    # One mapped post, one unmapped album part, and a deletion in another chat.
    await handlers["deleted"](None, _deleted((1, 10), (1, 11), (777, 10)))
    sender.delete_messages.assert_awaited_once_with(111, [900, 901, 902])
    alert.assert_not_awaited()


async def test_delete_sync_can_be_switched_off(delete_env, monkeypatch):
    handlers, sender, _ = delete_env
    monkeypatch.setenv("SYNC_DELETES", "0")
    await handlers["deleted"](None, _deleted((1, 10)))
    sender.delete_messages.assert_not_awaited()


async def test_failed_delete_sync_alerts_the_admin(delete_env):
    handlers, sender, alert = delete_env
    sender.delete_messages.return_value = (False, "message can't be deleted")
    await handlers["deleted"](None, _deleted((1, 10)))
    alert.assert_awaited_once()
    assert "Delete sync failed" in alert.await_args.args[0]


# --------------------------------------------------------------------------- #
# Sender: ids, replies, live photo, poll, delete, emoji fallback
# --------------------------------------------------------------------------- #


def _resp(status=200, result=None, description=None):
    r = MagicMock()
    r.status_code = status
    r.text = description or ""
    r.json.return_value = (
        {"ok": True, "result": result} if status == 200 else {"ok": False, "description": description}
    )
    return r


def _recorder():
    rec = EventRecorder()
    rec.set(dest_channel_id=-100500, dest_channel_name="test")
    return rec


def test_record_sent_appends_in_order():
    rec = EventRecorder()
    record_sent(rec, 5)
    record_sent(rec, 6, None, 7)
    assert rec.get("dest_message_ids") == "5,6,7"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.post")
async def test_every_chunk_of_a_long_message_is_recorded(mock_post):
    mock_post.side_effect = [_resp(result={"message_id": 11}), _resp(result={"message_id": 12})]
    sender = TelegramSender()
    rec = _recorder()
    assert await sender.send_message("A" * (sender.MAX_MESSAGE_LENGTH + 10), rec, 7)
    assert rec.get("dest_message_ids") == "11,12"
    body = mock_post.call_args_list[0].kwargs["json"]
    assert body["reply_parameters"] == {"message_id": 7, "allow_sending_without_reply": True}


@pytest.mark.asyncio
@patch("httpx.AsyncClient.post")
async def test_album_records_all_ids_and_replies(mock_post):
    mock_post.return_value = _resp(result=[{"message_id": 21}, {"message_id": 22}])
    sender = TelegramSender()
    rec = _recorder()
    items = [("live_photo", "vid", "still"), ("photo", "p")]
    assert await sender.send_media_group(items, "cap", rec, 7)
    assert rec.get("dest_message_id") == 21 and rec.get("dest_message_ids") == "21,22"
    data = mock_post.call_args.kwargs["data"]
    media = json.loads(data["media"])
    assert media[0] == {"type": "live_photo", "media": "vid", "photo": "still",
                        "caption": "cap", "parse_mode": "HTML"}
    assert json.loads(data["reply_parameters"])["message_id"] == 7


@pytest.mark.asyncio
@patch(
    "translator.services.telegram_sender.get_channel_config",
    return_value=(SimpleNamespace(channel_id=-100500), None),
)
@patch("httpx.AsyncClient.post")
async def test_live_photo_send_shape(mock_post, _cfg):
    mock_post.return_value = _resp(result={"message_id": 31})
    sender = TelegramSender()
    rec = _recorder()
    assert await sender.send_live_photo_message("vid", "still", "cap", rec, reply_to_message_id=9)
    url = mock_post.call_args.args[0]
    data = mock_post.call_args.kwargs["data"]
    assert url.endswith("/sendLivePhoto")
    assert data["live_photo"] == "vid" and data["photo"] == "still" and data["caption"] == "cap"
    assert json.loads(data["reply_parameters"])["message_id"] == 9
    assert rec.get("dest_message_ids") == "31"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.post")
async def test_poll_send_and_stop(mock_post):
    mock_post.return_value = _resp(result={"message_id": 41})
    sender = TelegramSender()
    rec = _recorder()
    body = {"question": "Q", "options": [{"text": "a"}], "is_anonymous": True}
    assert await sender.send_poll(body, rec)
    sent = mock_post.call_args.kwargs["json"]
    assert sent["chat_id"] == -100500 and sent["question"] == "Q"
    assert rec.get("dest_message_ids") == "41"
    mock_post.return_value = _resp(result={})
    assert await sender.stop_poll(-100500, "41")
    assert mock_post.call_args.kwargs["json"] == {"chat_id": -100500, "message_id": 41}


@pytest.mark.asyncio
@patch("httpx.AsyncClient.post")
async def test_delete_messages_batches_by_100(mock_post):
    mock_post.return_value = _resp(result=True)
    ok, err = await TelegramSender().delete_messages(-1, list(range(1, 151)))
    assert ok and err is None
    batches = [c.kwargs["json"]["message_ids"] for c in mock_post.call_args_list]
    assert [len(b) for b in batches] == [100, 50]


@pytest.mark.asyncio
@patch("httpx.AsyncClient.post")
async def test_refused_custom_emoji_are_retried_plain_and_remembered(mock_post, monkeypatch):
    monkeypatch.delenv("PRESERVE_CUSTOM_EMOJI", raising=False)
    mock_post.side_effect = [
        _resp(400, description="Bad Request: DOCUMENT_INVALID"),
        _resp(result={"message_id": 51}),
    ]
    rec = _recorder()
    text = 'Hi <tg-emoji emoji-id="5368">👍</tg-emoji>'
    assert await TelegramSender().send_message(text, rec)
    first, second = (c.kwargs["json"]["text"] for c in mock_post.call_args_list)
    assert "<tg-emoji" in first and second == "Hi 👍"
    assert custom_emoji.should_preserve() is False  # flattened up front from now on


@pytest.mark.asyncio
@patch("httpx.AsyncClient.post")
async def test_unrelated_rejections_are_not_retried(mock_post):
    mock_post.return_value = _resp(400, description="Bad Request: chat not found")
    assert not await TelegramSender().send_message("plain", _recorder())
    assert mock_post.call_count == 1
    assert custom_emoji.should_preserve() is True


def test_emoji_modes(monkeypatch):
    monkeypatch.setenv("PRESERVE_CUSTOM_EMOJI", "0")
    assert custom_emoji.mode() == "off" and not custom_emoji.should_preserve()
    monkeypatch.setenv("PRESERVE_CUSTOM_EMOJI", "1")
    custom_emoji.mark_refused("x")  # remembered only in auto mode
    assert custom_emoji.should_preserve()
    monkeypatch.setenv("PRESERVE_CUSTOM_EMOJI", "auto")
    custom_emoji.mark_refused("x")
    assert not custom_emoji.should_preserve()
    custom_emoji._refused_at -= custom_emoji.COOLDOWN  # a day later: try again
    assert custom_emoji.should_preserve()


def test_flatten_body_covers_album_json():
    media = json.dumps([{"caption": 'a <tg-emoji emoji-id="1">🔥</tg-emoji>'}])
    flat = custom_emoji.flatten_body({"media": media, "chat_id": 1})
    assert json.loads(flat["media"])[0]["caption"] == "a 🔥"
    assert custom_emoji.flatten_body({"text": "plain"}) is None


# --------------------------------------------------------------------------- #
# Event store: every destination id
# --------------------------------------------------------------------------- #


@pytest.fixture
def sqlite_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "events.db"))
    monkeypatch.setattr(config, "STORAGE_BACKEND", "sqlite")
    monkeypatch.setattr(connection, "_initialized", False)
    yield


def test_dest_ids_lookup_prefers_the_full_list(sqlite_db):
    events_dao.insert_event({"source_channel_id": "-1", "message_id": "5",
                             "dest_message_id": "52", "dest_message_ids": "50,51,52"})
    # A later edit row carries only the single id; it must not hide the list.
    events_dao.insert_event({"source_channel_id": "-1", "message_id": "5",
                             "event_type": "edit", "dest_message_id": "52"})
    assert events_dao.get_destination_msg_ids(-1, 5) == [50, 51, 52]
    assert config.CONFIG.get_destination_msg_ids(-1, 5) == [50, 51, 52]


def test_dest_ids_fall_back_to_the_legacy_single_id(sqlite_db):
    events_dao.insert_event({"source_channel_id": "-1", "message_id": "6", "dest_message_id": "60"})
    assert events_dao.get_destination_msg_ids(-1, 6) == [60]
    assert events_dao.get_destination_msg_ids(-1, 7) == []


def test_existing_databases_gain_the_new_column(sqlite_db):
    with connection.get_conn() as conn:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(events)")}
    assert "dest_message_ids" in cols


@pytest.mark.asyncio
@patch("httpx.AsyncClient.post")
async def test_not_modified_edit_is_never_retried_flattened(mock_post):
    mock_post.return_value = _resp(400, description="Bad Request: message is not modified")
    body = {"chat_id": 1, "text": 'x <tg-emoji emoji-id="1">🔥</tg-emoji>'}
    ok, _r, _err = await TelegramSender()._post_telegram("https://api/editMessageText", json=body)
    assert not ok and mock_post.call_count == 1
    assert custom_emoji.should_preserve() is True
