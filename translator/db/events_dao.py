"""Data-access layer for the SQLite event store.

These functions are the SQLite implementations behind the three legacy access
points (``EventRecorder.finalize`` append, ``Config.get_destination_msg_id``
lookup, ``aggregator.load_messages`` range read). Call sites select between this
and the legacy JSON path via ``CONFIG.STORAGE_BACKEND``; this module is always
SQLite-only so the migrator can use it directly regardless of that flag.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from translator.db.connection import get_conn
from translator.models import MessageEvent

# Column order = MessageEvent field order (the dataclass is the source of truth).
_FIELDS: List[str] = list(MessageEvent.__annotations__.keys())
_INT_FIELDS = {f for f, t in MessageEvent.__annotations__.items() if t is int}
_FLOAT_FIELDS = {f for f, t in MessageEvent.__annotations__.items() if t is float}
_BOOL_FIELDS = {f for f, t in MessageEvent.__annotations__.items() if t is bool}


def _coerce_to_db(field: str, value: Any) -> Any:
    """Coerce a Python payload value to its stored SQLite representation."""
    if field in _BOOL_FIELDS:
        return 1 if value else 0
    if field in _INT_FIELDS:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
    if field in _FLOAT_FIELDS:
        # Repairs the legacy float->False bug: float(False) == 0.0.
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
    return "" if value is None else str(value)


def _payload_to_row(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Build a full column dict from a (possibly partial/legacy) payload dict."""
    return {f: _coerce_to_db(f, payload.get(f)) for f in _FIELDS}


def _row_to_dict(row) -> Dict[str, Any]:
    """Convert a DB row back to the dict shape the old JSON path produced."""
    out: Dict[str, Any] = {}
    for f in _FIELDS:
        v = row[f]
        if f in _BOOL_FIELDS:
            out[f] = bool(v)
        elif f in _FLOAT_FIELDS:
            out[f] = float(v) if v is not None else 0.0
        elif f in _INT_FIELDS:
            out[f] = int(v) if v is not None else 0
        else:
            out[f] = v if v is not None else ""
    return out


def insert_event(payload: Dict[str, Any]) -> int:
    """Append one event. Replaces EventRecorder.finalize's append+rewrite."""
    row = _payload_to_row(payload)
    cols = ", ".join(_FIELDS)
    placeholders = ", ".join("?" for _ in _FIELDS)
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            cur = conn.execute(
                f"INSERT INTO events ({cols}) VALUES ({placeholders})",
                [row[f] for f in _FIELDS],
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        return int(cur.lastrowid)


def get_destination_msg_id(source_channel_id, message_id) -> Optional[str]:
    """Newest destination message id for a source message, or None.

    Drop-in for Config.get_destination_msg_id; uses idx_events_src_msg.
    """
    if not message_id:
        raise ValueError("message_id cannot be empty")
    with get_conn() as conn:
        r = conn.execute(
            """SELECT dest_message_id FROM events
               WHERE source_channel_id = ? AND message_id = ? AND dest_message_id <> ''
               ORDER BY id DESC LIMIT 1""",
            (str(source_channel_id), str(message_id)),
        ).fetchone()
    return r["dest_message_id"] if r else None


def load_messages(
    since_iso: Optional[str] = None, event_type: Optional[str] = None
) -> List[Dict[str, Any]]:
    """All events as list-of-dicts (oldest first), with optional filters.

    Drop-in for aggregator.load_messages; the build_* consumers see the same shape.
    """
    sql = "SELECT * FROM events"
    where: List[str] = []
    args: List[Any] = []
    if since_iso:
        where.append("timestamp >= ?")
        args.append(since_iso)
    if event_type:
        where.append("event_type = ?")
        args.append(event_type)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id ASC"
    with get_conn() as conn:
        rows = conn.execute(sql, args).fetchall()
    return [_row_to_dict(r) for r in rows]


def delete_by_message_id(message_id, source_channel_id=None) -> int:
    """Delete events for a source message id (optionally scoped to a channel).

    Returns the number of rows removed. Used by the admin manager's manual
    "delete message" action.
    """
    sql = "DELETE FROM events WHERE message_id = ?"
    args: List[Any] = [str(message_id)]
    if source_channel_id is not None:
        sql += " AND source_channel_id = ?"
        args.append(str(source_channel_id))
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            cur = conn.execute(sql, args)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        return cur.rowcount


def count_events() -> int:
    with get_conn() as conn:
        return int(conn.execute("SELECT COUNT(*) AS c FROM events").fetchone()["c"])
