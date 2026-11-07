# Zamp Invoice AP — Claude context

Invoice processing pipeline for the Zamp ASA PS-1 case study. **Spec: [PRD.md](PRD.md)** — read it first.

## Current state (as of 2026-11-07)

- Repo set up; initial commit contains the scaffold below.
- **Backend** (`backend/`): Collection + Categorization/Extraction + Processing built. `POST /api/invoices/upload`, `POST /api/cases/{id}/run[?use_cache=false]` (case status -> `processed`), `GET /api/cases/{id}`. Paths in `app/settings.py`; SQLite `data/ap.db` (`app/db.py`); schemas in `app/models.py` (Invoice, OpResult, Dossier); orchestration `app/pipeline/runner.py`. `verdict.py` has only `apply_review_policies()`. 30 offline tests (Gemini stubbed). `scripts/run_case.py [--reset] <pdf...>` = end-to-end vs manifest; one file adds the per-field extraction report (#1: 44/44, #3: 43/44). Live run 2026-11-07: **10/10 fixtures match** (all 10 now in the Gemini cache).
- **Processing** (`app/pipeline/processing.py`, per `docs/plan-processing.md`, approved 2026-11-07): Ops 1-10 + advisory **F1** (coding = vendor-master default GL/cost center, `coding_suggestion` toggle). T1 fail -> rest `skipped`; Op 7 fail -> Op 8 `not_evaluated`. Dossier gets `resolved` {entity_id, vendor_id, po_number}, `missing_required_fields` (null required field -> flag; drives #9). `processing.decision_hint()` = fraud_alert/reject/flag/approve (first half of V1). "Earlier cases" = lower case ID, processed, not T1-blocked; those that passed Op 7 reserve PO balance + qty. Over-billing PO balance allowed up to the total tolerance. Op 10 = GSTIN format/checksum/state/PAN + mocked active list (`gstin_active_check`) + HSN shape + slab + reference rate (`data/hsn_gst_rates.json`, written by the generator) + intra/inter (CGST+SGST vs IGST). Settings spine verified: #10 flag -> approve at `price_pct` 3.
- **Extraction**: text layer (bucket B) or rapidocr (bucket C) -> Gemini structured output (`PROMPT_VERSION` in categorization.py) -> grounding: value not found in source text => confidence capped 0.5; OCR path also capped at OCR box score. Gemini output cached in `data/cache/` (gitignored) by sha256+model+prompt version — **pre-warm the cache before the demo** (run all fixtures once).
- **Default config**: `backend/data/config_default.json` — every §10 setting, `config_version: 1`. TDS + ITC removed (config + PRD §9/§10).
- **Gemini**: `google-genai==2.34.0` installed (anthropic uninstalled). Key + `GEMINI_MODEL` in `backend/.env` (gitignored). `backend/test_gemini.py` confirmed `gemini-3.6-flash` reachable on 2026-11-07.
- **Frontend** (`frontend/`): untouched `create-next-app` default (Next 16.4.5, React 19, TS, Tailwind 4). Builds. Read `frontend/AGENTS.md` before writing Next code — this Next version has breaking changes.
- **venv**: `.venv` (Python 3.12.10). Bare `python` on this machine is msys 3.11 — always use `.venv/Scripts/python.exe`.

## Decisions locked

- **OCR**: `rapidocr==3.10.0` + `onnxruntime` (user-approved 2026-11-07; replaces frozen `rapidocr-onnxruntime`). Models ship in the wheel — verified offline, no download.
- **LLM for extraction**: `gemini-3.6-flash` (stable, no shutdown date as of 2026-11-07) via the `google-genai` SDK (`from google import genai`). Model ID read from `GEMINI_MODEL` env — never hardcode it; Google retires Flash versions fast (2.0 Flash shut down 2026-06-01; 2.5 Flash deprecated). `google-generativeai` is deprecated — don't use it. google-genai 3.0.0 (released 2026-11-06) deliberately not adopted.
- **Review policy — OCR'd invoices never auto-approve** (user decision 2026-11-07). Config `review_policies.ocr_always_pending_review` (default `true`; Settings toggle later). Implemented in `verdict.apply_review_policies()`: caps `auto_approve` -> `approve_pending_review` when the text came from OCR; never touches flag/reject/fraud and never upgrades. **This is a deliberate control policy, not a bug workaround.** Rationale: extraction confidence measures how sure we are we *read* the page, not that the page is genuine or that OCR didn't misread a digit consistently (seen in testing: OCR read a CGST rate "9" as "6" at score 1.000 and the LLM silently corrected it). Scans/photos are also where tampered or re-typed invoices tend to arrive. A one-click human glance on scanned invoices is cheap insurance, and it's a policy firms differ on — hence a toggle. Demo line: "anything we had to OCR gets a human glance."
- **TDS + ITC: scoped out** entirely (detection, config, Settings UI). Named in the demo cut log.
- Stack per PRD §16: FastAPI + Next.js + SQLite (stdlib `sqlite3`) + PyMuPDF for PDF text layer.

## PENDING — next session, in order

1. [x] Remove TDS + ITC from config + Settings spec. (PRD §8 V4 "Tax treatment" intentionally left as-is — user decision; journal entry is computed without TDS/ITC.)
2. [x] Switch extraction SDK to `google-genai` + `GEMINI_API_KEY`.
3. [x] Gemini key in `backend/.env`; `test_gemini.py` passes.
4. [x] Synthetic data: `backend/scripts/generate_fixtures.py` → `backend/data/` (entity, vendor_master, po_master, chart_of_accounts, `invoices/*.pdf` + `invoices/manifest.json` answer key). Deterministic (byte-identical reruns); 76 built-in self-checks. Process invoices in file order (#7/#8 need #1, #6 needs #5).
5. [x] Collection + Categorization + Extraction (buckets B, C).
6. [x] Processing (10 ops + F1). [ ] Verdict (V1-V6) — next. Open items for Verdict:
   - #3 scan extracts at confidence 0.99 (High band); its expected `approve_pending_review` comes from the OCR review policy (see Decisions locked). V1 must call `verdict.apply_review_policies()` after deciding the state.
   - Gemini fills `total_tax` on intra-state invoices despite prompt rule 1 (grounding catches it -> 0.5). Optional/derived fields must not drag decision confidence — V2 uses required fields only.
   - OCR misread line 2 CGST rate as "6"; Gemini silently corrected to 9 @ 1.00. Arithmetic op (Op 9) is the real safety net (test `test_ocr_rate_misread_caught_by_arithmetic`).
   - PO reservation counts every earlier non-blocked case linked to the PO; could be refined to approved / pending only once verdicts exist.

## Cut log (demo + interview answer sheet)

- **TDS + ITC** — detection, config and Settings UI scoped out (see Decisions locked).
- **Op 8 is a 2-way match, not 3-way** — PO vs invoice only; we have no goods-receipt (GRN) data. Labelled honestly in the op's evidence and reason: "2-way (no goods-receipt data in this build)". 3-way needs GRN fixtures (~½ day).
- **Per-line billed qty from the PO master** — master only has amount `billed_to_date`, so Op 8's quantity check counts invoices seen by this system only (Op 7's balance check uses the master's amount).
- **Fuzzy vendor-name match** (edge case 4) — Op 3 matches exact GSTIN or exact legal name / alias only.

## Commands

```bash
cd backend && ../.venv/Scripts/python.exe -m pytest -q                       # tests
cd backend && ../.venv/Scripts/python.exe -m uvicorn app.main:app --reload    # API :8000
cd frontend && npm run dev                                                    # UI :3000
```

## Working style

Follow the karpathy-guidelines skill: minimum code, surgical changes, state assumptions, verify before claiming done.
