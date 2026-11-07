# Zamp Invoice AP — Claude context

Invoice processing pipeline for the Zamp ASA PS-1 case study. **Spec: [PRD.md](PRD.md)** — read it first.

## Current state (as of 2026-11-07)

- Repo set up; initial commit contains the scaffold below.
- **Backend** (`backend/`): FastAPI app with only `/health` (`app/main.py`); one docstring-only module per bucket in `app/pipeline/` (collection, categorization, processing, verdict); 1 passing smoke test (`tests/test_health.py`).
- **Default config**: `backend/data/config_default.json` — every §10 setting, `config_version: 1`. TDS + ITC removed (config + PRD §9/§10).
- **Gemini**: `google-genai==2.34.0` installed (anthropic uninstalled). Key + `GEMINI_MODEL` in `backend/.env` (gitignored). `backend/test_gemini.py` confirmed `gemini-3.6-flash` reachable on 2026-11-07.
- **Frontend** (`frontend/`): untouched `create-next-app` default (Next 16.4.5, React 19, TS, Tailwind 4). Builds. Read `frontend/AGENTS.md` before writing Next code — this Next version has breaking changes.
- **venv**: `.venv` (Python 3.12.10). Bare `python` on this machine is msys 3.11 — always use `.venv/Scripts/python.exe`.

## Decisions locked

- **OCR**: `rapidocr-onnxruntime` (pip-installable, offline — fits PRD §14b demo determinism). Not installed yet.
- **LLM for extraction**: `gemini-3.6-flash` (stable, no shutdown date as of 2026-11-07) via the `google-genai` SDK (`from google import genai`). Model ID read from `GEMINI_MODEL` env — never hardcode it; Google retires Flash versions fast (2.0 Flash shut down 2026-06-01; 2.5 Flash deprecated). `google-generativeai` is deprecated — don't use it. google-genai 3.0.0 (released 2026-11-06) deliberately not adopted.
- **TDS + ITC: scoped out** entirely (detection, config, Settings UI). Named in the demo cut log.
- Stack per PRD §16: FastAPI + Next.js + SQLite (stdlib `sqlite3`) + PyMuPDF for PDF text layer.

## PENDING — next session, in order

1. [x] Remove TDS + ITC from config + Settings spec. (PRD §8 V4 "Tax treatment" intentionally left as-is — user decision; journal entry is computed without TDS/ITC.)
2. [x] Switch extraction SDK to `google-genai` + `GEMINI_API_KEY`.
3. [x] Gemini key in `backend/.env`; `test_gemini.py` passes.
4. [x] Synthetic data: `backend/scripts/generate_fixtures.py` → `backend/data/` (entity, vendor_master, po_master, chart_of_accounts, `invoices/*.pdf` + `invoices/manifest.json` answer key). Deterministic (byte-identical reruns); 76 built-in self-checks. Process invoices in file order (#7/#8 need #1, #6 needs #5).
   - ⚠ Before building OCR: `rapidocr-onnxruntime` is frozen at 1.4.4 (Jan 2025); successor is `rapidocr` (3.x). Decide with user. Confirm `03_scanned.pdf` OCRs cleanly — tune `make_scanned()` noise if not.

## Commands

```bash
cd backend && ../.venv/Scripts/python.exe -m pytest -q                       # tests
cd backend && ../.venv/Scripts/python.exe -m uvicorn app.main:app --reload    # API :8000
cd frontend && npm run dev                                                    # UI :3000
```

## Working style

Follow the karpathy-guidelines skill: minimum code, surgical changes, state assumptions, verify before claiming done.
