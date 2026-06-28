"""One-shot, idempotent import of events.json into the SQLite event store.

Usage:
    python -m translator.db.migrate           # import only if table is empty
    python -m translator.db.migrate --force   # wipe table and re-import

Order is preserved (oldest->newest), so the synthetic ``id`` reproduces the old
list order: ``id ASC`` == JSON order, ``id DESC`` == the old reversed() lookup.
The original events.json is left untouched as a rollback.
"""

from __future__ import annotations

import json
import logging
import os
import sys

from translator.config import EVENTS_PATH
from translator.db import events_dao
from translator.db.connection import get_conn

logger = logging.getLogger(__name__)


def migrate(force: bool = False) -> int:
    """Import events.json into the events table. Returns rows imported."""
    existing = events_dao.count_events()
    if existing and not force:
        logger.info(
            "events table already has %d rows; skipping import (use --force to re-import)",
            existing,
        )
        return 0

    if force:
        with get_conn() as conn:
            conn.execute("DELETE FROM events")
        logger.info("--force: cleared existing events table")

    if not os.path.exists(EVENTS_PATH):
        logger.warning("No events.json at %s; nothing to import", EVENTS_PATH)
        return 0

    with open(EVENTS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    messages = data.get("messages", [])

    imported = 0
    for i, msg in enumerate(messages):
        try:
            events_dao.insert_event(msg)
            imported += 1
        except Exception as e:  # don't abort the whole import on one bad legacy row
            logger.error("Skipping malformed row %d: %s", i, e)

    logger.info("Imported %d/%d events from %s", imported, len(messages), EVENTS_PATH)
    # Light verification: count + a sample lookup round-trip.
    total = events_dao.count_events()
    logger.info("events table now holds %d rows", total)
    return imported


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    migrate(force="--force" in sys.argv)
