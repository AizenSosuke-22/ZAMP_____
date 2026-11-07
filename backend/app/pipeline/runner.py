"""Runs one case through the buckets; persists Dossier + verdict (V5) and records overrides (V6)."""
import hashlib
import json
from datetime import datetime, timezone

from app import db, settings
from app.models import Dossier, Invoice
from app.pipeline import categorization, processing, verdict

GENESIS_HASH = "0" * 64


def _now():
    return datetime.now(timezone.utc)


def run_case(case: dict, use_cache: bool = True) -> dict:
    config = settings.load_config()
    dossier = Dossier(case_id=case["case_id"], config_version=config["config_version"], run_started=_now())

    pdf = (settings.UPLOAD_DIR / f"{case['case_id']}.pdf").read_bytes()
    cat, fields, confidence = categorization.categorize(pdf, case["sha256"], use_cache)
    dossier.categorization = cat
    dossier.invoice_extracted = Invoice(
        **fields, case_id=case["case_id"], ingested_at=case["ingested_at"],
        source_channel=case["source_channel"], file_hash=case["sha256"],
        buyer_entity_id=None,  # filled by Op 2
        per_field_confidence=confidence)
    processing.run(dossier, processing.load_context(config, case["case_id"]))
    dossier.run_ended = _now()
    card, record = verdict.decide(dossier, config)

    inv = dossier.invoice_extracted
    card_json, record_json = json.dumps(card, ensure_ascii=False), json.dumps(record, ensure_ascii=False)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO dossiers (case_id, config_version, dossier_json, updated_at) VALUES (?, ?, ?, ?)"
            " ON CONFLICT(case_id) DO UPDATE SET config_version = excluded.config_version,"
            " dossier_json = excluded.dossier_json, updated_at = excluded.updated_at",
            (case["case_id"], dossier.config_version, dossier.model_dump_json(), _now().isoformat()))
        # Append-only audit entry, hash-chained to the previous one (a re-run adds, never replaces).
        prev = conn.execute("SELECT entry_hash FROM audit_log ORDER BY audit_id DESC LIMIT 1").fetchone()
        prev_hash = prev["entry_hash"] if prev else GENESIS_HASH
        entry_hash = hashlib.sha256((prev_hash + card_json + record_json).encode()).hexdigest()
        audit_id = conn.execute(
            "INSERT INTO audit_log (case_id, decision_state, confidence, band, routing_label, config_version,"
            " card_json, record_json, created_at, prev_hash, entry_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (case["case_id"], card["state"], card["confidence"]["score"], card["confidence"]["band"],
             card["routing_label"], dossier.config_version, card_json, record_json,
             record["audit"]["decided_at"], prev_hash, entry_hash)).lastrowid
        # Dashboard row points at the latest verdict; an override belonged to the old one, so it's cleared.
        conn.execute(
            "INSERT INTO dashboard (case_id, decided_at, vendor_id, vendor_name, invoice_number, grand_total,"
            " decision_state, routing_label, confidence, band, latest_audit_id, override_state)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL) ON CONFLICT(case_id) DO UPDATE SET"
            " decided_at = excluded.decided_at, vendor_id = excluded.vendor_id, vendor_name = excluded.vendor_name,"
            " invoice_number = excluded.invoice_number, grand_total = excluded.grand_total,"
            " decision_state = excluded.decision_state, routing_label = excluded.routing_label,"
            " confidence = excluded.confidence, band = excluded.band, latest_audit_id = excluded.latest_audit_id,"
            " override_state = NULL",
            (case["case_id"], record["audit"]["decided_at"], dossier.resolved.get("vendor_id"), inv.vendor_name,
             inv.invoice_number, inv.grand_total, card["state"], card["routing_label"],
             card["confidence"]["score"], card["confidence"]["band"], audit_id))
        conn.execute("UPDATE cases SET status = 'decided', status_reason = NULL WHERE case_id = ?",
                     (case["case_id"],))
    return {"case_id": case["case_id"], "dossier": dossier.model_dump(mode="json"),
            "decision_card": card, "processed_invoice_record": record}


def latest_verdict(conn, case_id: str):
    return conn.execute("SELECT * FROM audit_log WHERE case_id = ? ORDER BY audit_id DESC LIMIT 1",
                        (case_id,)).fetchone()


def get_case(case_id: str) -> dict | None:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM cases WHERE case_id = ?", (case_id,)).fetchone()
        if not row:
            return None
        d = conn.execute("SELECT dossier_json FROM dossiers WHERE case_id = ?", (case_id,)).fetchone()
        v = latest_verdict(conn, case_id)
        dash = conn.execute("SELECT override_state FROM dashboard WHERE case_id = ?", (case_id,)).fetchone()
        overrides = [dict(o) for o in conn.execute(
            "SELECT * FROM overrides WHERE case_id = ? ORDER BY override_id", (case_id,))]
    return {**dict(row), "dossier": json.loads(d["dossier_json"]) if d else None,
            "decision_card": json.loads(v["card_json"]) if v else None,
            "processed_invoice_record": json.loads(v["record_json"]) if v else None,
            "audit": {k: v[k] for k in ("audit_id", "created_at", "prev_hash", "entry_hash")} if v else None,
            "override_state": dash["override_state"] if dash else None,
            "overrides": overrides}


def override(case_id: str, new_state: str, reason: str, overridden_by: str) -> dict:
    """V6: record a human override. Never touches audit_log or the record (append-only overrides row)."""
    if new_state not in verdict.STATES:
        raise ValueError(f"new_state must be one of {', '.join(verdict.STATES)}")
    if not reason.strip() or not overridden_by.strip():
        raise ValueError("reason and overridden_by are required")
    with db.connect() as conn:
        v = latest_verdict(conn, case_id)
        if not v:
            raise LookupError(f"{case_id} has no verdict to override")
        dash = conn.execute("SELECT override_state FROM dashboard WHERE case_id = ?", (case_id,)).fetchone()
        current = dash["override_state"] or v["decision_state"]
        if new_state == current:
            raise ValueError(f"{case_id} is already {new_state}")
        created = _now().isoformat(timespec="seconds")
        override_id = conn.execute(
            "INSERT INTO overrides (case_id, audit_id, original_state, new_state, reason, overridden_by, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (case_id, v["audit_id"], v["decision_state"], new_state, reason.strip(), overridden_by.strip(),
             created)).lastrowid
        conn.execute("UPDATE dashboard SET override_state = ? WHERE case_id = ?", (new_state, case_id))
    return {"override_id": override_id, "case_id": case_id, "audit_id": v["audit_id"],
            "original_verdict": v["decision_state"], "new_verdict": new_state, "reason": reason.strip(),
            "overridden_by": overridden_by.strip(), "created_at": created}
