# Zamp ASA PS-1 — Invoice Processing PRD

Nov 6, 2026 · @Priyadarshi Ubale

## 1 · Context & Objective

This document specifies the invoice processing automation we will build for the Zamp AI Solutions Analyst case study (Problem Statement 1 — Finance / AP). The one-week build culminates in a live, runnable process and a 5-minute demo video; if the submission moves forward, it is demoed live in the follow-up interview.

**The problem.** A mid-size company receives hundreds of vendor invoices every month, arriving as PDFs attached to email. Someone on the AP team opens each one, finds the matching purchase order in a spreadsheet, checks the numbers, and decides what to do with it. Invoices arrive in wildly different formats — clean digital PDFs, scans, phone photos, handwritten receipts — with varying completeness. Matching logic is non-trivial: a vendor may split a PO across multiple invoices, amounts may be close but not exact, and critical fields may be missing. The process is repetitive, slow, and prone to expensive mistakes.

**What we are building.** A process that takes an invoice as input and produces a clear, reasoned decision as output, with every intermediate step visible. The decision tells an AP analyst exactly what to do next, and the system produces a structured, canonical invoice record the analyst can hand straight to the ERP. The AP analyst stays in the loop — we help, we don't replace.

**What this is not.** A black-box classifier that spits out "approve / reject." The output is a decision plus the full reasoning trail plus the structured record. The reasoning has to be legible to a non-technical reader.

## 2 · Users

**Primary user — AP Analyst.** Mid-size Indian company. Processes 100–300 invoices per week. Not technical. Needs:

- Fast triage of clean cases (so attention goes to exceptions)
- Clear reasoning when something is flagged (so they know what to fix or query)
- Structured output they can post to the ERP (so the automation genuinely saves work, not just reads invoices)
- Confidence in an audit trail (so compliance and the finance controller trust the system)

**Secondary user — Finance Controller / CFO.** Doesn't touch invoices; looks at the dashboard. Cares about AP aging, exception volume, DPO trends, control effectiveness.

**Buyer (demo audience) — Zamp hiring team.** Evaluating product judgement, understanding of operational problems, and ability to explain a build fluently to a non-technical audience. The demo narrative is as graded as the code.

## 3 · Scope

**In scope**

| Area | Specifics |
| --- | --- |
| Intake | Email watcher (simulated) + manual web upload |
| Extraction | Digital PDFs (text layer) + OCR for scans / images |
| Classification | Document type + routing bucket (7 buckets) |
| Verification | Vendor master, PO lookup, bank-detail integrity |
| Matching | Line-item match, qty / price / total checks, tolerances |
| Validation | Duplicate detection (hard + near), arithmetic, GST, TDS |
| Coding | Suggested GL account, cost center, capex / opex (advisory) |
| Decision | 5 states (Auto-approve / Approve pending / Flag / Reject / Fraud alert) |
| Reasoning | Short narrative + full failed-check trail + confidence score |
| Output | Decision Card + Processed Invoice Record (CSV / JSON / PDF export) |
| UI | Upload, live run view, dashboard, decision drill-down, settings |
| Config | Editable thresholds + a slice of on / off toggles |
| Edge cases | 3 chosen (see §11) |

**Out of scope** (see §15 for rationale)

Journal posting to ERP · payment scheduling / execution · TDS deposit + 26Q filing · GSTR-2B reconciliation · vendor statement reconciliation · vendor onboarding (PS-2) · approval workflow execution · vendor query drafting / sending · vendor-behavior pattern analytics.

## 4 · System Overview — The 4 Buckets

Four buckets, in sequence. Each has a clean input, a clean output, and one responsibility.

```
┌───────────────┐    ┌────────────────┐    ┌───────────────┐    ┌───────────┐
│  COLLECTION   │──→ │ CATEGORIZATION │──→ │  PROCESSING   │──→ │  VERDICT  │
│               │    │                │    │               │    │           │
│ Email / Upload│    │ Classify + OCR │    │ 22 ops across │    │ Decide +  │
│ Ingest + hash │    │ + extract      │    │ 6 stages with │    │ reason +  │
│               │    │ (7 buckets)    │    │ tier gating   │    │ output    │
└───────────────┘    └────────────────┘    └───────────────┘    └───────────┘
      ↓                     ↓                     ↓                   ↓
   PDF + meta         Invoice JSON +         Dossier             Decision Card
                      per-field conf                            + Processed
                                                                Invoice Record
```

- **Collection** — gets the file into the system.
- **Categorization** — figures out *what kind of thing it is* and *extracts fields from it.*
- **Processing** — runs all business-logic checks and produces an evidence dossier.
- **Verdict** — reads the dossier and produces a decision + a structured record the AP analyst can act on.

Clean interfaces between buckets are what let us iterate on one without breaking the next.

## 5 · Bucket 1 — Collection

**Input:** a new invoice, from any channel. **Output:** raw file (PDF / image / text) + ingest metadata (channel, source, timestamp, SHA-256 hash) + a new case ID.

### Channels

| Channel | In scope | Notes |
| --- | --- | --- |
| Email watcher (simulated inbox) | ✅ | Mock `ap@company.com` with sample emails; in production an IMAP / API watcher |
| Manual web upload | ✅ | Drag-drop file via UI |
| Shared drive watcher | ❌ | Named as scoped-out |
| Vendor portal push | ❌ | Named as scoped-out |
| GSTN / IRP push (e-invoice) | ❌ | Named as scoped-out |

### Ingest flow

1. New file detected (email attachment / upload).
2. SHA-256 the file — used for hard duplicate detection downstream.
3. If **email**: parse headers → resolve original sender (through forwards), split multiple attachments into separate cases, detect email-body-only invoices, detect password-protected PDFs.
4. If **upload**: tag with uploader identity for audit.
5. Assign new case ID; write ingest metadata.
6. Hand off to Categorization.

### Collection-time concerns handled here

- **Forwarded emails** — the apparent sender in a forwarded chain is the forwarder, not the vendor. Parse forwarded headers to find the original sender.
- **Multiple invoices per email** — spawn one case per attachment.
- **Zip / compressed attachments** — extract and fan out.
- **Password-protected PDFs** — detect at ingest, flag immediately for human intervention (do not attempt to crack).
- **Hard duplicate at ingest** — if hash matches a previously ingested file, drop silently (log but don't create a case).
- **Email identification** — classifier on subject + attachment type + sender domain to decide whether an email is actually an invoice, so marketing emails and OTPs don't enter the queue.

## 6 · Bucket 2 — Categorization

**Input:** raw file + ingest metadata. **Output:** extracted invoice JSON (canonical schema) + per-field confidence scores + original file reference + the routing bucket it was placed in.

### Two-axis framing

Extraction difficulty and document validity are independent axes.

|  | Easy to extract | Hard to extract |
| --- | --- | --- |
| **Valid invoice** | Clean digital PDF (fast path) | Handwritten bill from legit vendor |
| **Invalid document** | Clean PDF of a pro forma (readable, reject) | Blurry photo of something that isn't an invoice |

Difficulty does not equal validity — the system must score them separately.

### 7 routing buckets

| Bucket | What routes here | Pipeline branch |
| --- | --- | --- |
| **A · Structured** | E-invoice with valid IRN QR, or standardised ERP-generated PDF | Parse structured fields, skip LLM extraction |
| **B · Text-layer PDF** | Digital PDF, unfamiliar template | LLM extraction on raw text |
| **C · Image + OCR** | Scanned PDF, clear photo | OCR → LLM extraction, confidence scored |
| **D · Low confidence** | Blurry, skewed, partial | Bounce back for better copy; cap at N retries |
| **E · Handwritten** | Hand-filled or hand-written receipt | Flag for human review from the start |
| **F · Wrong document type** | Pro forma, quote, customer receipt, marketing PDF | Immediate flag with reason |
| **G · Missing mandatory fields** | No invoice #, no GSTIN, no total | Flag with specific vendor query template |

Buckets A–C are automated paths. D, E, F, G are human-in-loop by design — not failures, just the system correctly identifying what it should not decide alone.

### Document-type classification (runs first inside Categorization)

LLM classification on header + body. Is this a tax invoice / pro forma / credit note / debit note / statement / customer-side receipt / not an invoice at all? Routes to bucket F if not a tax invoice; routes credit / debit notes to a separate downstream flow.

### Resubmission loop

A resubmitted invoice keeps the same **case ID**. Case ID carries a retry counter. After N retries (configurable; default 3), the system stops bouncing back and escalates to human review regardless of quality.

## 7 · Bucket 3 — Processing

**Input:** extracted invoice JSON + per-field confidence + original file. **Output:** the **Dossier** — a structured record of every check run, with results, severity, confidence, evidence, and skip reasons.

*Scoped down from 22 ops to 10 per council review. Dropped from Processing: TDS section/rate detection, ITC eligibility classification (Sec 17(5)), reverse charge applicability, GL coding depth — all named in the demo as deliberately scoped out, with a one-line reason each. Scoping discipline is itself a judgement signal for the grader.*

### Tier system (governs gating / short-circuit behaviour)

| Tier | Behaviour on fail |
| --- | --- |
| **T1 · Blocker** | Stop pipeline. Downstream ops marked `skipped`. Jump to Verdict with blocker reason. |
| **T2 · Structural** | Keep running, but mark dependent ops `not evaluated`. |
| **T3 · Validation** | Keep running. Logged as a fail with severity. |
| **T4 · Advisory** | Keep running. Informs the recommendation only. |

### The 10 operations (scoped down from 22)

| Op | Check | Stage | Tier |
| --- | --- | --- | --- |
| 1 | Document type is a tax invoice | A | T1 |
| 2 | Bill-to matches our entity | A | T1 |
| 3 | Vendor exists in master | A | T1 |
| 4 | Bank details match master | A | T1 |
| 5 | Hard duplicate (hash / vendor+inv#) | A | T1 |
| 6 | Near-duplicate (vendor + amount + date ±7d) | A | T3 |
| 7 | PO exists + is open + has remaining balance | B | T2 |
| 8 | 3-way match composite (line + qty + price + total within tolerance) | C | T3 |
| 9 | Arithmetic reconciliation (lines → subtotal → tax → total) | D | T3 |
| 10 | GSTIN format + HSN sanity | E | T3 |

### Stage execution order

```
┌───────────────────────────┐
│ A · Pre-flight gates (T1) │──fail──→ REJECT / FRAUD ALERT
└───────────────────────────┘
            │ pass
┌───────────────────────────┐
│ B · PO linkage (T2)       │──no PO──┐
└───────────────────────────┘         │
            │ pass                    │ (Stage C skipped if no PO)
┌───────────────────────────┐         │
│ C · Match engine (T3)     │         │
└───────────────────────────┘         │
            ├─────────────────────────┘
            ↓
┌───────────────────────────┐
│ D · Arithmetic (T3)       │  runs regardless
└───────────────────────────┘
            ↓
┌───────────────────────────┐
│ E · Tax validation (T3+4) │  runs regardless
└───────────────────────────┘
            ↓
┌───────────────────────────┐
│ F · Coding (T4)           │  runs regardless, advisory
└───────────────────────────┘
            ↓
       DOSSIER → Verdict
```

Stages D, E, F run regardless of what happened in B / C — they just produce different implications in the verdict.

## 8 · Bucket 4 — Verdict

**Input:** the Dossier. **Output:** **Decision Card** (what the AP analyst sees) + **Processed Invoice Record** (what they take forward), both written to the dashboard and the audit log.

### V1 · Decide the state

Five decision states, driven by the dossier:

| Trigger | Decision |
| --- | --- |
| Bank-detail mismatch (Op 4) | 🚨 **Fraud alert** — escalate, do not process further |
| Any other T1 blocker failed | **Reject** — with specific reason |
| T2 structural fail (no PO + can't be inferred, or PO closed / exceeded) | **Flag for review** — with "non-PO" / "PO issue" label |
| Any T3 validation failed beyond threshold | **Flag for review** — with specific label |
| T3 all passed, only T4 advisories, extraction confidence medium | **Approve pending review** — one-click confirm |
| T3 all passed, only T4 advisories, extraction confidence high | **Auto-approve** |

### V2 · Compute decision confidence

Composite 0–1 score:

- Minimum field confidence across mandatory fields (weakest-link)
- Fraction of T3 checks passed cleanly
- Consistency between extracted total and computed total

| Band | Meaning | Treatment |
| --- | --- | --- |
| ≥ 0.85 | High | Auto-approve permitted |
| 0.70 – 0.85 | Medium | Downgrade auto-approve → "approve pending review" |
| < 0.70 | Low | Flag regardless of other check outcomes |

### V3 · Compose the Decision Card

Shown to AP analyst first:

- Status badge (one of 5 states)
- Confidence score + band
- 2–3 sentence reasoning narrative (LLM over dossier)
- Failed-check list (collapsible, with severity + evidence)
- Routing label

### V4 · Assemble the Processed Invoice Record

Canonical, structured output the AP person actually uses downstream:

- Extracted invoice fields in canonical schema
- Suggested GL coding per line (account, cost center, capex / opex)
- Tax treatment (ITC eligible Y/N, TDS section + amount, reverse charge Y/N)
- Computed journal entry (Dr / Cr lines)
- Audit metadata (case ID, timestamp, pipeline version, config version, every check result + confidence)

### V5 · Export + persist

- Dashboard row (status, timestamp, vendor, amount, label — drill-down-able)
- Audit log entry (immutable; stamped record of the decision)
- Export formats: CSV / Excel row (ERP upload), JSON (API), PDF summary (archival)

### V6 · Human override hook

When the AP analyst overrides the verdict:

- Original verdict preserved (immutability)
- New verdict + who + when + reason captured in a separate `overrides` log
- Feeds a "N overrides in last 30 days, 60% on tolerance" dashboard panel (V2 training signal)

### Routing labels

| Label | Trigger |
| --- | --- |
| Reject — hard duplicate | Op 11a |
| Reject — vendor not in master | Op 3 |
| Reject — wrong entity | Op 2 |
| Reject — not a tax invoice | Op 1 |
| 🚨 Fraud alert — bank mismatch | Op 4 |
| Flag — non-PO invoice | Op 5 |
| Flag — PO issue (closed / exceeded) | Op 6 |
| Flag — tolerance breach | Ops 8, 9, 10 |
| Flag — near duplicate | Op 11b |
| Flag — arithmetic mismatch | Op 12 |
| Flag — tax validation failure | Ops 13–16, 19 |
| Flag — missing mandatory fields | Any op with low confidence on required field |
| Flag — low extraction confidence | V2 band = Low |

## 9 · Data Model

Schemas (conceptual — concrete types finalised in build).

### Invoice (extracted, canonical)

```
{
  case_id, ingested_at, source_channel, file_hash,
  vendor_name, vendor_gstin, vendor_pan, vendor_bank_acct, vendor_bank_ifsc,
  buyer_name, buyer_gstin, buyer_entity_id,
  invoice_number, invoice_date, due_date, payment_terms,
  po_reference,
  place_of_supply, currency,
  line_items: [
    { desc, hsn_sac, qty, uom, unit_price, discount, taxable_value,
      cgst_rate, cgst_amt, sgst_rate, sgst_amt, igst_rate, igst_amt }
  ],
  subtotal, total_tax, round_off, grand_total,
  reverse_charge_flag,
  per_field_confidence: { ... 0-1 per field ... }
}
```

### PO (dataset row)

```
{
  po_number, vendor_id, status (open/closed/cancelled),
  raised_date, approved_by,
  total_value, billed_to_date, remaining_balance,
  line_items: [{ item_code, desc, qty_ordered, unit_price, line_total }]
}
```

### Vendor master

```
{
  vendor_id, legal_name, aliases, gstin, pan, status,
  bank_acct, bank_ifsc, bank_last_updated,
  default_gl_account, default_cost_center,
  category (goods / services / mixed)
}
```

### Config (editable — see §10)

```
{
  config_version,
  tolerances: { price_pct, qty_pct, total_pct, total_absolute_cap_inr },
  doa_matrix: [{ amount_ceiling, approver_role }],
  confidence_thresholds: { auto_approve_min, flag_below },
  required_fields: [...],
  itc_blocked_hsns_or_categories: [...],
  tds_matrix: [{ vendor_category_or_account, section, rate, threshold }],
  retry_limits: { low_conf_resubmissions },
  op_toggles: { gstin_active_check, near_dup_check, coding_suggestion }
}
```

### Dossier (Processing → Verdict)

```
{
  case_id, config_version, run_started, run_ended,
  invoice_extracted: { ... },
  stages: {
    A: { status, ops: [{ op_id, result, severity, confidence, evidence, reason }] },
    B: { ... }, C: { ... }, D: { ... }, E: { ... }, F: { ... }
  },
  blocker_hit: bool,
  failures: [...], warnings: [...], advisories: [...], skipped: [...]
}
```

### Processed Invoice Record (Verdict output)

```
{
  case_id, decision_state, decision_confidence, decision_confidence_band,
  reasoning_narrative, routing_label, failed_checks: [...],
  canonical_invoice: { ... }, suggested_coding: [...], tax_treatment: {...},
  computed_journal_entry: [ { dr_cr, account, amount } ],
  audit: { pipeline_version, config_version, timestamps, every_check_result }
}
```

### Audit & override logs

Append-only. One audit entry per verdict. One override entry per override, referencing the verdict it overrides.

## 10 · Configuration & Customization

AP policies differ firm-to-firm. Making thresholds configurable is both a correctness requirement (so the system isn't lying about being general) and a strong demo moment — same invoice, different config → different verdict.

### T1 · Editable config values

Stored in `config.json`, exposed in a Settings page.

| Setting | Example default |
| --- | --- |
| Price tolerance (per line) | ±2% |
| Quantity tolerance | ±5% |
| Total tolerance | min(2%, ₹5,000 absolute) |
| DoA matrix | <₹25K: AP · ₹25K–₹1L: Mgr · ₹1L–₹10L: Head · ₹10L+: CFO |
| Confidence thresholds | Auto-approve ≥ 0.85 · Flag < 0.70 |
| Required fields list | invoice\_number, invoice\_date, grand\_total, vendor\_gstin |
| Blocked ITC HSNs / categories | Sec 17(5) blocked list |
| TDS matrix | 194C / J / I / H → rates + thresholds |
| Retry limit on low-confidence bounce-back | 3 |

### T2 · On / off toggles (slice)

A small set of ops that firms genuinely differ on:

- GSTIN active check (requires API)
- Near-duplicate check
- GL coding suggestion

### Config versioning

Every run stamps the `config_version` it ran under. Prior runs remain valid under the config they ran under; they are never silently re-evaluated.

### Settings page

Simple admin UI. Reads `config.json`, writes it back. No freeform rule authoring (that's a V2 differentiator, out of scope).

## 11 · Edge Cases

### Shortlist (8 candidates)

| # | Edge case | What it reveals |
| --- | --- | --- |
| 1 | Scanned image invoice | OCR branch; modality handling |
| 2 | Split PO (one PO → multiple invoices) | State management; remaining-balance arithmetic |
| 3 | Duplicate (hard + near) submission | Pattern detection; hash + fuzzy |
| 4 | Vendor name fuzzy match ("ABC Corp" vs "ABC Corporation Pvt Ltd") | Canonicalization logic |
| 5 | Missing critical field (no invoice #) | Human-in-loop handling; vendor query |
| 6 | Amount close but outside tolerance (3% vs policy 2%) | Tolerance evaluation + reasoning |
| 7 | Line items bundled vs itemised (totals reconcile, structures don't) | Match flexibility |
| 8 | Pro forma formatted exactly like an invoice | Document-type classification discipline |

### Recommended 3 to build (scoped down from 4 per council)

Picked so each is a different class of problem:

1. **Duplicate (hard + near together)** — detection patterns; hash + fuzzy
2. **Split PO** — state management; one PO fulfilled across multiple invoices with remaining-balance arithmetic
3. **Scanned image invoice** — OCR branch; doubles as the "cold demo" invoice in the live run

The other five stay named-but-not-built, discussed in the demo as "what we'd handle next." Vendor name fuzzy match in particular is a strong V2 candidate — call it out.

## 12 · UI Requirements

Four surfaces. Intuitive, not overbuilt. The demo is scored on whether the interviewer can see the process running and understand the outputs.

### Upload view

- Drag-drop one or more files
- Alternative: paste email body + choose attachment
- Shows ingest confirmation + new case ID

### Live run view (centrepiece of the demo)

Shows the pipeline executing in real time.

- Each stage as a node / row (Collection, Categorization, A, B, C, D, E, F, Verdict)
- Stage states: pending · running · passed · failed · skipped
- Extracted fields appear below Categorization as they stream in, with confidence chips
- Each op in Processing shows its result inline when it completes
- Final decision card appears below Verdict when the run ends

### Dashboard

- Table of all runs: timestamp, vendor, amount, decision, routing label, confidence
- Filter by status, vendor, date range, routing label
- Click any row → full drill-down (dossier + decision card in detail)
- A small side panel: counts by status, counts by label

### Decision card (AP-facing)

Compact view:

- Status badge
- Confidence band
- Reasoning narrative (2–3 sentences)
- Failed checks (expandable)
- Suggested coding
- Export buttons (CSV / JSON / PDF)
- Override button (opens override capture dialog)

### Settings page

- Editable fields for every T1 config value (§10)
- Toggles for T2 ops
- "Save and version" button — increments `config_version`

## 13 · Synthetic Data Plan

All data self-generated. No real company data used.

### Invoices (\~12 PDFs)

| # | Type | Purpose |
| --- | --- | --- |
| 1 | Clean digital, matches PO exactly | Happy path |
| 2 | Clean digital, within tolerance | Happy path with minor variance |
| 3 | Scanned image | OCR edge case + cold-demo invoice |
| 4 | Pro forma invoice | Bucket F — flag with reason |
| 5 | Invoice 1 of 3 on split PO | Split PO edge case |
| 6 | Invoice 2 of 3 on same split PO | Split PO continuation |
| 7 | Hard duplicate of #1 | Duplicate hard |
| 8 | Near-duplicate of #1 (new inv# same amount same vendor) | Duplicate near |
| 9 | Missing invoice number | Missing field — Bucket G |
| 10 | Price outside tolerance | Tolerance breach |

### PO dataset

\~20 POs across 5 vendors. Mixed statuses: open, closed, partially billed. One split PO (for invoices 6 + 7).

### Vendor master

5–7 vendors. Each with: legal name + 2–3 aliases, GSTIN, PAN, bank details, status, default GL account, default cost center, category.

### Chart of accounts

\~15 GL accounts across common expense + asset categories.

### Config

`config_default.json` with the defaults listed in §10.

## 14 · Success Criteria

The build is demo-ready when:

1. Process executes end-to-end on the happy path with no manual intervention.
2. All 3 chosen edge cases produce the correct distinct decisions.
3. Dashboard displays run history and supports drilldown.
4. Decision card reads cleanly to a non-technical viewer — jargon translated.
5. Reasoning trail is complete and references the evidence it used.
6. 5-minute video script is rehearsed; video runs within 5 min and leads with the problem before the mechanics.
7. Settings page demonstrably flips a verdict on the same invoice live — this is the demo spine.
8. Audit log is immutable; override hook captures changes without rewriting original verdicts.
9. End-to-end demo runs deterministically on a cold machine with pre-staged fixtures — rehearsed ≥ 5× before live interview.
10. Interview answer sheet drafted (decision log + cut log + failure modes) and rehearsed.

A submission that handles 3 edge cases well beats one that half-handles 10. Judgement is shown by what we chose not to build — that becomes a talking point, not a hidden omission.

## 14b · Demo Readiness

Per council feedback, the deliverable isn't the system alone — it's the system plus the 5-minute video plus the follow-up live-demo defense. Four artifacts sit alongside the code.

### 5-minute video script

Written Fri evening, before any code. Shot list + voiceover + which invoice at which second. The build serves the script, not the other way around.

- **0:00–0:30** — the AP analyst's day today (the pain, not the mechanics)
- **0:30–1:00** — upload one invoice, show the Live Run view
- **1:00–3:00** — walk through the Decision Card for a happy path + a flagged case
- **3:00–4:00** — flip a config value in Settings, re-run the same invoice, show the verdict change live (this is the spine)
- **4:00–5:00** — summary of what we didn't build and why

Lead with the invoice and the headache. Earn the right to show the machinery.

### Jargon translation glossary

Every piece of finance / tax jargon has a 1-line plain-English translation, used consistently in the video, the Decision Card wording, and the demo narration.

| Jargon | Plain English |
| --- | --- |
| GSTIN | vendor's tax ID |
| HSN code | product category code |
| 3-way match | we check three things — what was ordered, what was received, what we're billed |
| PO | purchase order — the pre-approved commitment to buy |
| Split PO | one order billed in parts across multiple invoices |
| ITC | the GST credit we can claim back from the government |
| Reverse charge | a tax rule where the buyer (not vendor) pays GST |
| TDS | tax deducted at source — buyer withholds tax on certain payments |
| Dossier | the full evidence file of every check we ran |
| Immutable audit log | nothing can be edited after the fact |
| Auto-approve vs Approve pending review | auto = ready to post; pending = looks right but needs a 1-click human confirm |

### Interview answer sheet

Prepared Mon morning alongside the final build. Three logs, printed and reviewed before the live interview.

- **Decision log** — every architectural choice + the reasoning (why 4 buckets, why tier gating, why these 10 ops, why the Settings page is the demo spine)
- **Cut log** — everything we chose NOT to build and the single-line reason for each (TDS, ITC, reverse charge, GL coding depth, 4 unbuilt edge cases, Vendor Risk Score)
- **Failure-mode log** — where this breaks at 500 invoices/day, what fails first, what we'd change

Plus prepared talking points for likely questions: "why this tolerance?", "what did you drop and why?", "where would this break?", "how would you add X?"

### Live-demo determinism

The follow-up live demo is the real exam. It happens in a room with hostile questions and possibly bad WiFi. Build for that.

- SQLite backend with pre-staged fixtures (no live DB spin-up on demo day)
- "Reset to clean state" button for the live demo
- Offline-first — no external API dependencies at demo time (GSTIN "active" check mocked against a static list of known-active IDs; demo narrates "in production this calls the live GSTN portal")
- Prepared invoice pack stored locally, not downloaded live
- Rehearse end-to-end on a cold machine ≥ 5× before the interview

## 15 · Non-goals

Named explicitly so the demo has a clean boundary.

| Not built | Why |
| --- | --- |
| Journal posting to ERP | Downstream of the decision; would require ERP integration |
| Payment scheduling / execution | Treasury concern, out of problem statement |
| TDS section + rate detection | Scoped out of Processing per council; demo mentions as scoped-out |
| ITC eligibility (Sec 17(5)) classification | Scoped out of Processing per council; demo mentions as scoped-out |
| Reverse charge applicability | Scoped out of Processing per council |
| GL coding suggestion (full depth) | Scoped out per council; vendor-master default inheritance only, if at all |
| Vendor name fuzzy match (4th edge case) | Dropped per council; mention as scoped-out and strong V2 |
| TDS deposit + 26Q filing | Tax compliance, separate workflow |
| GSTR-2B reconciliation | Monthly process, separate workflow |
| Vendor statement reconciliation | Monthly process, separate workflow |
| Vendor onboarding | That is Problem Statement 2 |
| Approval workflow execution | We recommend the approver; routing + sign-off collection is a separate system |
| Vendor query drafting / sending | Human stays in loop for all vendor communication |
| Vendor-behavior pattern analytics | Requires longitudinal data we don't have in a short build |
| Vendor Risk Score (compounding anomaly detection) | V2 — great product direction, out of 3-day scope |
| Freeform rule authoring (T3 customization) | Natural V2; needs a safe rule engine |

Named in the demo as "deliberately scoped out" — shows we know they exist.

## 16 · Compressed Build Plan — Fri 6 Nov evening → Mon 9 Nov EoD

| Window (IST) | Deliverable |
| --- | --- |
| **Fri 6 Nov evening** | Finalise PRD · write 5-min video script (scene-by-scene) · stack scaffold (FastAPI + Next.js + SQLite + Python OCR) · generate synthetic data (10 invoices + PO + vendor master + chart of accounts) · `config_default.json` |
| **Sat 7 Nov AM** | Collection (manual upload only) · Categorization (3 buckets: Structured, Text-PDF, Image+OCR) · Extraction with per-field confidence · Dossier schema |
| **Sat 7 Nov PM** | Processing — all 10 ops across 6 stages with tier gating · tested end-to-end on happy-path invoice · Dossier output stable |
| **Sun 8 Nov AM** | Verdict (V1–V6) · Decision Card wording (plain English, jargon translated) · Upload view + Live Run view wired to backend |
| **Sun 8 Nov PM** | Dashboard · Settings page (demo spine — editable tolerances + 3 toggles) · edge case 1 (Duplicate) + edge case 2 (Split PO) |
| **Mon 9 Nov AM** | Edge case 3 (Scanned) · decision-card polish · audit log + override hook · draft interview answer sheet · jargon glossary |
| **Mon 9 Nov PM** | Rehearse end-to-end on cold machine ×5 · record 5-min video · submit by EoD |

**Buffer strategy:** if Sat PM slips, Processing is cut to 8 ops (drop near-duplicate and HSN sanity); if Sun PM slips, edge case 2 (Split PO) is dropped. A clean 2 edge cases beats a broken 3. Non-negotiable: Live Run view + Decision Card + Settings-flips-verdict demo moment must all be working by end of Mon AM.

## 17 · Open Questions

Decisions still outstanding before build starts.

1. **Edge case lock** — confirm the 4 picked (Split PO, Duplicate, Scanned, Fuzzy vendor match) or swap any.
2. **Procurement system representation** — PO dataset as a plain CSV (simpler, cleaner demo) vs a tiny admin UI to manage POs alongside (more impressive, costs \~½ day).
3. **GSTIN active check (Op 14)** — mock with a static list of "known-active" GSTINs, or wire the live GSTN API (adds a dependency, risks flakiness at demo time).
4. **Build tool** — Claude Code only (one environment, cleaner), or Claude Code for backend + Lovable / v0 for UI first pass (faster visual polish, more moving parts).
5. **Deploy target** — Vercel (frontend) + Railway (backend) separately, or Replit for a single-URL demo (fewer failure points for live demo, slightly less "production" feel).
6. **Decision-card tone** — terse ("Tolerance breach, +3%") or narrative ("This invoice is above the 2% tolerance by 3%, totalling ₹3,200 over the matched PO value. Recommended: route to manager for override.") — recommend narrative for the demo.
