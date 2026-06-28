-- SQLite schema for the event log (replaces translator/cache/events.json).
-- One row per MessageEvent (translator/models.py). All statements are idempotent.

CREATE TABLE IF NOT EXISTS events (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp           TEXT    NOT NULL DEFAULT '',
    event_type          TEXT    NOT NULL DEFAULT 'create',
    source_channel_id   TEXT    NOT NULL DEFAULT '',  -- TEXT: existing data + lookups compare as str
    dest_channel_id     TEXT    NOT NULL DEFAULT '',
    source_channel_name TEXT    NOT NULL DEFAULT '',
    dest_channel_name   TEXT    NOT NULL DEFAULT '',
    message_id          TEXT    NOT NULL DEFAULT '',
    media_type          TEXT    NOT NULL DEFAULT '',
    file_size_bytes     INTEGER NOT NULL DEFAULT 0,
    original_size       INTEGER NOT NULL DEFAULT 0,
    translated_size     INTEGER NOT NULL DEFAULT 0,
    translation_time    REAL    NOT NULL DEFAULT 0.0,  -- REAL fixes the float->False prefill bug at rest
    retry_count         INTEGER NOT NULL DEFAULT 0,
    posting_success     INTEGER NOT NULL DEFAULT 0,    -- 0/1 (SQLite has no bool)
    api_error_code      INTEGER NOT NULL DEFAULT 0,
    exception_message   TEXT    NOT NULL DEFAULT '',
    edit_timestamp      TEXT    NOT NULL DEFAULT '',
    previous_size       INTEGER NOT NULL DEFAULT 0,
    new_size            INTEGER NOT NULL DEFAULT 0,
    source_message      TEXT    NOT NULL DEFAULT '',
    translated_message  TEXT    NOT NULL DEFAULT '',
    dest_message_id     TEXT    NOT NULL DEFAULT '',
    file_path           TEXT    NOT NULL DEFAULT '',
    -- Anthropic token usage + model, for cost reporting (added in schema v2).
    -- Existing DBs gain these via connection._ensure_columns (idempotent ALTER).
    input_tokens          INTEGER NOT NULL DEFAULT 0,
    output_tokens         INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens     INTEGER NOT NULL DEFAULT 0,
    cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
    model_used            TEXT    NOT NULL DEFAULT ''
);

-- Core edit lookup: (source_channel_id, message_id) newest-first, only rows that
-- actually have a destination. Turns the old full-file reverse scan into one seek.
CREATE INDEX IF NOT EXISTS idx_events_src_msg
    ON events (source_channel_id, message_id, id DESC)
    WHERE dest_message_id <> '';

-- Dashboard time-range + per-channel grouping.
CREATE INDEX IF NOT EXISTS idx_events_ts       ON events (timestamp);
CREATE INDEX IF NOT EXISTS idx_events_type_ts  ON events (event_type, timestamp);
CREATE INDEX IF NOT EXISTS idx_events_chan_ts  ON events (source_channel_name, timestamp);

CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT);
INSERT OR IGNORE INTO schema_meta (key, value) VALUES ('version', '1');
-- v2 added the token/cost columns above; bump the recorded version (no-op on
-- fresh DBs where it was just inserted as '1', so force it forward).
UPDATE schema_meta SET value = '2' WHERE key = 'version' AND value = '1';
