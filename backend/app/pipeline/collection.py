"""Bucket 1 (PRD §5): file + channel -> raw file + ingest metadata (SHA-256, case ID).

Manual upload only. Email watcher is out of scope for this build.
"""
import hashlib
import logging
from datetime import datetime, timezone

import pymupdf

from app import db, settings

log = logging.getLogger(__name__)


def ingest(filename: str, content: bytes, uploaded_by: str, channel: str = "upload") -> dict:
    """Create a case for one PDF. Caller has already checked it is a PDF.

    Hard duplicate (same bytes as an earlier upload) -> no new case (PRD §5: log, don't create).
    Password-protected PDF -> case created with status needs_human (PRD §5: don't try to crack).
    """
    sha = hashlib.sha256(content).hexdigest()
    with db.connect() as conn:
        dup = conn.execute("SELECT case_id FROM cases WHERE sha256 = ?", (sha,)).fetchone()
        if dup:
            log.info("hard duplicate at ingest: %s matches %s (sha256 %s) - dropped", filename, dup["case_id"], sha)
            return {"filename": filename, "case_id": None, "sha256": sha,
                    "status": "duplicate_dropped", "duplicate_of": dup["case_id"]}

        status, reason = "ingested", None
        if pymupdf.open(stream=content, filetype="pdf").needs_pass:
            status, reason = "needs_human", "password_protected"

        cur = conn.execute(
            "INSERT INTO cases (filename, sha256, source_channel, uploaded_by, ingested_at,"
            " file_path, size_bytes, status, status_reason) VALUES (?, ?, ?, ?, ?, '', ?, ?, ?)",
            (filename, sha, channel, uploaded_by, datetime.now(timezone.utc).isoformat(timespec="seconds"),
             len(content), status, reason))
        case_id = f"CASE-{cur.lastrowid:06d}"
        rel_path = f"uploads/{case_id}.pdf"
        settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        (settings.UPLOAD_DIR / f"{case_id}.pdf").write_bytes(content)
        conn.execute("UPDATE cases SET case_id = ?, file_path = ? WHERE id = ?", (case_id, rel_path, cur.lastrowid))

    return {"filename": filename, "case_id": case_id, "sha256": sha, "status": status,
            **({"status_reason": reason} if reason else {})}
