import json

import pytest
from fastapi.testclient import TestClient

from app import settings
from app.main import app
from app.models import InvoiceFields, LineItem
from app.pipeline import narrative

INVOICES = settings.DATA_DIR / "invoices"
MANIFEST = {e["file"]: e for e in json.loads((INVOICES / "manifest.json").read_text(encoding="utf-8"))["invoices"]}


@pytest.fixture
def client(tmp_path, monkeypatch):
    """App with an isolated DB / uploads / cache - never touches backend/data runtime state."""
    monkeypatch.setattr(settings, "DB_PATH", tmp_path / "ap.db")
    monkeypatch.setattr(settings, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(settings, "CACHE_DIR", tmp_path / "cache")
    return TestClient(app)


@pytest.fixture(autouse=True)
def offline_narrative(monkeypatch):
    """No test reaches Gemini for narratives: the template fallback is used unless a test stubs call_gemini."""
    def offline(facts):
        raise RuntimeError("offline in tests")
    monkeypatch.setattr(narrative, "call_gemini", offline)


def canned_extraction(file: str, confidence: float = 1.0) -> dict:
    """A perfect Gemini response for a fixture, built from the manifest answer key."""
    gt = MANIFEST[file]["ground_truth"]
    inv = {k: gt.get(k) for k in InvoiceFields.model_fields if k != "line_items"}
    inv["document_type"] = "tax_invoice"
    inv["line_items"] = [{k: li.get(k) for k in LineItem.model_fields} for li in gt["line_items"]]
    if any(li["cgst_amt"] for li in gt["line_items"]):
        inv["total_tax"] = None  # intra-state invoices print CGST + SGST rows, no total-tax row

    conf = {k: confidence for k in inv if k != "line_items"}
    conf["line_items"] = [{k: confidence for k in LineItem.model_fields} for _ in inv["line_items"]]
    return {"invoice": inv, "confidence": conf}
