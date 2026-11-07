import json
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, UploadFile
from google.genai import errors as genai_errors

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
