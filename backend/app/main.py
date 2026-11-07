import json
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, UploadFile
from fastapi.responses import Response
from google.genai import errors as genai_errors
from pydantic import BaseModel

from app import exports
from app.pipeline import collection, runner

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MAX_UPLOAD_BYTES = 20 * 1024 * 1024

app = FastAPI(title="Zamp Invoice AP")


@app.get("/health")
def health():
    config = json.loads((DATA_DIR / "config_default.json").read_text(encoding="utf-8"))
    return {"status": "ok", "config_version": config["config_version"]}


@app.post("/api/invoices/upload", status_code=201)
async def upload(files: list[UploadFile], uploaded_by: str = Form("demo-analyst")):
    contents = [(f.filename, await f.read()) for f in files]
    for name, content in contents:  # validate the whole batch before ingesting any of it
        if not content.startswith(b"%PDF-"):
            raise HTTPException(415, f"{name}: only PDF files are accepted")
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, f"{name}: larger than 20 MB")
    return {"results": [collection.ingest(name, content, uploaded_by) for name, content in contents]}


@app.post("/api/cases/{case_id}/run")
def run(case_id: str, use_cache: bool = True):
    case = runner.get_case(case_id)
    if not case:
        raise HTTPException(404, f"{case_id} not found")
    if case["status"] == "needs_human":
        raise HTTPException(409, f"{case_id} needs human intervention: {case['status_reason']}")
    try:
        return runner.run_case(case, use_cache)
    except genai_errors.APIError as e:
        raise HTTPException(502, f"Extraction model error: {e.code} {e.status}: {e.message}")


@app.get("/api/cases/{case_id}")
def get_case(case_id: str):
    case = runner.get_case(case_id)
    if not case:
        raise HTTPException(404, f"{case_id} not found")
    return case


def _decided(case_id: str) -> dict:
    case = runner.get_case(case_id)
    if not case:
        raise HTTPException(404, f"{case_id} not found")
    if not case["decision_card"]:
        raise HTTPException(409, f"{case_id} has no verdict yet - run it first")
    return case


class OverrideIn(BaseModel):
    new_state: str
    reason: str
    overridden_by: str


@app.post("/api/cases/{case_id}/override", status_code=201)
def override(case_id: str, body: OverrideIn):
    """V6: human override. Appends to the overrides log; the original verdict is never rewritten."""
    try:
        return runner.override(case_id, body.new_state, body.reason, body.overridden_by)
    except LookupError as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.get("/api/cases/{case_id}/export.json")
def export_json(case_id: str):
    c = _decided(case_id)
    return {"processed_invoice_record": c["processed_invoice_record"], "audit": c["audit"],
            "override_state": c["override_state"], "overrides": c["overrides"]}


@app.get("/api/cases/{case_id}/export.csv")
def export_csv(case_id: str):
    c = _decided(case_id)
    return Response(exports.to_csv(c["processed_invoice_record"], c["override_state"]), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{case_id}.csv"'})


@app.get("/api/cases/{case_id}/export.pdf")
def export_pdf(case_id: str):
    c = _decided(case_id)
    pdf = exports.to_pdf(c["decision_card"], c["processed_invoice_record"], c["audit"], c["overrides"])
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{case_id}.pdf"'})
