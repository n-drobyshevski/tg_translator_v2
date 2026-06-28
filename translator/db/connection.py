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


def _ensure_initialized(conn: sqlite3.Connection) -> None:
    global _initialized
    if _initialized:
        return
    # journal_mode is persisted in the DB header; setting it once per process is enough.
    conn.execute(f"PRAGMA journal_mode={_config.SQLITE_JOURNAL_MODE}")
    conn.execute("PRAGMA synchronous=NORMAL")
    _apply_schema(conn)
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
