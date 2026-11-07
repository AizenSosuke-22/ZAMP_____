import sqlite3
from datetime import datetime, timezone

import pytest

from app import settings
from app.models import Categorization, Dossier, Invoice
from app.pipeline import categorization as cat
from app.pipeline import narrative, processing, verdict
from app.pipeline.verdict import apply_review_policies
from tests.conftest import INVOICES, MANIFEST
from tests.test_processing import canned


def dossier(text_source):
    return Dossier(case_id="CASE-000001", config_version=1, run_started=datetime.now(timezone.utc),
                   categorization=Categorization(
                       routing_bucket="C" if text_source == "ocr" else "B", text_source=text_source,
                       page_count=1, model="m", prompt_version="p", cache_hit=False, ungrounded_fields=[]))


def config(on=True):
    c = settings.load_config()
    c["review_policies"]["ocr_always_pending_review"] = on
    return c


def test_default_config_has_policy_on():
    assert settings.load_config()["review_policies"]["ocr_always_pending_review"] is True


def test_ocr_invoice_capped_at_pending_review():
    decision, reason = apply_review_policies("auto_approve", dossier("ocr"), config(on=True))
    assert decision == "approve_pending_review"
    assert "scan" in reason


def test_policy_off_lets_ocr_invoice_auto_approve():
    assert apply_review_policies("auto_approve", dossier("ocr"), config(on=False)) == ("auto_approve", None)


def test_text_layer_invoice_unaffected():
    assert apply_review_policies("auto_approve", dossier("text_layer"), config()) == ("auto_approve", None)


@pytest.mark.parametrize("decision", ["approve_pending_review", "flag", "reject", "fraud_alert"])
def test_policy_never_changes_other_decisions(decision):
    assert apply_review_policies(decision, dossier("ocr"), config()) == (decision, None)


# ------------------------------------------------------------------ V1-V6 ---
def run_fixture(client, monkeypatch, f, mutate=lambda inv: None):
    """Upload + run one fixture through the API with a canned (optionally mutated) extraction."""
    ext = canned(f)
    mutate(ext["invoice"])
    monkeypatch.setattr(cat, "call_gemini", lambda text, source: ext)
    case_id = client.post("/api/invoices/upload", files=[("files", (f, (INVOICES / f).read_bytes(),
                                                                     "application/pdf"))]).json()["results"][0]["case_id"]
    r = client.post(f"/api/cases/{case_id}/run")
    assert r.status_code == 200, r.text
    return r.json()


def test_all_fixtures_match_manifest_decision_and_label(client, monkeypatch):
    """auto_approve (#1,#2,#5,#6), approve_pending_review (#3 via OCR policy), reject (#4,#7), flag (#8,#9,#10)."""
    got = {f: run_fixture(client, monkeypatch, f) for f in MANIFEST}
    for f, r in got.items():
        exp = MANIFEST[f]["expected"]
        assert (r["decision_card"]["state"], r["decision_card"]["routing_label"]) == \
            (exp["decision"], exp["routing_label"]), f

    c3 = got["03_scanned.pdf"]["decision_card"]
    assert c3["confidence"]["band"] == "High" and "scan" in c3["policy_notes"][0]  # pending comes from the policy
    assert got["08_near_duplicate.pdf"]["decision_card"]["secondary_labels"] == ["Flag — PO issue (closed / exceeded)"]

    je10 = got["10_outside_tolerance.pdf"]["processed_invoice_record"]["computed_journal_entry"]
    assert je10["balanced"] and je10["status"].startswith("draft")
    assert {"dr_cr": "Cr", "account": "5990", "cost_center": None, "amount": 0.4,
            "account_name": "Round-off"} in je10["lines"]
    assert got["04_proforma.pdf"]["processed_invoice_record"]["computed_journal_entry"]["lines"] == []
    rec1 = got["01_happy_path.pdf"]["processed_invoice_record"]
    assert rec1["computed_journal_entry"]["status"] == "ready to post" and rec1["computed_journal_entry"]["balanced"]
    assert rec1["tax_treatment"]["itc_eligibility"] == "not evaluated — scoped out"
    assert rec1["suggested_coding"][0]["gl_account"] == "1510"


def test_bank_mismatch_is_fraud_alert(client, monkeypatch):
    r = run_fixture(client, monkeypatch, "01_happy_path.pdf", lambda i: i.update(vendor_bank_acct="50200099999999"))
    card = r["decision_card"]
    assert card["state"] == "fraud_alert" and card["routing_label"] == "🚨 Fraud alert — bank mismatch"
    assert card["failed_checks"][0]["severity"] == "critical"
    assert r["processed_invoice_record"]["computed_journal_entry"]["lines"] == []


# --- V2 bands (no fixture lands in Medium / Low: Gemini reads clean PDFs at 1.0) ---
@pytest.fixture
def ctx(client):
    return processing.load_context(settings.load_config(), "CASE-000000")


def processed(ctx, fixture, mutate=lambda inv: None, field_conf=1.0):
    inv = canned(fixture)["invoice"]
    mutate(inv)
    conf = {f: field_conf for f in ctx.config["required_fields"]}
    d = Dossier(case_id="CASE-000099", config_version=1, run_started=datetime.now(timezone.utc),
                categorization=Categorization(routing_bucket="B", text_source="text_layer", page_count=1, model="m",
                                              prompt_version="p", cache_hit=False, ungrounded_fields=[]),
                invoice_extracted=Invoice(**inv, case_id="CASE-000099", ingested_at="", source_channel="upload",
                                          file_hash="x", per_field_confidence=conf))
    return processing.run(d, ctx)


def test_medium_band_is_pending_review(ctx):
    card, _ = verdict.decide(processed(ctx, "01_happy_path.pdf", field_conf=0.8), ctx.config)
    assert (card["confidence"]["band"], card["state"], card["routing_label"]) == ("Medium", "approve_pending_review", None)


def test_low_band_flags_an_otherwise_clean_invoice(ctx):
    card, _ = verdict.decide(processed(ctx, "01_happy_path.pdf", field_conf=0.5), ctx.config)
    assert (card["state"], card["routing_label"]) == ("flag", "Flag — low extraction confidence")


def test_t3_warning_pulls_to_medium(ctx):
    d = processed(ctx, "01_happy_path.pdf", lambda i: i["line_items"][0].update(hsn_sac=None))
    assert d.warnings == ["10"]
    card, _ = verdict.decide(d, ctx.config)
    assert card["confidence"]["components"]["checks"] == 0.75 and card["state"] == "approve_pending_review"


# --- V3 narrative guardrails ---
FACTS = {"decision": "flag", "issues": [{"check": "Matches the purchase order",
                                         "what_we_found": "line 1 unit price Rs 1,028.00 is +2.8% (limit ±2%)."}],
         "notes": [], "next_action": "Ask the vendor to correct the price."}


@pytest.mark.parametrize("text,why", [
    ("This invoice needs your review. It is Rs 9,999.00 over the order. Ask the vendor to fix it.", "numbers not in FACTS"),
    ("This invoice needs your review because the GSTIN is wrong. Ask the vendor to fix it.", "jargon: GSTIN"),
    ("One. Two. Three. Four.", "4 sentences"),
])
def test_bad_narrative_falls_back_to_template(client, monkeypatch, text, why):
    monkeypatch.setattr(narrative, "call_gemini", lambda facts: text)
    out, source, rejected = narrative.write(FACTS)
    assert source == "template" and why in rejected
    assert out.startswith(narrative.HEADLINE["flag"]) and "Rs 1,028.00" in out


def test_gemini_error_falls_back_to_template(client):  # conftest stub raises
    out, source, rejected = narrative.write(FACTS)
    assert source == "template" and rejected.startswith("Gemini unavailable")


def test_good_narrative_used_and_cached(client, monkeypatch):
    calls = []
    good = ("This invoice needs your review because line 1 is priced 2.8% above the purchase order, more than the 2% "
            "we accept. Ask the vendor to correct the price.")
    monkeypatch.setattr(narrative, "call_gemini", lambda facts: calls.append(1) or good)
    assert narrative.write(FACTS) == (good, "llm", None)
    assert narrative.write(FACTS) == (good, "llm", None) and len(calls) == 1  # second from cache


# --- V5 immutability ---
def test_audit_log_is_append_only_and_chained(client, monkeypatch):
    case_id = run_fixture(client, monkeypatch, "10_outside_tolerance.pdf")["case_id"]
    client.post(f"/api/cases/{case_id}/run")  # re-run: new verdict, never a replacement
    conn = sqlite3.connect(settings.DB_PATH)
    rows = conn.execute("SELECT audit_id, prev_hash, entry_hash FROM audit_log ORDER BY audit_id").fetchall()
    assert len(rows) == 2 and rows[1][1] == rows[0][2] and rows[0][1] == "0" * 64
    for sql in ("UPDATE audit_log SET decision_state = 'auto_approve'", "DELETE FROM audit_log"):
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute(sql)


# --- V6 override ---
def test_override_logged_without_rewriting_verdict(client, monkeypatch):
    case_id = run_fixture(client, monkeypatch, "10_outside_tolerance.pdf")["case_id"]
    before = client.get(f"/api/cases/{case_id}").json()

    body = {"new_state": "auto_approve", "reason": "Price rise agreed by email on 25 Oct", "overridden_by": "ap.analyst"}
    r = client.post(f"/api/cases/{case_id}/override", json=body)
    assert r.status_code == 201
    o = r.json()
    assert (o["original_verdict"], o["new_verdict"], o["audit_id"]) == ("flag", "auto_approve", before["audit"]["audit_id"])

    after = client.get(f"/api/cases/{case_id}").json()
    assert after["override_state"] == "auto_approve" and len(after["overrides"]) == 1
    assert after["processed_invoice_record"] == before["processed_invoice_record"]  # original preserved
    assert after["audit"] == before["audit"]

    assert client.post(f"/api/cases/{case_id}/override", json={**body, "new_state": "maybe"}).status_code == 422
    assert client.post(f"/api/cases/{case_id}/override",
                       json={**body, "new_state": "reject", "reason": " "}).status_code == 422
    assert client.post(f"/api/cases/{case_id}/override", json=body).status_code == 422  # already auto_approve
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        sqlite3.connect(settings.DB_PATH).execute("DELETE FROM overrides")

    client.post(f"/api/cases/{case_id}/run")  # a new verdict clears the dashboard's override
    assert client.get(f"/api/cases/{case_id}").json()["override_state"] is None


# --- V5 exports ---
def test_exports(client, monkeypatch):
    case_id = run_fixture(client, monkeypatch, "10_outside_tolerance.pdf")["case_id"]
    j = client.get(f"/api/cases/{case_id}/export.json")
    assert j.status_code == 200 and j.json()["processed_invoice_record"]["decision_state"] == "flag"
    c = client.get(f"/api/cases/{case_id}/export.csv")
    assert c.headers["content-type"].startswith("text/csv")
    rows = c.text.strip().splitlines()
    assert len(rows) == 3 and rows[1].startswith(f"{case_id},flag,,Flag — tolerance breach")  # header + 2 lines
    p = client.get(f"/api/cases/{case_id}/export.pdf")
    assert p.headers["content-type"] == "application/pdf" and p.content.startswith(b"%PDF")
    assert client.get("/api/cases/CASE-999999/export.pdf").status_code == 404
