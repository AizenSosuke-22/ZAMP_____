"""Offline: Gemini is replaced with canned responses built from the manifest answer key."""
import pytest

from app.pipeline import categorization as cat
from tests.conftest import INVOICES, canned_extraction


def pdf(name):
    return (INVOICES / name).read_bytes()


def test_text_pdf_routes_to_bucket_b():
    bucket, source, pages, text = cat.classify(pdf("01_happy_path.pdf"))
    assert (bucket, source, pages) == ("B", "text_layer", 1)
    assert "SOS/26-27/0187" in text


def test_scanned_pdf_routes_to_bucket_c():
    bucket, source, _, text = cat.classify(pdf("03_scanned.pdf"))
    assert (bucket, source, text) == ("C", "ocr", "")


def test_ocr_reads_scanned_invoice():
    text, boxes = cat.ocr_pdf(pdf("03_scanned.pdf"))
    assert "SFM/1026/0342" in text and "27AAGCS2287M1ZS" in text and "89,090.00" in text
    assert all(0 <= s <= 1 for _, s in boxes)


def test_grounding_keeps_correct_values():
    _, _, _, text = cat.classify(pdf("01_happy_path.pdf"))
    conf, ungrounded = cat.ground(canned_extraction("01_happy_path.pdf"), text)
    assert ungrounded == []
    assert conf["invoice_number"] == 1.0 and conf["line_items[1].unit_price"] == 1.0
    assert conf["due_date"] == 1.0  # "19-Nov-2026" on the page grounds ISO "2026-11-19"


def test_grounding_caps_values_not_on_the_page():
    _, _, _, text = cat.classify(pdf("01_happy_path.pdf"))
    result = canned_extraction("01_happy_path.pdf")
    result["invoice"]["grand_total"] = 183163.0          # transposed digits
    result["invoice"]["vendor_gstin"] = "27AAFCS7342L1ZY"  # wrong check digit
    result["invoice"]["invoice_number"] = None             # absent -> 0
    conf, ungrounded = cat.ground(result, text)
    assert set(ungrounded) == {"grand_total", "vendor_gstin"}
    assert conf["grand_total"] == cat.UNGROUNDED_CAP and conf["vendor_gstin"] == cat.UNGROUNDED_CAP
    assert conf["invoice_number"] == 0.0


def test_ocr_confidence_capped_by_box_score():
    boxes = [("Invoice No.: SFM/1026/0342", 0.81), ("68,000.00", 0.99)]
    result = canned_extraction("03_scanned.pdf")
    conf, _ = cat.ground(result, "\n".join(t for t, _ in boxes), boxes)
    assert conf["invoice_number"] == 0.81
    assert conf["line_items[0].unit_price"] == 0.99


@pytest.mark.parametrize("fixture,bucket", [("01_happy_path.pdf", "B"), ("03_scanned.pdf", "C")])
def test_run_endpoint_builds_dossier(client, monkeypatch, fixture, bucket):
    monkeypatch.setattr(cat, "call_gemini", lambda text, source: canned_extraction(fixture))
    case_id = client.post("/api/invoices/upload", files=[("files", (fixture, pdf(fixture), "application/pdf"))]
                          ).json()["results"][0]["case_id"]
    d = client.post(f"/api/cases/{case_id}/run").json()
    assert d["config_version"] == 1
    assert d["categorization"]["routing_bucket"] == bucket
    assert d["categorization"]["cache_hit"] is False
    inv = d["invoice_extracted"]
    assert inv["case_id"] == case_id and inv["source_channel"] == "upload"
    assert inv["per_field_confidence"]["grand_total"] > 0.9
    assert d["stages"] == {} and d["blocker_hit"] is False

    # second run comes from cache, and the dossier is retrievable
    assert client.post(f"/api/cases/{case_id}/run").json()["categorization"]["cache_hit"] is True
    assert client.get(f"/api/cases/{case_id}").json()["status"] == "extracted"
