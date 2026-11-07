"""Runs one case through the buckets and stores its Dossier. Processing + Verdict plug in here next."""
import json
from datetime import datetime, timezone

from app import db, settings
from app.models import Dossier, Invoice
from app.pipeline import categorization


def _now():
    return datetime.now(timezone.utc)


def run_case(case: dict, use_cache: bool = True) -> Dossier:
    config = settings.load_config()
    dossier = Dossier(case_id=case["case_id"], config_version=config["config_version"], run_started=_now())

    pdf = (settings.UPLOAD_DIR / f"{case['case_id']}.pdf").read_bytes()
    cat, fields, confidence = categorization.categorize(pdf, case["sha256"], use_cache)
    dossier.categorization = cat
    dossier.invoice_extracted = Invoice(
        **fields, case_id=case["case_id"], ingested_at=case["ingested_at"],
        source_channel=case["source_channel"], file_hash=case["sha256"],
        buyer_entity_id=None,  # resolved against entity.json by Op 2 (next task)
        per_field_confidence=confidence)
    dossier.run_ended = _now()

    with db.connect() as conn:
        conn.execute(
            "INSERT INTO dossiers (case_id, config_version, dossier_json, updated_at) VALUES (?, ?, ?, ?)"
            " ON CONFLICT(case_id) DO UPDATE SET config_version = excluded.config_version,"
            " dossier_json = excluded.dossier_json, updated_at = excluded.updated_at",
            (case["case_id"], dossier.config_version, dossier.model_dump_json(), _now().isoformat()))
        conn.execute("UPDATE cases SET status = 'extracted', status_reason = NULL WHERE case_id = ?",
                     (case["case_id"],))
    return dossier


def get_case(case_id: str) -> dict | None:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM cases WHERE case_id = ?", (case_id,)).fetchone()
        if not row:
            return None
        d = conn.execute("SELECT dossier_json FROM dossiers WHERE case_id = ?", (case_id,)).fetchone()
    return {**dict(row), "dossier": json.loads(d["dossier_json"]) if d else None}
