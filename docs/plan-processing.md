# Plan — Processing (PRD §7)

Zamp Invoice AP · 2026-11-07 · status: **awaiting approval**

Scope: implement the 10 ops across stages A–F with tier gating, wire Processing into the case run, and verify all 10 fixtures fire the right failures. Final Verdict (V1–V6) is the next task.

---

## 1. Gaps between the PRD and our data

| # | Gap | Proposal |
|---|---|---|
| 1 | **Op 8 can't be a true 3-way match.** 3-way = ordered (PO) vs received (goods receipt, GRN) vs billed. We have no goods-receipt data. | **Recommended:** name it honestly as "PO match" and have its evidence say *"2-way (no goods-receipt data in this build)"*. Add a line to the cut log. Alternative: generate GRN fixtures (~½ day). |
| 2 | **Stage F (coding) has no op** among the 10. | Add one advisory step **F1**, numbered so it isn't mistaken for an 11th op. It copies the vendor-master default GL account and cost center, behind the `coding_suggestion` toggle. PRD §15 allows exactly this much. The Decision Card and journal entry need it. |
| 3 | **No op checks for missing required fields**, which is #9's expected flag. | Processing records `missing_required_fields`: any field in `config.required_fields` that came back null. The decision hint, and later Verdict, flags on it. |
| 4 | **The manifest's buckets F/G are outcomes**, not how the text was read. | Keep `routing_bucket` as the extraction path (B/C). Check F as "Op 1 failed" and G as "required fields missing". |
| 5 | **The "decision hint" is the first half of Verdict's V1 step.** | `processing.decision_hint(dossier)` returns `fraud_alert` / `reject` / `flag` / `approve`. Verdict splits approve into auto vs pending (confidence + OCR policy) next task. |

---

## 2. Op contract

```python
class OpResult(BaseModel):
    op_id: str            # "1".."10", "F1"
    name: str             # "Vendor exists in master"
    stage: str            # "A".."F"
    tier: str             # "T1".."T4"
    result: Literal["pass", "warn", "fail", "skipped", "not_evaluated"]
    severity: Literal["critical", "high", "medium", "low", "info", "none"]
    confidence: float     # min confidence of the extracted fields the op relied on
    evidence: dict        # the exact values compared
    reason: str           # plain English, glossary wording (e.g. "vendor's tax ID")

def op_x(dossier: Dossier, ctx: Context) -> OpResult
# Context = config, entity, vendors, POs, prior cases
#           (+ resolved vendor_id / po_number filled in as ops run)
```

**Severity mapping**

| Outcome | Severity |
|---|---|
| Op 4 fails (bank details) | `critical` |
| Any other T1 failure | `high` |
| T2 or T3 failure | `medium` |
| Warning | `low` |
| T4 advisory | `info` |

`warn` means the op didn't fail but the analyst should know something. Example: an invoice with no bank details printed, where the master record will be used for payment.

**Dossier additions**

- `stages` filled per stage: `{status, ops: [OpResult]}`
- `resolved`: `{entity_id, vendor_id, po_number}`
- `missing_required_fields`
- `failures` / `warnings` / `advisories` / `skipped`: lists of op IDs
- `blocker_hit`: true when any T1 op fails
- Canonical invoice's `buyer_entity_id` filled when Op 2 passes

---

## 3. Gating

```
for each op in order 1..10, F1:
    blocker already hit       -> skipped        reason: "skipped - Op N blocked the run"
    depends on a failed T2    -> not_evaluated  (only Op 8 depends on Op 7)
    toggled off in config     -> skipped        reason: "turned off in Settings"
    otherwise                 -> run
```

- A T1 failure stops everything after it, including the rest of stage A (PRD §7).
- Stages D, E and F always run unless a T1 blocker was hit.

---

## 4. The ops

| Op | Stage / tier | Pass rule | Notes |
|---|---|---|---|
| **1** Doc type | A / T1 | `document_type == tax_invoice` | Credit/debit notes fail with "separate flow, not built". |
| **2** Bill-to | A / T1 | `buyer_gstin == entity.gstin` | If GSTIN missing, fall back to legal name / aliases. |
| **3** Vendor in master | A / T1 | Exact GSTIN match (else exact alias match); vendor status active | Fuzzy name matching stays out (cut edge case 4). Sets `resolved.vendor_id`. |
| **4** Bank details | A / T1 | Account + IFSC equal master (spaces/dashes ignored) | Fail → **fraud alert**. Missing from invoice → `warn`. |
| **5** Hard duplicate | A / T1 | No **earlier** case with same file hash, or same vendor + invoice number | Invoice number missing → `warn` ("only the file-hash check was possible"). |
| **6** Near duplicate | A / T3 | No earlier case with same vendor + grand total, dated within ±7 days, different invoice number | Toggle: `near_dup_check`. |
| **7** PO linkage | B / T2 | PO exists, belongs to this vendor, `open`, and invoice subtotal ≤ effective remaining + total tolerance | Effective remaining = master `remaining_balance` − subtotals of **earlier non-blocked cases** on the same PO. |
| **8** PO match | C / T3 | Lines matched by HSN + description similarity. Per line: price within ±`price_pct`; quantity billed so far ≤ ordered × (1 + `qty_pct`). Total variance ≤ min(`total_pct`%, ₹cap). | Billing part of an order (split PO) is not a quantity variance. Invoice line with no PO line → fail. |
| **9** Arithmetic | D / T3 | Line: qty × price = taxable; taxable × rate = tax. Lines → subtotal; tax lines → total tax (if printed); subtotal + tax + round-off = grand total. ±₹0.50. | Safety net for the OCR "9 read as 6" case. |
| **10** GSTIN + HSN | E / T3 | Both GSTINs: format, checksum, state code, embedded PAN. HSN/SAC shape valid. Line rate is a valid slab and matches the reference rate where known. CGST+SGST vs IGST matches intra vs inter-state. | "Active" check against a mocked list: vendor-master GSTINs + ours (PRD §14b), behind `gstin_active_check`. Rate reference: new `data/hsn_gst_rates.json` written by the generator; PDFs unchanged. |
| **F1** Coding | F / T4 | Advisory: vendor default GL + cost center; capex/opex from chart of accounts | Toggle: `coding_suggestion`. |

**Points to note**

- **"Earlier"** = cases with a lower ID. Re-running #1 after #7 exists won't make #1 a duplicate of #7.
- **Earlier cases reserve PO balance.** Next task can refine this to count only approved / pending invoices.
- **Over-billing allowance:** exceeding the remaining PO balance is allowed up to the total tolerance. Otherwise #2 (+₹1,260) and #10 (+₹1,680) would fail Op 7 when only their prices should be judged.
- **Scaling note:** duplicate checks scan earlier dossiers — fine for a demo. At 500 invoices/day you'd index vendor + invoice number (failure-mode talking point).

---

## 5. Wiring

- **Runner:** after Categorization, `runner.run_case` calls `processing.run(dossier, ctx)` and stores the dossier. Case status → `processed`.
- **OCR policy:** extraction path is already recorded in `categorization.text_source`, so Verdict has what it needs.

---

## 6. Testing

**Offline pytest** — all 10 fixtures, in order, through the real API. Gemini is replaced by canned responses from the manifest (`#4 → proforma_invoice`). Asserts each fixture's decision hint and failing ops:

| # | Expected hint | Expected failed ops |
|---|---|---|
| 1, 2, 3, 5, 6 | approve | none (#2 shows +1.5% variance; #6 leaves ₹6.5L on the PO) |
| 4 | reject | 1 (ops 2–10 and F1 skipped) |
| 7 | reject | 5 (everything after skipped) |
| 8 | flag | 6, plus 7 (PO-A used up by #1) → Op 8 not evaluated |
| 9 | flag | missing required: `invoice_number` (Op 5 → warn) |
| 10 | flag | 8 (line 1 +2.8%) |

**Targeted tests** for paths no fixture exercises:

- bank mismatch → fraud alert
- vendor not in master
- wrong bill-to entity
- closed PO
- near-duplicate toggle off → skipped
- GSTIN with a bad check digit

**Live run** — `run_case.py` gets `--reset` and accepts several files:

- `--reset` wipes the runtime DB and uploads but keeps the Gemini cache.
- Ingests in order; prints one row per invoice: bucket · expected vs actual hint · expected vs actual failing ops · ✓/✗.
- 8 new Gemini calls, made once (#1 and #3 already cached).

**Commands**

```bash
cd backend && ../.venv/Scripts/python.exe scripts/generate_fixtures.py     # adds hsn_gst_rates.json
cd backend && ../.venv/Scripts/python.exe -m pytest -q
cd backend && ../.venv/Scripts/python.exe scripts/run_case.py --reset data/invoices/*.pdf
```

---

## 7. Decisions needed

The two that matter most:

1. **Op 8 is 2-way and labelled honestly** (recommended), or build goods-receipt data.
2. **Earlier non-blocked cases reserve PO balance** for now.

Approving also accepts these defaults:

- F1 coding as an advisory step
- `missing_required_fields` driving #9
- `hsn_gst_rates.json`
- intra/inter tax check inside Op 10
- over-billing allowance up to total tolerance
