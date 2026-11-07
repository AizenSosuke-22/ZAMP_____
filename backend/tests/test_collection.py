import hashlib

import pymupdf

from app import settings
from tests.conftest import INVOICES


def upload(client, name, content):
    return client.post("/api/invoices/upload", files=[("files", (name, content, "application/pdf"))])


def test_upload_creates_case_and_stores_file(client):
    pdf = (INVOICES / "01_happy_path.pdf").read_bytes()
    resp = upload(client, "01.pdf", pdf)
    assert resp.status_code == 201
    r = resp.json()["results"][0]
    assert r["case_id"] == "CASE-000001"
    assert r["status"] == "ingested"
    assert r["sha256"] == hashlib.sha256(pdf).hexdigest()
    assert (settings.UPLOAD_DIR / "CASE-000001.pdf").read_bytes() == pdf

    case = client.get("/api/cases/CASE-000001").json()
    assert case["source_channel"] == "upload" and case["uploaded_by"] == "demo-analyst"
    assert case["dossier"] is None


def test_same_bytes_twice_is_dropped(client):
    pdf = (INVOICES / "01_happy_path.pdf").read_bytes()
    upload(client, "01.pdf", pdf)
    r = upload(client, "01-again.pdf", pdf).json()["results"][0]
    assert r == {"filename": "01-again.pdf", "case_id": None, "sha256": hashlib.sha256(pdf).hexdigest(),
                 "status": "duplicate_dropped", "duplicate_of": "CASE-000001"}


def test_rerendered_duplicate_gets_its_own_case(client):
    """#7 has #1's vendor + invoice no. but different bytes: it must reach Processing (Op 5)."""
    upload(client, "01.pdf", (INVOICES / "01_happy_path.pdf").read_bytes())
    r = upload(client, "07.pdf", (INVOICES / "07_hard_duplicate.pdf").read_bytes()).json()["results"][0]
    assert r["case_id"] == "CASE-000002" and r["status"] == "ingested"


def test_non_pdf_rejected(client):
    assert upload(client, "notes.txt", b"hello").status_code == 415


def test_password_protected_pdf_needs_human(client, tmp_path):
    doc = pymupdf.open(stream=(INVOICES / "01_happy_path.pdf").read_bytes(), filetype="pdf")
    locked = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="secret", owner_pw="secret")
    r = upload(client, "locked.pdf", locked).json()["results"][0]
    assert r["status"] == "needs_human" and r["status_reason"] == "password_protected"
    assert client.post(f"/api/cases/{r['case_id']}/run").status_code == 409
