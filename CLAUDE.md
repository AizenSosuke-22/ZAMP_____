# Zamp Invoice AP — Claude context

Invoice processing pipeline for the Zamp ASA PS-1 case study. **Spec: [PRD.md](PRD.md)** — read it first.

## Current state (as of 2026-11-09, Monday evening — submission day)

- **UI built (2026-11-09):** single-page workbench in `frontend/app/` (`_components/Workbench.tsx` orchestrates; `UploadZone`, `LiveRun`, `DecisionCard`, `SettingsPanel`, `RecentRuns`, `Toaster`; `_lib/` = types, API client, formatting). Light mode, system fonts, indigo accent. No polling: `POST /run` is synchronous, so the Live Run replays the real results step by step (~150 ms/check) with real server timings. Settings flip = price-tolerance slider (saves on settle -> `PATCH /api/config`) + "Re-run" -> run-to-run diff (changed check tagged "Failed → Passed", old badge struck, confidence counts up, narrative crossfades). Verified in headless Edge (Playwright, dev-only in `.venv`): #1 auto-approve, #4/#7 reject, #10 flag -> auto-approve at ±3%. Screenshots in `.impeccable/review/`. Product context in `PRODUCT.md`; direction contract in `.impeccable/surfaces/`.
- **Backend additions (2026-11-09):** CORS for :3000; `GET /api/cases?limit=20`; `GET`/`PATCH /api/config` (Settings writes `data/config.json`, gitignored, overriding `config_default.json`; each save bumps `config_version`; `run_case.py --reset` deletes it); per-check `elapsed_ms` + dossier `timings_ms`; `NARRATIVE_CACHE_ONLY=1` in `.env` = cached narrative or template, never a network call (**keep it 1 for the demo**; set 0 only to warm the cache). Auto-approve next step / template now read "Ready for <approver> sign-off" (DoA decision below). 48 tests.
- **Narratives cached (2026-11-09, billing on, `narrative-v3`):** all 10 fixtures + #10 under ±3% (11 entries), verified by a cache-only replay. Cache keys depend on FACTS, so the flip narrative hits only when #10 is re-run after #1–#9 exist (upload all 10 in order).

- **Backend complete and tested:** Collection + Categorization + Extraction + Processing + Verdict. **43 tests passing; 10/10 fixture decisions + routing labels match the manifest.** Branch `gemini-sdk-switch`, commits up to `cb8137d` (not pushed). `docs/` (plan-processing.md, plan-verdict.md) is untracked.
- **Done Saturday night:** Verdict V1–V6 (state, weakest-link confidence, Decision Card, Processed Invoice Record, persistence + exports, override hook), the narrative validator with template fallback, and the hash-chained append-only audit log.
- **Backend** (`backend/`): all 4 buckets built (backend only). `POST /api/invoices/upload`, `POST /api/cases/{id}/run[?use_cache=false]` -> `{case_id, dossier, decision_card, processed_invoice_record}` (case status -> `decided`), `GET /api/cases/{id}` (+ latest card/record/audit/overrides), `POST /api/cases/{id}/override`, `GET /api/cases/{id}/export.{json,csv,pdf}`. Paths + `PIPELINE_VERSION` in `app/settings.py`; SQLite `data/ap.db` (`app/db.py`); schemas in `app/models.py`; orchestration + V5 persistence + V6 override in `app/pipeline/runner.py`; exports in `app/exports.py`. 43 offline tests (Gemini stubbed for extraction; narratives forced to template by an autouse conftest stub). `scripts/run_case.py [--reset] <pdf...>` = end-to-end vs manifest (processing table + verdict table + decision cards). Live run 2026-11-07: **10/10 decisions + routing labels match manifest**.
- **Verdict** (`app/pipeline/verdict.py`, per `docs/plan-verdict.md`, approved 2026-11-07): V1 = `decision_hint()` then band (Low -> flag, Medium -> pending, High -> auto) then OCR policy. V2 = **min**(required-field confidence, share of evaluated T3 ops that passed, our line-item total == printed total). Routing labels in fixed priority (`LABELS`); "low extraction confidence" only when Low is *why* it's flagged. Journal: Dr F1 GL + Input GST 1310/1320/1330, Cr/Dr 5990 Round-off, Cr 2100; none for reject/fraud. `audit_log` + `overrides` append-only (SQLite triggers) and hash-chained; `dashboard` = mutable one-row-per-case projection; re-run appends a new verdict and clears the dashboard override.
- **Narrative** (`app/pipeline/narrative.py`, `NARRATIVE_PROMPT_VERSION`): FACTS -> Gemini (12 s timeout; API rejects < 10 s) -> validator (1-3 sentences, <= 90 words, no jargon, no number absent from FACTS) -> else template. Raw output cached in `data/cache/narrative_*` and re-validated on use.
- **Gemini billing enabled 2026-11-09** (free tier was 20 requests/day per model, hit 2026-11-07). Each fixture costs 1 extraction + 1 narrative; a cold `--reset` run with a warm cache costs 0. Extraction (10) and narrative (11) caches are warm.
- **Processing** (`app/pipeline/processing.py`, per `docs/plan-processing.md`, approved 2026-11-07): Ops 1-10 + advisory **F1** (coding = vendor-master default GL/cost center, `coding_suggestion` toggle). T1 fail -> rest `skipped`; Op 7 fail -> Op 8 `not_evaluated`. Dossier gets `resolved` {entity_id, vendor_id, po_number}, `missing_required_fields` (null required field -> flag; drives #9). `processing.decision_hint()` = fraud_alert/reject/flag/approve (first half of V1). "Earlier cases" = lower case ID, processed, not T1-blocked; those that passed Op 7 reserve PO balance + qty. Over-billing PO balance allowed up to the total tolerance. Op 10 = GSTIN format/checksum/state/PAN + mocked active list (`gstin_active_check`) + HSN shape + slab + reference rate (`data/hsn_gst_rates.json`, written by the generator) + intra/inter (CGST+SGST vs IGST). Settings spine verified: #10 flag -> approve at `price_pct` 3.
- **Extraction**: text layer (bucket B) or rapidocr (bucket C) -> Gemini structured output (`PROMPT_VERSION` in categorization.py) -> grounding: value not found in source text => confidence capped 0.5; OCR path also capped at OCR box score. Gemini output cached in `data/cache/` (gitignored) by sha256+model+prompt version — **pre-warm the cache before the demo** (run all fixtures once).
- **Default config**: `backend/data/config_default.json` — every §10 setting, `config_version: 1`. TDS + ITC removed (config + PRD §9/§10).
- **Gemini**: `google-genai==2.34.0` installed (anthropic uninstalled). Key + `GEMINI_MODEL` in `backend/.env` (gitignored). `backend/test_gemini.py` confirmed `gemini-3.6-flash` reachable on 2026-11-07.
- **Frontend** (`frontend/`): Next 16.4.5, React 19, TS, Tailwind 4 (`cacheComponents` on, `devIndicators: false`). Read `frontend/AGENTS.md` before writing Next code — this Next version has breaking changes.
- **venv**: `.venv` (Python 3.12.10). Bare `python` on this machine is msys 3.11 — always use `.venv/Scripts/python.exe`.

## Decisions locked

- **OCR**: `rapidocr==3.10.0` + `onnxruntime` (user-approved 2026-11-07; replaces frozen `rapidocr-onnxruntime`). Models ship in the wheel — verified offline, no download.
- **LLM for extraction**: `gemini-3.6-flash` (stable, no shutdown date as of 2026-11-07) via the `google-genai` SDK (`from google import genai`). Model ID read from `GEMINI_MODEL` env — never hardcode it; Google retires Flash versions fast (2.0 Flash shut down 2026-06-01; 2.5 Flash deprecated). `google-generativeai` is deprecated — don't use it. google-genai 3.0.0 (released 2026-11-06) deliberately not adopted.
- **Review policy — OCR'd invoices never auto-approve** (user decision 2026-11-07). Config `review_policies.ocr_always_pending_review` (default `true`; Settings toggle later). Implemented in `verdict.apply_review_policies()`: caps `auto_approve` -> `approve_pending_review` when the text came from OCR; never touches flag/reject/fraud and never upgrades. **This is a deliberate control policy, not a bug workaround.** Rationale: extraction confidence measures how sure we are we *read* the page, not that the page is genuine or that OCR didn't misread a digit consistently (seen in testing: OCR read a CGST rate "9" as "6" at score 1.000 and the LLM silently corrected it). Scans/photos are also where tampered or re-typed invoices tend to arrive. A one-click human glance on scanned invoices is cheap insurance, and it's a policy firms differ on — hence a toggle. Demo line: "anything we had to OCR gets a human glance."
- **TDS + ITC: scoped out** entirely (detection, config, Settings UI). Named in the demo cut log.
- **Auto-approve does NOT bypass the DoA** (user decision 2026-11-07). Auto-approve means the pipeline is clean and the invoice is ready for the named DoA approver to sign off. The DoA matrix populates `approver_role` on the Decision Card but does not cap auto-approve. Rationale: matches Oracle AP / SAP / NetSuite convention; auto-approve is a system-confidence signal, not a payment release. A config toggle for a DoA cap is a V2 item.
- **#9 confidence 0.00 stays as-is in the backend** (missing invoice number -> fields component 0). The UI handles the display for this edge case.
- Stack per PRD §16: FastAPI + Next.js + SQLite (stdlib `sqlite3`) + PyMuPDF for PDF text layer.

## PENDING — next session, in order

1. [x] Remove TDS + ITC from config + Settings spec. (PRD §8 V4 "Tax treatment" intentionally left as-is — user decision; journal entry is computed without TDS/ITC.)
2. [x] Switch extraction SDK to `google-genai` + `GEMINI_API_KEY`.
3. [x] Gemini key in `backend/.env`; `test_gemini.py` passes.
4. [x] Synthetic data: `backend/scripts/generate_fixtures.py` → `backend/data/` (entity, vendor_master, po_master, chart_of_accounts, `invoices/*.pdf` + `invoices/manifest.json` answer key). Deterministic (byte-identical reruns); 76 built-in self-checks. Process invoices in file order (#7/#8 need #1, #6 needs #5).
5. [x] Collection + Categorization + Extraction (buckets B, C).
6. [x] Processing (10 ops + F1). [x] Verdict (V1-V6), backend.
### First thing Sunday (before any UI work)

7. [x] **Enable billing on the Gemini API** (user; if not done Saturday night). The free tier is 20 requests/day per model, which is not enough to warm the cache or run the demo.
8. [x] **Warm the narrative cache** (done 2026-11-09; #10 at ±3% cached via `PATCH /api/config` + `run_case.py`):
   - `cd backend && ../.venv/Scripts/python.exe scripts/run_case.py --reset data/invoices/*.pdf` (10 narrative calls; extraction is already cached).
   - Re-run #10 under `tolerances.price_pct = 3` to cache the Settings-flip narrative. There's no flag for this yet: edit `config_default.json`, run `run_case.py data/invoices/10_outside_tolerance.pdf`, then revert. Or add a `--price-pct` flag to `run_case.py`.
9. [~] **Review the regenerated narratives** (#3/#9 tone fixed in `narrative-v3` 2026-11-09; fraud one-off not done) for #3, #8, #10 and a fraud case against the targets in `docs/plan-verdict.md` §3. No fixture is a fraud case, so generate one as a one-off: #1 with a changed bank account, as in `tests/test_verdict.py::test_bank_mismatch_is_fraud_alert`, but with live Gemini. If the tone is off, calibrate `SYSTEM_PROMPT` in `narrative.py` and bump `NARRATIVE_PROMPT_VERSION` (currently `narrative-v3`: v3 added "pending = the analyst confirms, never 'we approved'" and "never describe which checks ran").

### Sunday build plan (PRD §12, §16)

10. [x] **UI shell (built Monday 2026-11-09):** Upload view, Live Run view (stages Collection → Categorization → A–F → Verdict, op results inline), Decision Card rendering. This includes the display for #9's 0.00 confidence (see Decisions locked). Read `frontend/AGENTS.md` first.
11. [~] **Dashboard + Settings:** done as one page (Recent runs list + price-tolerance slider). Not built: dashboard filters, status/label counts, overrides panel, other Settings fields. Dashboard table with filters, row → drill-down, status/label counts, and an overrides panel. The Settings page edits the §10 config and bumps `config_version` (it's the demo spine: flip `price_pct` and re-run #10). The backend needs list + config endpoints for these; they don't exist yet.

Open items:
- **Design review pass + `DESIGN.md` = V2 item** (user decision 2026-11-09: skipped to spend the time on rehearsal + recording).
- PO reservation counts every earlier non-blocked case linked to the PO; could be refined to approved / pending only.

## Current cached narratives (`narrative-v3`, Gemini, cached 2026-11-09)

Shown verbatim on the Decision Card in the demo (cache-only mode). Regenerating needs `NARRATIVE_CACHE_ONLY=0`, a prompt-version bump, and all 10 fixtures run in order plus #10 at ±3%.

- **#3 scanned (Approve pending review):** "This invoice for Rs 89,090.00 from Sahyadri Facility Management Pvt Ltd is ready for your one-click confirmation. Because it was read from a scan, our policy requires a brief check even though every check passed against purchase order PO-2026-0377. Give it a quick look and confirm with one click."
- **#9 missing invoice number (Flagged for review):** "We flagged this Rs 1,18,000.00 document for purchase order PO-2026-0391 because the invoice doesn't show an invoice number. Please contact Kaveri Infotech Services Pvt Ltd to request a corrected invoice that includes their invoice number."

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
