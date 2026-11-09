# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- **Primary: AP analyst** at a mid-size Indian company, processing 100–300 vendor invoices a week. Not technical. Needs fast triage of clean invoices, clear reasons when something is flagged, a structured record to post to the ERP, and an audit trail the finance controller trusts.
- **Secondary: finance controller / CFO** — reads exception volume and control effectiveness, never touches invoices. (Dashboard needs; not served by the first surface.)
- **Evaluator: the Zamp hiring team** (ASA PS-1 case study). Grades whether a viewer can see the process run and understand the output, and the product judgement behind what was and wasn't built.

## Product Purpose

Takes a vendor invoice PDF and returns a reasoned decision (auto-approve, approve pending review, flag, reject, fraud alert) with every intermediate check visible, plus a canonical record and journal entry the analyst can hand to the ERP. The analyst stays in the loop: the system helps, it doesn't replace them. Success = an analyst reads the decision card and knows exactly what to do next.

## Positioning

Decisions are made by fixed, inspectable rules over an evidence file (the dossier); the language model only reads the invoice and words the explanation, and can never change a decision. Thresholds are firm-configurable, and changing one visibly changes the verdict on the same invoice.

## Operating Context

- Invoices arrive as PDFs (digital or scanned); upload is the only channel built.
- The analyst works in an office, at a desk, in daylight; the demo is screen-recorded and later shared live in an interview.
- Must run offline on one machine: FastAPI backend on :8000, Next.js UI on :3000, SQLite, pre-cached model outputs. No live external API calls at demo time.

## Capabilities and Constraints

- Pipeline: Collection → Categorization (text layer or OCR, then extraction) → Processing (10 checks + advisory GL coding) → Verdict.
- Built: 10 synthetic fixture invoices with an answer key; price-tolerance setting editable in the UI; append-only, hash-chained audit log; overrides and exports exist in the backend (not surfaced in the first UI).
- Scoped out: TDS, ITC, reverse-charge applicability, 3-way match (no goods-receipt data; Op 8 is 2-way), fuzzy vendor-name match, ERP posting, payments.
- Terminology: plain English in the UI — "vendor tax ID" not GSTIN, "product code" not HSN, "purchase order" not PO in prose, "approver role" not DoA.

## Brand Commitments

- Internal tool. No marketing language, no hero, no "AI-powered" framing.
- Look pinned by the owner: dashboard/workbench in the register of Linear, Notion, Stripe. Light mode, system fonts, indigo accent (confirmed 2026-11-09).

## Evidence on Hand

- Fixtures: `backend/data/invoices/*.pdf` + `manifest.json` (answer key). All data is synthetic — no real company data, customers, or metrics may be invented.

## Product Principles

1. Decide in code, explain in plain English.
2. Every decision shows its evidence; nothing is a black box.
3. The human stays in the loop for anything uncertain, scanned, or risky.
4. Scoping is a feature: say what isn't built rather than fake it.
5. Deterministic and offline for the demo.

## Accessibility & Inclusion

WCAG AA contrast; status is never carried by colour alone (every badge has text). (Inferred from the brief; no further requirement stated.)
