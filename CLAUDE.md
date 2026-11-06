# Zamp Invoice AP — Claude context

Invoice processing pipeline for the Zamp ASA PS-1 case study. **Spec: [PRD.md](PRD.md)** — read it first.

## Current state (as of 2026-11-07)

- Repo set up; initial commit contains the scaffold below.
- **Backend** (`backend/`): FastAPI app with only `/health` (`app/main.py`); one docstring-only module per bucket in `app/pipeline/` (collection, categorization, processing, verdict); 1 passing smoke test (`tests/test_health.py`).
- **Default config**: `backend/data/config_default.json` — every §10 setting, `config_version: 1`. Still contains TDS + ITC entries (see PENDING).
- **Frontend** (`frontend/`): untouched `create-next-app` default (Next 16.4.5, React 19, TS, Tailwind 4). Builds. Read `frontend/AGENTS.md` before writing Next code — this Next version has breaking changes.
- **venv**: `.venv` (Python 3.12.10). Bare `python` on this machine is msys 3.11 — always use `.venv/Scripts/python.exe`.

## Decisions locked

- **OCR**: `rapidocr-onnxruntime` (pip-installable, offline — fits PRD §14b demo determinism). Not installed yet.
- **LLM for extraction**: Gemini 2.0 Flash.
- **TDS + ITC: scoped out** entirely (detection, config, Settings UI). Named in the demo cut log.
- Stack per PRD §16: FastAPI + Next.js + SQLite (stdlib `sqlite3`) + PyMuPDF for PDF text layer.

## PENDING — next session, in order

1. [ ] **Remove TDS + ITC** from `backend/data/config_default.json` (`tds_matrix`, `itc_blocked_hsns_or_categories`) and from the Settings spec.
2. [ ] **Switch extraction SDK to `google-generativeai`**: remove `anthropic` from `backend/requirements.txt`, uninstall it from `.venv`, rename `ANTHROPIC_API_KEY` in `backend/.env.example` and `README.md`. No Anthropic SDK reference should remain.
   - ⚠ Verify before installing: `google-generativeai` was deprecated by Google in favour of `google-genai`, and Gemini 2.0 Flash may be retired/scheduled for retirement. Confirm the model ID is still served and which SDK to use — raise with user if either has changed.
3. [ ] **User pastes Gemini API key into `backend/.env`** — the file does not exist yet; only `backend/.env.example` does. Copy the example, then the user fills the key. Never commit `.env` (gitignored).
4. [ ] **Run the synthetic data generator** (PRD §13): ~10 invoice PDFs, ~20 POs across 5 vendors (incl. one split PO), 5–7 vendor master rows, ~15 GL accounts. Generator not written yet.

## Commands

```bash
cd backend && ../.venv/Scripts/python.exe -m pytest -q                       # tests
cd backend && ../.venv/Scripts/python.exe -m uvicorn app.main:app --reload    # API :8000
cd frontend && npm run dev                                                    # UI :3000
```

## Working style

Follow the karpathy-guidelines skill: minimum code, surgical changes, state assumptions, verify before claiming done.
