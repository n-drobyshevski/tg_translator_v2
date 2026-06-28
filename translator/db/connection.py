"""SQLite connection handling for the event store.

Design notes (see plan): two separate OS processes use this DB — the async relay
bot (always-on task) and the synchronous Flask admin app (WSGI). Safety comes
from short, connection-per-operation access under WAL with a busy_timeout, never
a long-lived cached connection.
"""

from __future__ import annotations

import contextlib
import os
import sqlite3

from translator import config as _config

_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")

# Per-process guard: the persistent pragmas (journal_mode) and schema only need
# to be applied once per process, not on every connection.
_initialized = False


def _apply_schema(conn: sqlite3.Connection) -> None:
    with open(_SCHEMA_PATH, "r", encoding="utf-8") as f:
        conn.executescript(f.read())


# Columns added after the initial schema. `schema.sql` uses CREATE TABLE IF NOT
# EXISTS, which never alters an existing table, so columns added in later schema
# versions must be back-filled here for DBs created before they existed. Each
# entry is (column, "TYPE NOT NULL DEFAULT <x>"); applied idempotently.
_ADDED_COLUMNS = [
    ("input_tokens", "INTEGER NOT NULL DEFAULT 0"),
    ("output_tokens", "INTEGER NOT NULL DEFAULT 0"),
    ("cache_read_tokens", "INTEGER NOT NULL DEFAULT 0"),
    ("cache_creation_tokens", "INTEGER NOT NULL DEFAULT 0"),
    ("model_used", "TEXT NOT NULL DEFAULT ''"),
]


def _ensure_columns(conn: sqlite3.Connection) -> None:
    """Add any missing later-version columns to the events table (idempotent)."""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(events)")}
    for name, decl in _ADDED_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE events ADD COLUMN {name} {decl}")


def _ensure_initialized(conn: sqlite3.Connection) -> None:
    global _initialized
    if _initialized:
        return
    # journal_mode is persisted in the DB header; setting it once per process is enough.
    conn.execute(f"PRAGMA journal_mode={_config.SQLITE_JOURNAL_MODE}")
    conn.execute("PRAGMA synchronous=NORMAL")
    _apply_schema(conn)
    _ensure_columns(conn)
    _initialized = True


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(_config.DB_PATH), exist_ok=True)
    conn = sqlite3.connect(
        _config.DB_PATH,
        timeout=5.0,            # Python-side busy wait, mirrors busy_timeout
        isolation_level=None,   # autocommit; we manage write txns explicitly
        check_same_thread=False,  # safe: connection is created+closed within one get_conn()
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextlib.contextmanager
def get_conn():
    """Yield a short-lived connection; schema/pragmas are ensured on first use."""
    conn = _connect()
    try:
        _ensure_initialized(conn)
        yield conn
    finally:
        conn.close()
