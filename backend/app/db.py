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
    status         TEXT NOT NULL,   -- ingested | needs_human | decided | failed
    status_reason  TEXT,
    retry_count    INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS dossiers (
    case_id        TEXT PRIMARY KEY REFERENCES cases(case_id),
    config_version INTEGER NOT NULL,
    dossier_json   TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
-- One entry per verdict (PRD §8 V5). Append-only: triggers below, and each entry_hash chains
-- sha256(prev_hash + card_json + record_json) so tampering with a stored row is detectable.
CREATE TABLE IF NOT EXISTS audit_log (
    audit_id       INTEGER PRIMARY KEY,
    case_id        TEXT NOT NULL REFERENCES cases(case_id),
    decision_state TEXT NOT NULL,
    confidence     REAL NOT NULL,
    band           TEXT NOT NULL,
    routing_label  TEXT,
    config_version INTEGER NOT NULL,
    card_json      TEXT NOT NULL,
    record_json    TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    prev_hash      TEXT NOT NULL,
    entry_hash     TEXT NOT NULL
);
-- Human overrides (V6). Append-only; never touches audit_log.
CREATE TABLE IF NOT EXISTS overrides (
    override_id    INTEGER PRIMARY KEY,
    case_id        TEXT NOT NULL REFERENCES cases(case_id),
    audit_id       INTEGER NOT NULL REFERENCES audit_log(audit_id),
    original_state TEXT NOT NULL,
    new_state      TEXT NOT NULL,
    reason         TEXT NOT NULL,
    overridden_by  TEXT NOT NULL,
    created_at     TEXT NOT NULL
);
-- Dashboard projection: one row per case, points at the latest verdict. Mutable by design.
CREATE TABLE IF NOT EXISTS dashboard (
    case_id         TEXT PRIMARY KEY REFERENCES cases(case_id),
    decided_at      TEXT NOT NULL,
    vendor_id       TEXT,
    vendor_name     TEXT,
    invoice_number  TEXT,
    grand_total     REAL,
    decision_state  TEXT NOT NULL,
    routing_label   TEXT,
    confidence      REAL NOT NULL,
    band            TEXT NOT NULL,
    latest_audit_id INTEGER NOT NULL REFERENCES audit_log(audit_id),
    override_state  TEXT
);
CREATE TRIGGER IF NOT EXISTS audit_log_no_update BEFORE UPDATE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_log_no_delete BEFORE DELETE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS overrides_no_update BEFORE UPDATE ON overrides
BEGIN SELECT RAISE(ABORT, 'overrides is append-only'); END;
CREATE TRIGGER IF NOT EXISTS overrides_no_delete BEFORE DELETE ON overrides
BEGIN SELECT RAISE(ABORT, 'overrides is append-only'); END;
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
