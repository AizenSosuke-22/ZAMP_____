"""Endpoints the UI uses: config read/patch, case list, CORS, cache-only narratives."""
from app import settings
from app.pipeline import narrative
from tests.conftest import INVOICES


def test_config_patch_bumps_version_and_persists(client):
    assert client.get("/api/config").json()["tolerances"]["price_pct"] == 2.0
    r = client.patch("/api/config", json={"price_pct": 3})
    assert r.status_code == 200 and r.json()["config_version"] == 2 and r.json()["tolerances"]["price_pct"] == 3.0
    assert client.get("/api/config").json()["config_version"] == 2
    assert client.get("/health").json()["config_version"] == 2
    assert (settings.DATA_DIR / "config_default.json").read_text(encoding="utf-8").count('"price_pct": 2.0') == 1


def test_config_patch_rejects_out_of_range(client):
    assert client.patch("/api/config", json={"price_pct": 9}).status_code == 422
    assert client.get("/api/config").json()["config_version"] == 1


def test_list_cases_newest_first(client):
    for f in ("01_happy_path.pdf", "04_proforma.pdf"):
        client.post("/api/invoices/upload", files=[("files", (f, (INVOICES / f).read_bytes(), "application/pdf"))])
    cases = client.get("/api/cases").json()["cases"]
    assert [c["filename"] for c in cases] == ["04_proforma.pdf", "01_happy_path.pdf"]
    assert cases[0]["decision_state"] is None  # not run yet


def test_cors_allows_ui_origin(client):
    r = client.options("/api/config", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "PATCH"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_cache_only_never_calls_gemini(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(settings, "NARRATIVE_CACHE_ONLY", True)
    monkeypatch.setattr(narrative, "call_gemini", lambda facts: (_ for _ in ()).throw(AssertionError("network")))
    facts = {"decision": "auto_approve", "issues": [], "notes": [], "next_action": "No action needed."}
    text, source, why = narrative.write(facts)
    assert source == "template" and "cache-only" in why
