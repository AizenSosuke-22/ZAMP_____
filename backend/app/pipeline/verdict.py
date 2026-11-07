"""Bucket 4 (PRD §8): Dossier -> Decision Card + Processed Invoice Record.

V1 state, V2 confidence, V3 card, V4 record live here; V5 persistence and V6 overrides in runner.py.
See docs/plan-verdict.md.
"""
import json
from datetime import datetime, timezone

from app import settings
from app.models import Dossier
from app.pipeline import narrative, processing
from app.pipeline.processing import MONEY_TOL
from app.pipeline.processing import _inr as inr

STATES = ("auto_approve", "approve_pending_review", "flag", "reject", "fraud_alert")
APPROVE_STATES = ("auto_approve", "approve_pending_review")
BADGE = {"auto_approve": "Auto-approved", "approve_pending_review": "Approve pending review",
         "flag": "Flagged for review", "reject": "Rejected", "fraud_alert": "🚨 Fraud alert"}
MEANING = {
    "auto_approve": "ready to post; no action needed",
    "approve_pending_review": "looks right, but needs a one-click confirmation from a person before it is posted",
    "flag": "needs a person to review it before anything is paid",
    "reject": "should not be paid",
    "fraud_alert": "must not be paid until the vendor's bank details are confirmed",
}
DATA_CONFIDENCE = {"High": "we're confident we read the invoice correctly",
                   "Medium": "we read the invoice, but not every detail with full confidence",
                   "Low": "some key details couldn't be read reliably"}
FIELD_NAMES = {"invoice_number": "invoice number", "invoice_date": "invoice date",
               "grand_total": "invoice total", "vendor_gstin": "vendor's tax ID"}


def apply_review_policies(decision: str, dossier: Dossier, config: dict) -> tuple[str, str | None]:
    """Control policies that cap how far a decision may go without a human (PRD §10 config).

    Only ever downgrades auto_approve -> approve_pending_review; never touches flag / reject /
    fraud_alert, and never upgrades anything. Returns (decision, plain-English reason or None).
    """
    if (decision == "auto_approve"
            and config.get("review_policies", {}).get("ocr_always_pending_review")
            and dossier.categorization and dossier.categorization.text_source == "ocr"):
        return ("approve_pending_review",
                "This invoice was read from a scan, so our policy is that a person gives it a "
                "one-click check before it is posted - even though every check passed.")
    return decision, None


# ---------------------------------------------------------- V2 confidence --
def confidence(d: Dossier, config: dict) -> dict:
    """min(fields, checks, totals) - only as strong as the weakest of the three."""
    inv = d.invoice_extracted
    fields = min(inv.per_field_confidence.get(f, 0.0) if getattr(inv, f) not in (None, "") else 0.0
                 for f in config["required_fields"])
    t3 = [o for s in d.stages.values() for o in s.ops if o.tier == "T3" and o.result not in ("skipped", "not_evaluated")]
    checks = sum(o.result == "pass" for o in t3) / len(t3) if t3 else 1.0
    taxable = [li.taxable_value for li in inv.line_items]
    if inv.grand_total is None or not taxable or None in taxable:
        totals = 0.0
    else:  # our own total, from the line items only
        gst = sum((li.cgst_amt or 0) + (li.sgst_amt or 0) + (li.igst_amt or 0) for li in inv.line_items)
        totals = 1.0 if abs(sum(taxable) + gst + (inv.round_off or 0) - inv.grand_total) <= MONEY_TOL else 0.0
    score = round(min(fields, checks, totals), 3)
    th = config["confidence_thresholds"]
    band = "High" if score >= th["auto_approve_min"] else "Medium" if score >= th["flag_below"] else "Low"
    return {"score": score, "band": band,
            "components": {"fields": round(fields, 3), "checks": round(checks, 3), "totals": totals}}


# ------------------------------------------------------------ V1 state -----
def decide_state(d: Dossier, band: str, config: dict) -> tuple[str, str | None]:
    """-> (state, policy note). Rules 1-3 are processing.decision_hint(); Low only ever pushes an approval down."""
    hint = processing.decision_hint(d)
    if hint != "approve":
        return hint, None
    state = {"Low": "flag", "Medium": "approve_pending_review", "High": "auto_approve"}[band]
    return apply_review_policies(state, d, config)


# --------------------------------------------------------- V3 card ---------
def _no_po(d):
    return not d.invoice_extracted.po_reference


# (label, applies(dossier, band), op whose reason explains it). Order = priority when several apply.
LABELS = [
    ("🚨 Fraud alert — bank mismatch", lambda d, b: "4" in d.failures, "4"),
    ("Reject — not a tax invoice", lambda d, b: "1" in d.failures, "1"),
    ("Reject — wrong entity", lambda d, b: "2" in d.failures, "2"),
    ("Reject — vendor not in master", lambda d, b: "3" in d.failures, "3"),
    ("Reject — hard duplicate", lambda d, b: "5" in d.failures, "5"),
    ("Flag — near duplicate", lambda d, b: "6" in d.failures, "6"),
    ("Flag — missing mandatory fields", lambda d, b: bool(d.missing_required_fields), None),
    ("Flag — non-PO invoice", lambda d, b: "7" in d.failures and _no_po(d), "7"),
    ("Flag — PO issue (closed / exceeded)", lambda d, b: "7" in d.failures and not _no_po(d), "7"),
    ("Flag — tolerance breach", lambda d, b: "8" in d.failures, "8"),
    ("Flag — arithmetic mismatch", lambda d, b: "9" in d.failures, "9"),
    ("Flag — tax validation failure", lambda d, b: "10" in d.failures, "10"),
    # Only when Low is *why* it's flagged (V1 rule 4). Failed checks also lower the score, but they have their own labels.
    ("Flag — low extraction confidence", lambda d, b: b == "Low" and processing.decision_hint(d) == "approve", None),
]


def _missing_names(d):
    return " and ".join(FIELD_NAMES.get(f, f.replace("_", " ")) for f in d.missing_required_fields)


def _next_action(state: str, label: str | None, d: Dossier) -> str:
    if state == "auto_approve":
        return "No action needed; it is ready to post."
    if state == "approve_pending_review":
        return "Give it a quick look and confirm with one click."
    if label == "Reject — hard duplicate":
        return f"Close it as a duplicate of {processing._op(d, '5').evidence['duplicate_of']}; it has already been received."
    if label == "Flag — near duplicate":
        return (f"Compare it with {processing._op(d, '6').evidence['similar_to']} and confirm with the vendor "
                "whether it is a separate bill before paying.")
    if label == "Flag — missing mandatory fields":
        return f"Ask the vendor for a corrected invoice that shows the {_missing_names(d)}."
    return {
        "🚨 Fraud alert — bank mismatch": "Don't pay; call the vendor on the phone number we already have on file "
                                         "to confirm their bank details.",
        "Reject — not a tax invoice": "Ask the vendor for the final tax invoice.",
        "Reject — wrong entity": "Return it to the vendor to re-issue it to our company.",
        "Reject — vendor not in master": "Check whether this vendor should be onboarded before anything is paid.",
        "Flag — non-PO invoice": "Find the purchase order, or get approval for a purchase made without one.",
        "Flag — PO issue (closed / exceeded)": "Check with the buyer whether the purchase order should be extended "
                                               "before paying.",
        "Flag — tolerance breach": "Ask the vendor to correct the price, or approve the difference if it was agreed "
                                   "in advance.",
        "Flag — arithmetic mismatch": "Ask the vendor for a corrected invoice.",
        "Flag — tax validation failure": "Ask the vendor to correct the tax details on the invoice.",
        "Flag — low extraction confidence": "Check the extracted values against the original document before approving.",
    }[label]


def _approver(total, config):
    """DoA matrix (PRD §10): who should approve this amount. Recommended, not executed."""
    if total is None:
        return None
    return next(r["approver_role"] for r in config["doa_matrix"]
                if r["amount_ceiling"] is None or total < r["amount_ceiling"])


def _issue(d, label, op_id):
    if op_id:
        o = processing._op(d, op_id)
        return {"check": o.name, "what_we_found": o.reason}
    if label == "Flag — missing mandatory fields":
        return {"check": "Required details are present", "what_we_found": f"The invoice doesn't show the {_missing_names(d)}."}
    return {"check": "We could read the invoice reliably",
            "what_we_found": "Some key details couldn't be read reliably from the document."}


# ------------------------------------------------------- V4 record ---------
def _journal(inv, coding, state, accounts):
    """Basic entry from invoice totals + GST breakdown; no TDS / ITC adjustments."""
    if state not in APPROVE_STATES and state != "flag":
        return {"status": "not prepared — invoice " + ("rejected" if state == "reject" else "held for fraud review"),
                "balanced": None, "lines": []}
    lines = []

    def add(dr_cr, code, amount, cost_center=None):
        if amount:
            lines.append({"dr_cr": dr_cr, "account": code, "cost_center": cost_center, "amount": round(amount, 2),
                          "account_name": accounts[code]["name"] if code in accounts else "to be coded by the analyst"})

    grouped = {}
    for n, li in enumerate(inv.line_items):
        c = coding[n] if n < len(coding) else {}
        key = (c.get("gl_account"), c.get("cost_center"))
        grouped[key] = grouped.get(key, 0) + (li.taxable_value or 0)
    for (gl, cc), amount in grouped.items():
        add("Dr", gl, amount, cc)
    for code, field in (("1310", "cgst_amt"), ("1320", "sgst_amt"), ("1330", "igst_amt")):
        add("Dr", code, sum(getattr(li, field) or 0 for li in inv.line_items))
    ro = inv.round_off or 0
    add("Dr" if ro > 0 else "Cr", "5990", abs(ro))
    add("Cr", "2100", inv.grand_total or 0)
    dr = round(sum(x["amount"] for x in lines if x["dr_cr"] == "Dr"), 2)
    cr = round(sum(x["amount"] for x in lines if x["dr_cr"] == "Cr"), 2)
    return {"status": "ready to post" if state in APPROVE_STATES else "draft — post only after review",
            "balanced": abs(dr - cr) <= 0.005, "total_debit": dr, "total_credit": cr, "lines": lines,
            "note": "Input GST is debited assuming the GST credit is claimable; GST credit (ITC) eligibility "
                    "is not evaluated in this build."}


def decide(d: Dossier, config: dict) -> tuple[dict, dict]:
    """Dossier -> (Decision Card, Processed Invoice Record)."""
    inv, cat = d.invoice_extracted, d.categorization
    conf = confidence(d, config)
    state, policy_note = decide_state(d, conf["band"], config)
    labels = [(lb, op) for lb, applies, op in LABELS if applies(d, conf["band"])] if state not in APPROVE_STATES else []
    label = labels[0][0] if labels else None
    next_action = _next_action(state, label, d)
    approver = _approver(inv.grand_total, config)
    ops = [o for s in d.stages.values() for o in s.ops]
    policy_notes = [policy_note] if policy_note else []

    facts = {
        "decision": state, "decision_meaning": MEANING[state],
        "vendor": inv.vendor_name, "invoice_number": inv.invoice_number,
        "invoice_total": inr(inv.grand_total) if inv.grand_total is not None else None,
        "purchase_order": inv.po_reference,
        "issues": [_issue(d, lb, op) for lb, op in labels],
        "notes": policy_notes + [o.reason for o in ops if o.result == "warn"],
        "data_confidence": DATA_CONFIDENCE[conf["band"]],
        "next_action": next_action,
        "approver": approver if state in ("approve_pending_review", "flag") else None,
    }
    text, source, rejected = narrative.write(facts)
    failed = [{"op_id": o.op_id, "name": o.name, "result": o.result, "severity": o.severity,
               "reason": o.reason, "evidence": o.evidence} for o in ops if o.result in ("fail", "warn")]

    card = {"case_id": d.case_id, "state": state, "status_badge": BADGE[state], "confidence": conf,
            "routing_label": label, "secondary_labels": [lb for lb, _ in labels[1:]],
            "narrative": text, "narrative_source": source, "narrative_rejected": rejected,
            "next_action": next_action, "approver_role": approver, "policy_notes": policy_notes,
            "failed_checks": failed}

    accounts = {a["code"]: a for a in json.loads((settings.DATA_DIR / "chart_of_accounts.json").read_text(encoding="utf-8"))}
    f1 = processing._op(d, "F1")
    coding = f1.evidence["lines"] if f1 and f1.result == "pass" else []
    op10 = processing._op(d, "10")
    gst = {k: round(sum(getattr(li, f"{k}_amt") or 0 for li in inv.line_items), 2) for k in ("cgst", "sgst", "igst")}
    record = {
        "case_id": d.case_id, "decision_state": state,
        "decision_confidence": conf["score"], "decision_confidence_band": conf["band"],
        "reasoning_narrative": text, "routing_label": label, "failed_checks": failed,
        "canonical_invoice": inv.model_dump(mode="json"),
        "suggested_coding": coding,
        "tax_treatment": {
            "supply_type": op10.evidence.get("supply") if op10 else None,
            "gst": {**gst, "total": round(sum(gst.values()), 2)},
            "reverse_charge": inv.reverse_charge_flag,
            "itc_eligibility": "not evaluated — scoped out",
            "tds": "not evaluated — scoped out",
        },
        "computed_journal_entry": _journal(inv, coding, state, accounts),
        "audit": {
            "pipeline_version": settings.PIPELINE_VERSION, "config_version": d.config_version,
            "extraction_model": cat.model if cat else None, "extraction_prompt_version": cat.prompt_version if cat else None,
            "narrative_model": settings.GEMINI_MODEL, "narrative_prompt_version": narrative.NARRATIVE_PROMPT_VERSION,
            "narrative_source": source, "text_source": cat.text_source if cat else None,
            "ingested_at": inv.ingested_at, "run_started": d.run_started.isoformat(),
            "run_ended": d.run_ended.isoformat() if d.run_ended else None,
            "decided_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "checks": [{"op_id": o.op_id, "name": o.name, "result": o.result, "severity": o.severity,
                        "confidence": o.confidence} for o in ops],
        },
    }
    return card, record
