"""Tests for the SQLite event store (translator.db) and its EventRecorder wiring.

These avoid the network/Telegram/Anthropic deps: they exercise the DAO, the
migrator, and EventRecorder's finalize path against a throwaway temp database.
"""

import json

import pytest

from translator import config
from translator.db import connection, events_dao, migrate
from translator.services.event_logger import EventRecorder


@pytest.fixture
def sqlite_db(tmp_path, monkeypatch):
    """Point the data layer at a fresh temp DB on the SQLite backend."""
    db = tmp_path / "events.db"
    monkeypatch.setattr(config, "DB_PATH", str(db))
    monkeypatch.setattr(config, "STORAGE_BACKEND", "sqlite")
    # Force schema (re)application for this test's DB file.
    monkeypatch.setattr(connection, "_initialized", False)
    yield db


def test_insert_and_lookup_newest_wins(sqlite_db):
    events_dao.insert_event({"timestamp": "2026-01-01T00:00:00", "source_channel_id": "-1",
                             "message_id": "5", "dest_message_id": "50"})
    events_dao.insert_event({"timestamp": "2026-01-02T00:00:00", "source_channel_id": "-1",
                             "message_id": "5", "dest_message_id": "51"})
    assert events_dao.get_destination_msg_id(-1, "5") == "51"  # newest wins
    assert events_dao.get_destination_msg_id(-1, "999") is None


def test_lookup_ignores_rows_without_destination(sqlite_db):
    events_dao.insert_event({"source_channel_id": "-1", "message_id": "8", "dest_message_id": ""})
    assert events_dao.get_destination_msg_id(-1, "8") is None


def test_type_coercion_repairs_float_bug(sqlite_db):
    # Legacy data stored translation_time as `false`; it must read back as 0.0.
    events_dao.insert_event({"source_channel_id": "-1", "message_id": "7",
                             "translation_time": False, "posting_success": True})
    m = events_dao.load_messages()[0]
    assert isinstance(m["translation_time"], float) and m["translation_time"] == 0.0
    assert m["posting_success"] is True


def test_delete_by_message_id(sqlite_db):
    events_dao.insert_event({"source_channel_id": "-1", "message_id": "7", "dest_message_id": "70"})
    assert events_dao.delete_by_message_id("7", "-1") == 1
    assert events_dao.count_events() == 0


def test_event_recorder_prefill_defaults(sqlite_db):
    r = EventRecorder()
    assert r.payload["translation_time"] == 0.0
    assert isinstance(r.payload["translation_time"], float)
    assert r.payload["posting_success"] is False


def test_event_recorder_finalize_writes_sqlite_row(sqlite_db):
    r = EventRecorder()
    r.set(source_channel_id="-1", message_id="9", dest_message_id="90", event_type="create")
    r.finalize()
    assert events_dao.get_destination_msg_id(-1, "9") == "90"


def test_migrate_imports_and_is_idempotent(sqlite_db, tmp_path, monkeypatch):
    events_json = tmp_path / "events.json"
    events_json.write_text(json.dumps({"messages": [
        {"timestamp": "2026-01-01T00:00:00", "source_channel_id": "-2",
         "message_id": "1", "dest_message_id": "10"},
        {"timestamp": "2026-01-02T00:00:00", "source_channel_id": "-2",
         "message_id": "1", "dest_message_id": "11"},
    ]}), encoding="utf-8")
    monkeypatch.setattr(migrate, "EVENTS_PATH", str(events_json))

    assert migrate.migrate() == 2
    assert migrate.migrate() == 0           # idempotent: table already populated
    assert events_dao.count_events() == 2
    assert events_dao.get_destination_msg_id(-2, "1") == "11"  # order preserved
