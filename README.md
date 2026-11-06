# Zamp Invoice AP

Invoice processing pipeline for the Zamp ASA PS-1 case study. Spec: [PRD.md](PRD.md).

```
backend/   FastAPI + SQLite — the 4 buckets live in app/pipeline/
frontend/  Next.js — Upload, Live Run, Dashboard, Settings
```

## Run

```bash
# backend (from repo root) — venv is Python 3.12
.venv/Scripts/python.exe -m pip install -r backend/requirements.txt
cd backend && ../.venv/Scripts/python.exe -m uvicorn app.main:app --reload   # http://localhost:8000/health
../.venv/Scripts/python.exe -m pytest -q

# frontend
cd frontend && npm install && npm run dev   # http://localhost:3000
```

Copy `backend/.env.example` to `backend/.env` and set `ANTHROPIC_API_KEY`.
