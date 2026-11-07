"""SQLite (stdlib). Schema is created on first connect."""
import sqlite3
from contextlib import contextmanager

from app import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    id             INTEGER PRIMARY KEY,
    case_id        TEXT UNIQUE,
    filename       TEXT NOT NULL,
    sha256         TEXT NOT NULL UNIQUE,
    source_channel TEXT NOT NULL,
    uploaded_by    TEXT,
    ingested_at    TEXT NOT NULL,
    file_path      TEXT NOT NULL,   -- relative to data/
    size_bytes     INTEGER NOT NULL,
    status         TEXT NOT NULL,   -- ingested | needs_human | processed | failed
    status_reason  TEXT,
    retry_count    INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS dossiers (
    case_id        TEXT PRIMARY KEY REFERENCES cases(case_id),
    config_version INTEGER NOT NULL,
    dossier_json   TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
"""


@contextmanager
def connect():
    """`with connect() as conn:` — commits on success, rolls back on error, always closes."""
    settings.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        with conn:
            yield conn
    finally:
        conn.close()
