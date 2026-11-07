"""Processing (PRD §7) offline: Gemini replaced by canned responses from the manifest answer key."""
from datetime import datetime, timezone

import pytest

from app import settings
from app.models import Dossier, Invoice
from app.pipeline import categorization as cat
from app.pipeline import processing
from tests.conftest import INVOICES, canned_extraction

# fixture -> (decision hint, failed ops), processed in file order (docs/plan-processing.md §6)
EXPECTED = {
    "01_happy_path.pdf": ("approve", []),
    "02_within_tolerance.pdf": ("approve", []),
    "03_scanned.pdf": ("approve", []),
    "04_proforma.pdf": ("reject", ["1"]),
    "05_split_po_1of3.pdf": ("approve", []),
    "06_split_po_2of3.pdf": ("approve", []),
    "07_hard_duplicate.pdf": ("reject", ["5"]),
    "08_near_duplicate.pdf": ("flag", ["6", "7"]),
    "09_missing_invoice_no.pdf": ("flag", []),
    "10_outside_tolerance.pdf": ("flag", ["8"]),
}


def canned(fixture):
    ext = canned_extraction(fixture)
    if fixture == "04_proforma.pdf":
        ext["invoice"]["document_type"] = "proforma_invoice"
    return ext


def op(d, op_id):
    return processing._op(d, op_id)


def test_all_fixtures_in_order(client, monkeypatch):
    got = {}
    for f in EXPECTED:
        monkeypatch.setattr(cat, "call_gemini", lambda text, source, ext=canned(f): ext)
        case_id = client.post("/api/invoices/upload", files=[("files", (f, (INVOICES / f).read_bytes(),
                                                                         "application/pdf"))]).json()["results"][0]["case_id"]
        got[f] = Dossier.model_validate(client.post(f"/api/cases/{case_id}/run").json())

    assert {f: (processing.decision_hint(d), d.failures) for f, d in got.items()} == EXPECTED

    # #2: within tolerance, variance visible in evidence
    m2 = op(got["02_within_tolerance.pdf"], "8")
    assert m2.evidence["total_variance"] == 1260 and m2.evidence["match_type"].startswith("2-way")
    # #4: everything after Op 1 skipped
    assert got["04_proforma.pdf"].skipped == ["2", "3", "4", "5", "6", "7", "8", "9", "10", "F1"]
    # #5 / #6: split PO balance carried across invoices
    assert op(got["05_split_po_1of3.pdf"], "7").evidence["remaining_after_this_invoice"] == 1300000
    assert op(got["06_split_po_2of3.pdf"], "7").evidence["remaining_after_this_invoice"] == 650000
    # #7: duplicate of #1's case
    assert op(got["07_hard_duplicate.pdf"], "5").evidence["duplicate_of"] == "CASE-000001"
    # #8: PO used up by #1 -> Op 8 not evaluated
    assert op(got["08_near_duplicate.pdf"], "8").result == "not_evaluated"
    # #9: missing invoice number drives the flag; Op 5 could only check the file hash
    d9 = got["09_missing_invoice_no.pdf"]
    assert d9.missing_required_fields == ["invoice_number"] and "5" in d9.warnings
    # #10: price breach named in plain English
    assert "+2.8%" in op(got["10_outside_tolerance.pdf"], "8").reason
    # coding advisory + entity resolved on the happy path
    d1 = got["01_happy_path.pdf"]
    assert d1.advisories == ["F1"] and d1.invoice_extracted.buyer_entity_id == "ENT-01"


# ------------------------------------------------- targeted (no fixture) ---
@pytest.fixture
def ctx(client):  # client -> isolated DB
    return processing.load_context(settings.load_config(), "CASE-000000")


def process(ctx, fixture, mutate=lambda inv: None, case_id="CASE-000099"):
    inv = canned(fixture)["invoice"]
    mutate(inv)
    d = Dossier(case_id=case_id, config_version=1, run_started=datetime.now(timezone.utc),
                invoice_extracted=Invoice(**inv, case_id=case_id, ingested_at="", source_channel="upload",
                                          file_hash=case_id, per_field_confidence={}))
    return processing.run(d, ctx)


def test_bank_mismatch_is_fraud_alert(ctx):
    d = process(ctx, "01_happy_path.pdf", lambda i: i.update(vendor_bank_acct="50200099999999"))
    assert d.failures == ["4"] and processing.decision_hint(d) == "fraud_alert"
    assert op(d, "4").severity == "critical" and op(d, "5").result == "skipped"


def test_vendor_not_in_master(ctx):
    d = process(ctx, "01_happy_path.pdf", lambda i: i.update(vendor_gstin="27AAAAA0000A1Z5",
                                                            vendor_name="Unknown Traders Pvt Ltd"))
    assert d.failures == ["3"] and processing.decision_hint(d) == "reject"


def test_wrong_bill_to_entity(ctx):
    d = process(ctx, "01_happy_path.pdf", lambda i: i.update(buyer_gstin="29AADCK5519H1ZD"))
    assert d.failures == ["2"] and processing.decision_hint(d) == "reject"


def test_closed_po_flags_and_skips_match(ctx):
    d = process(ctx, "01_happy_path.pdf", lambda i: i.update(po_reference="PO-2026-0301"))
    assert d.failures == ["7"] and op(d, "8").result == "not_evaluated"
    assert "closed" in op(d, "7").reason and processing.decision_hint(d) == "flag"


def test_near_dup_toggle_off_skips_op_6(ctx):
    ctx.prior = [process(ctx, "01_happy_path.pdf", case_id="CASE-000001")]
    ctx.config["op_toggles"]["near_dup_check"] = False
    d = process(ctx, "08_near_duplicate.pdf")
    assert op(d, "6").result == "skipped" and op(d, "6").reason == "Turned off in Settings."
    assert d.failures == ["7"]  # PO still used up by #1


def test_gstin_bad_check_digit(ctx):
    d = process(ctx, "01_happy_path.pdf", lambda i: i.update(vendor_gstin="27AAFCS7342L1ZY"))
    assert op(d, "3").result == "warn"  # matched by name instead
    assert d.failures == ["10"] and "check-digit" in op(d, "10").reason


def test_ocr_rate_misread_caught_by_arithmetic(ctx):
    """The '9 read as 6' OCR case: if the misread survives extraction, Op 9 catches it."""
    d = process(ctx, "03_scanned.pdf", lambda i: i["line_items"][1].update(cgst_rate=6.0))
    assert "9" in d.failures and processing.decision_hint(d) == "flag"
