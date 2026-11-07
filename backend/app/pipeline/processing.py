"""Bucket 3 (PRD §7): invoice JSON -> Dossier (10 ops, stages A-F, tier gating).

Ops run in order 1..10, then F1 (coding advisory; numbered so it isn't read as an 11th op).
Gating:
  - a T1 failure stops the run: every later op is `skipped`
  - Op 8 depends on Op 7 (T2): if Op 7 fails, Op 8 is `not_evaluated`
  - an op turned off in config (`op_toggles`) is `skipped`
"Earlier cases" = lower case ID, already processed, not stopped by a T1 failure. They are what
duplicates are checked against, and the ones linked to a PO (Op 7 passed) reserve its balance.
Reason strings are plain English for the AP analyst (PRD §14b glossary: GSTIN = "tax ID").
"""
import difflib
import json
import re
from dataclasses import dataclass
from datetime import date

from app import db, settings
from app.models import Dossier, Invoice, OpResult, Stage

MONEY_TOL = 0.50                # Rs allowed for rounding in arithmetic checks
NEAR_DUP_DAYS = 7
MIN_DESC_SIMILARITY = 0.6       # invoice line vs PO line description
# 12% and 28% were folded into 5/18/40 in Sept 2025; kept so older invoices aren't false-flagged.
GST_SLABS = {0, 0.25, 3, 5, 12, 18, 28, 40}
GSTIN_RE = re.compile(r"(\d{2})([A-Z]{5}\d{4}[A-Z])[1-9A-Z]Z[0-9A-Z]")
HSN_RE = re.compile(r"\d{4}(\d{2}){0,2}")
B36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
TWO_WAY = "2-way (no goods-receipt data in this build)"


@dataclass
class Context:
    config: dict
    entity: dict
    vendors: list[dict]
    pos: dict[str, dict]
    accounts: dict[str, dict]
    hsn_rates: dict[str, float]
    prior: list[Dossier]


def load_context(config: dict, case_id: str) -> Context:
    def load(name):
        return json.loads((settings.DATA_DIR / name).read_text(encoding="utf-8"))
    with db.connect() as conn:
        rows = conn.execute("SELECT dossier_json FROM dossiers WHERE case_id < ? ORDER BY case_id",
                            (case_id,)).fetchall()
    prior = [d for d in (Dossier.model_validate_json(r["dossier_json"]) for r in rows)
             if d.stages and not d.blocker_hit]
    return Context(config, load("entity.json"), load("vendor_master.json"),
                   {p["po_number"]: p for p in load("po_master.json")},
                   {a["code"]: a for a in load("chart_of_accounts.json")},
                   load("hsn_gst_rates.json"), prior)


# ------------------------------------------------------------- helpers -----
def _key(s):
    """Identifier compare form: no whitespace, uppercase."""
    return re.sub(r"\s", "", str(s)).upper() if s is not None else None


def _digits(s):
    """Bank account / IFSC compare form: spaces and dashes ignored."""
    return re.sub(r"[\s-]", "", str(s)).upper() if s is not None else None


def _name(s):
    return " ".join(str(s).casefold().split())


def _date(s):
    try:
        return date.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def _inr(x):
    """Indian digit grouping: 183136 -> 'Rs 1,83,136.00'."""
    whole, frac = f"{abs(x):.2f}".split(".")
    head, tail = whole[:-3], whole[-3:]
    while len(head) > 2:
        head, tail = head[:-2], f"{head[-2:]},{tail}"
    return f"{'-' if x < 0 else ''}Rs {head + ',' if head else ''}{tail}.{frac}"


def _val(inv: Invoice, key: str):
    m = re.fullmatch(r"line_items\[(\d+)\]\.(\w+)", key)
    return getattr(inv.line_items[int(m[1])], m[2]) if m else getattr(inv, key)


def _conf(inv: Invoice, *keys) -> float:
    """Weakest extraction confidence among the printed fields an op relied on."""
    vals = [inv.per_field_confidence.get(k, 0.0) for k in keys if _val(inv, k) is not None]
    return round(min(vals), 3) if vals else 0.0


def _line_keys(inv: Invoice, *fields) -> list[str]:
    return [f"line_items[{i}].{f}" for i in range(len(inv.line_items)) for f in fields]


def _subtotal(inv: Invoice) -> float:
    return inv.subtotal if inv.subtotal is not None else sum(li.taxable_value or 0 for li in inv.line_items)


def _tolerance(base: float, config: dict) -> float:
    """Total tolerance: min(total_pct of base, absolute cap)."""
    t = config["tolerances"]
    return min(t["total_pct"] / 100 * abs(base), t["total_absolute_cap_inr"])


def _vendor(ctx: Context, d: Dossier) -> dict:
    return next(v for v in ctx.vendors if v["vendor_id"] == d.resolved["vendor_id"])


def _op(d: Dossier, op_id: str) -> OpResult | None:
    return next((o for s in d.stages.values() for o in s.ops if o.op_id == op_id), None)


def _gstin_problem(g: str, pan: str | None = None) -> str | None:
    m = GSTIN_RE.fullmatch(g)
    if not m:
        return "isn't in the 15-character tax ID format"
    if not 1 <= int(m[1]) <= 38:
        return f"has an unknown state code ({m[1]})"
    total = 0
    for i, c in enumerate(g[:14]):
        p = B36.index(c) * (2 if i % 2 else 1)
        total += p // 36 + p % 36
    if B36[(36 - total % 36) % 36] != g[14]:
        return "fails the check-digit test (likely mistyped or misread)"
    if pan and _key(pan) != m[2]:
        return f"doesn't contain the vendor's PAN ({pan})"
    return None


# ----------------------------------------------------------------- ops -----
# Each op: (invoice, context, dossier) -> (result, reason, evidence, confidence)

def op_doc_type(inv, ctx, d):
    t, c = inv.document_type, _conf(inv, "document_type")
    ev = {"document_type": t}
    if t == "tax_invoice":
        return "pass", "The document is a tax invoice.", ev, c
    label = (t or "unrecognised document").replace("_", " ")
    if t in ("credit_note", "debit_note"):
        return "fail", f"This is a {label}, not a tax invoice. Credit and debit notes go through a separate flow (not built).", ev, c
    return "fail", f"This is a {label}, not a tax invoice, so it can't be booked or paid as one.", ev, c


def op_bill_to(inv, ctx, d):
    e = ctx.entity
    ev = {"invoice_buyer_gstin": inv.buyer_gstin, "invoice_buyer_name": inv.buyer_name, "our_gstin": e["gstin"]}
    if inv.buyer_gstin:
        ok, c = _key(inv.buyer_gstin) == e["gstin"], _conf(inv, "buyer_gstin")
        reason = (f"Billed to our tax ID ({e['gstin']})." if ok else
                  f"Billed to tax ID {inv.buyer_gstin}, which isn't ours ({e['gstin']}).")
    else:
        names = {_name(n) for n in [e["legal_name"], *e["aliases"]]}
        ok, c = inv.buyer_name is not None and _name(inv.buyer_name) in names, _conf(inv, "buyer_name")
        reason = ("No buyer tax ID printed; the buyer name matches our company." if ok else
                  f"No buyer tax ID printed, and the buyer name '{inv.buyer_name}' isn't our company.")
    if ok:
        d.resolved["entity_id"] = e["entity_id"]
    return ("pass" if ok else "fail"), reason, ev, c


def op_vendor(inv, ctx, d):
    g = _key(inv.vendor_gstin)
    v, how = next((v for v in ctx.vendors if g and v["gstin"] == g), None), "tax ID"
    if not v and inv.vendor_name:
        v, how = next((v for v in ctx.vendors if _name(inv.vendor_name) in
                       {_name(n) for n in [v["legal_name"], *v["aliases"]]}), None), "name"
    ev = {"invoice_vendor_name": inv.vendor_name, "invoice_vendor_gstin": inv.vendor_gstin,
          "matched_vendor_id": v and v["vendor_id"], "matched_on": v and how}
    c = _conf(inv, "vendor_gstin") if how == "tax ID" else _conf(inv, "vendor_name")
    if not v:
        return "fail", f"'{inv.vendor_name}' (tax ID {inv.vendor_gstin}) isn't in our vendor master.", ev, c
    if v["status"] != "active":
        return "fail", f"{v['legal_name']} is in the vendor master but marked {v['status']}.", ev, c
    d.resolved["vendor_id"] = v["vendor_id"]
    if how == "name":
        return "warn", (f"Matched {v['legal_name']} by name, but the invoice's tax ID "
                        f"({inv.vendor_gstin or 'none printed'}) isn't the one on file ({v['gstin']})."), ev, c
    return "pass", f"Known vendor: {v['legal_name']} ({v['vendor_id']}).", ev, c


def op_bank(inv, ctx, d):
    v = _vendor(ctx, d)
    pairs = {"account number": (inv.vendor_bank_acct, v["bank_acct"]), "IFSC": (inv.vendor_bank_ifsc, v["bank_ifsc"])}
    ev = {"invoice_bank_acct": inv.vendor_bank_acct, "master_bank_acct": v["bank_acct"],
          "invoice_bank_ifsc": inv.vendor_bank_ifsc, "master_bank_ifsc": v["bank_ifsc"],
          "master_bank_last_updated": v["bank_last_updated"]}
    c = _conf(inv, "vendor_bank_acct", "vendor_bank_ifsc")
    wrong = [k for k, (got, exp) in pairs.items() if got is not None and _digits(got) != _digits(exp)]
    missing = [k for k, (got, _) in pairs.items() if got is None]
    if wrong:
        return "fail", (f"The bank {' and '.join(wrong)} on the invoice differ from the vendor master. "
                        "Possible payment fraud: confirm with the vendor on a known phone number before paying."), ev, c
    if missing:
        return "warn", f"No bank {' or '.join(missing)} printed; payment would use the details on file.", ev, c
    return "pass", "Bank details match the vendor master.", ev, c


def op_hard_dup(inv, ctx, d):
    vid, num = d.resolved["vendor_id"], _key(inv.invoice_number)
    ev = {"earlier_cases_checked": len(ctx.prior)}
    for p in ctx.prior:
        pi = p.invoice_extracted
        if pi.file_hash == inv.file_hash:
            return "fail", f"This is the same file as {p.case_id}.", {**ev, "duplicate_of": p.case_id,
                                                                     "matched_on": "file hash"}, 1.0
        if num and p.resolved.get("vendor_id") == vid and _key(pi.invoice_number) == num:
            return "fail", (f"Invoice {inv.invoice_number} from this vendor was already received as {p.case_id}. "
                            "Paying it again would be a double payment."), \
                {**ev, "duplicate_of": p.case_id, "matched_on": "vendor + invoice number",
                 "invoice_number": inv.invoice_number}, _conf(inv, "invoice_number")
    if not num:
        return "warn", "No invoice number printed, so only the same-file check was possible.", ev, 0.0
    return "pass", "No earlier invoice with this number from this vendor.", ev, _conf(inv, "invoice_number")


def op_near_dup(inv, ctx, d):
    vid, dt, num = d.resolved["vendor_id"], _date(inv.invoice_date), _key(inv.invoice_number)
    c = _conf(inv, "grand_total", "invoice_date")
    if dt is None or inv.grand_total is None:
        return "warn", "Invoice date or total missing, so the near-duplicate check couldn't run.", {}, c
    for p in ctx.prior:
        pi, pd = p.invoice_extracted, _date(p.invoice_extracted.invoice_date)
        if (p.resolved.get("vendor_id") == vid and pi.grand_total is not None
                and abs(pi.grand_total - inv.grand_total) < 0.01 and pd and abs((pd - dt).days) <= NEAR_DUP_DAYS
                and not (num and _key(pi.invoice_number) == num)):
            days = abs((pd - dt).days)
            return "fail", (f"Looks like a re-bill of {p.case_id}: same vendor, same total ({_inr(inv.grand_total)}), "
                            f"{days} days apart, different invoice number ({pi.invoice_number} vs "
                            f"{inv.invoice_number})."), \
                {"similar_to": p.case_id, "grand_total": inv.grand_total, "days_apart": days,
                 "window_days": NEAR_DUP_DAYS, "this_invoice_number": inv.invoice_number,
                 "earlier_invoice_number": pi.invoice_number}, c
    return "pass", f"No earlier invoice from this vendor for the same amount within ±{NEAR_DUP_DAYS} days.", \
        {"earlier_cases_checked": len(ctx.prior), "window_days": NEAR_DUP_DAYS}, c


def op_po(inv, ctx, d):
    ref, c = _key(inv.po_reference), _conf(inv, "po_reference")
    ev = {"po_reference": inv.po_reference}
    if not ref:
        return "fail", ("No purchase order number on the invoice (non-PO invoice). "
                        "Finding the order automatically isn't built."), ev, c
    po = ctx.pos.get(ref)
    if not po:
        return "fail", f"Purchase order {inv.po_reference} doesn't exist in our records.", ev, c
    ev |= {"po_status": po["status"], "po_vendor_id": po["vendor_id"]}
    if po["vendor_id"] != d.resolved["vendor_id"]:
        return "fail", f"Purchase order {ref} belongs to a different vendor ({po['vendor_id']}).", ev, c
    if po["status"] != "open":
        return "fail", f"Purchase order {ref} is {po['status']}, so nothing more can be billed against it.", ev, c

    earlier = {p.case_id: _subtotal(p.invoice_extracted) for p in ctx.prior if p.resolved.get("po_number") == ref}
    remaining = po["remaining_balance"] - sum(earlier.values())
    amount, allowance = _subtotal(inv), _tolerance(remaining, ctx.config)
    ev |= {"po_total_value": po["total_value"], "master_remaining_balance": po["remaining_balance"],
           "reserved_by_earlier_cases": earlier, "effective_remaining": round(remaining, 2),
           "invoice_subtotal": amount, "over_billing_allowance": round(allowance, 2),
           "remaining_after_this_invoice": round(remaining - amount, 2)}
    c = _conf(inv, "po_reference", "subtotal")
    after = f" after {', '.join(earlier)}" if earlier else ""
    if amount > remaining + allowance:
        return "fail", (f"Purchase order {ref} has {_inr(remaining)} left{after}, but this invoice bills "
                        f"{_inr(amount)} before tax (PO exceeded)."), ev, c
    d.resolved["po_number"] = ref
    return "pass", (f"Purchase order {ref} is open: {_inr(remaining)} left{after}, "
                    f"{_inr(max(remaining - amount, 0))} after this invoice."), ev, c


def _similarity(a, b):
    return difflib.SequenceMatcher(None, _name(a or ""), _name(b or "")).ratio()


def op_po_match(inv, ctx, d):
    po, tol = ctx.pos[d.resolved["po_number"]], ctx.config["tolerances"]
    billed_before = {}  # item_code -> qty billed on earlier cases linked to this PO
    for p in ctx.prior:
        if p.resolved.get("po_number") == po["po_number"] and (m := _op(p, "8")):
            for ln in m.evidence.get("lines", []):
                if ln.get("item_code"):
                    billed_before[ln["item_code"]] = billed_before.get(ln["item_code"], 0) + (ln["qty"] or 0)

    unused, lines, problems = list(po["line_items"]), [], []
    expected = actual = 0.0
    for n, li in enumerate(inv.line_items, 1):
        cands = [p for p in unused if p["hsn_sac"] == _key(li.hsn_sac)] or unused
        best = max(cands, key=lambda p: _similarity(li.desc, p["desc"]), default=None)
        if best is None or _similarity(li.desc, best["desc"]) < MIN_DESC_SIMILARITY:
            lines.append({"line": n, "desc": li.desc, "item_code": None, "qty": li.qty})
            problems.append(f"line {n} ('{li.desc}') isn't on the purchase order")
            continue
        unused.remove(best)
        qty = li.qty or 0
        qty_so_far = billed_before.get(best["item_code"], 0) + qty
        qty_cap = best["qty_ordered"] * (1 + tol["qty_pct"] / 100)
        var = (None if li.unit_price is None else
               round((li.unit_price - best["unit_price"]) / best["unit_price"] * 100, 2))
        ok = var is not None and abs(var) <= tol["price_pct"] and qty_so_far <= qty_cap
        lines.append({"line": n, "desc": li.desc, "item_code": best["item_code"], "qty": li.qty,
                      "qty_billed_before": billed_before.get(best["item_code"], 0), "qty_ordered": best["qty_ordered"],
                      "unit_price": li.unit_price, "po_unit_price": best["unit_price"], "price_variance_pct": var,
                      "ok": ok})
        if var is None:
            problems.append(f"line {n} unit price couldn't be read")
        elif abs(var) > tol["price_pct"]:
            problems.append(f"line {n} unit price {_inr(li.unit_price)} is {var:+.1f}% vs the order's "
                            f"{_inr(best['unit_price'])} (limit ±{tol['price_pct']:g}%)")
        if qty_so_far > qty_cap:
            problems.append(f"line {n} brings quantity billed to {qty_so_far:g}, more than the {best['qty_ordered']:g} "
                            f"ordered (limit +{tol['qty_pct']:g}%)")
        expected += qty * best["unit_price"]
        actual += li.taxable_value if li.taxable_value is not None else qty * (li.unit_price or 0)

    diff, allow = round(actual - expected, 2), _tolerance(expected, ctx.config)
    pct = round(diff / expected * 100, 2) if expected else None
    if not inv.line_items:
        problems.append("no line items could be read")
    elif expected and abs(diff) > allow:
        problems.append(f"total is {_inr(diff)} ({pct:+.2f}%) off the order's prices, more than the "
                        f"{_inr(allow)} allowed")
    ev = {"match_type": TWO_WAY, "po_number": po["po_number"], "lines": lines, "expected_total": round(expected, 2),
          "invoiced_total": round(actual, 2), "total_variance": diff, "total_variance_pct": pct,
          "total_tolerance": round(allow, 2)}
    c = _conf(inv, *_line_keys(inv, "qty", "unit_price", "taxable_value"))
    if problems:
        return "fail", f"Doesn't match purchase order {po['po_number']}: " + "; ".join(problems) + \
            f". Checked {TWO_WAY}.", ev, c
    return "pass", (f"Every line matches purchase order {po['po_number']} within tolerance; total "
                    f"{pct:+.2f}% ({_inr(diff)}). Checked {TWO_WAY}."), ev, c


def op_arithmetic(inv, ctx, d):
    checks = []

    def chk(label, computed, printed):
        if computed is not None and printed is not None:
            checks.append({"check": label, "computed": round(computed, 2), "printed": printed,
                           "ok": abs(computed - printed) <= MONEY_TOL})

    for n, li in enumerate(inv.line_items, 1):
        if li.qty is not None and li.unit_price is not None:
            chk(f"line {n}: quantity x price = taxable value", li.qty * li.unit_price - (li.discount or 0),
                li.taxable_value)
        for t in ("cgst", "sgst", "igst"):
            rate, amt = getattr(li, f"{t}_rate"), getattr(li, f"{t}_amt")
            if li.taxable_value is not None and rate is not None:
                chk(f"line {n}: {t.upper()} {rate:g}% of taxable value", li.taxable_value * rate / 100, amt)
    taxable = [li.taxable_value for li in inv.line_items]
    line_tax = sum((li.cgst_amt or 0) + (li.sgst_amt or 0) + (li.igst_amt or 0) for li in inv.line_items)
    if taxable and None not in taxable:
        chk("lines add up to the subtotal", sum(taxable), inv.subtotal)
    chk("line taxes add up to the total tax", line_tax, inv.total_tax)
    sub = inv.subtotal if inv.subtotal is not None else (sum(taxable) if taxable and None not in taxable else None)
    if sub is not None:
        tax = inv.total_tax if inv.total_tax is not None else line_tax
        chk("subtotal + tax + round-off = grand total", sub + tax + (inv.round_off or 0), inv.grand_total)

    c = _conf(inv, "subtotal", "total_tax", "round_off", "grand_total",
              *_line_keys(inv, "qty", "unit_price", "discount", "taxable_value",
                          "cgst_rate", "cgst_amt", "sgst_rate", "sgst_amt", "igst_rate", "igst_amt"))
    ev = {"tolerance_inr": MONEY_TOL, "checks": checks}
    bad = [x for x in checks if not x["ok"]]
    if bad:
        return "fail", "The numbers don't add up: " + "; ".join(
            f"{x['check']}: works out to {_inr(x['computed'])} but {_inr(x['printed'])} is printed" for x in bad) + ".", ev, c
    if not checks:
        return "warn", "Not enough numbers were readable to check the arithmetic.", ev, c
    return "pass", f"All {len(checks)} arithmetic checks agree to within {_inr(MONEY_TOL)}.", ev, c


def op_tax(inv, ctx, d):
    problems, notes, ev = [], [], {}
    check_active = ctx.config["op_toggles"].get("gstin_active_check", True)
    active = {v["gstin"] for v in ctx.vendors} | {ctx.entity["gstin"]}
    for who, raw, pan in (("vendor", inv.vendor_gstin, inv.vendor_pan), ("buyer", inv.buyer_gstin, None)):
        g = _key(raw)
        if not g:
            notes.append(f"no {who} tax ID printed")
            continue
        problem = _gstin_problem(g, pan)
        if not problem and check_active and g not in active:
            problem = "isn't on the list of active tax IDs"
        ev[f"{who}_gstin"] = {"value": g, "problem": problem,
                              "active_check": "mocked list (production: GSTN portal)" if check_active
                              else "turned off in Settings"}
        if problem:
            problems.append(f"{who} tax ID {g} {problem}")

    vendor_state = _key(inv.vendor_gstin)[:2] if inv.vendor_gstin else None
    m = re.search(r"\b(\d{2})\b", inv.place_of_supply or "")
    pos_state = m[1] if m else (_key(inv.buyer_gstin)[:2] if inv.buyer_gstin else ctx.entity["state_code"])
    intra = vendor_state == pos_state
    ev |= {"vendor_state_code": vendor_state, "place_of_supply_state_code": pos_state,
           "supply": "intra-state (CGST + SGST)" if intra else "inter-state (IGST)", "lines": []}

    for n, li in enumerate(inv.line_items, 1):
        hsn = _key(li.hsn_sac)
        cg, sg, ig = li.cgst_rate or 0, li.sgst_rate or 0, li.igst_rate or 0
        rate, ref = cg + sg + ig, ctx.hsn_rates.get(hsn or "")
        ev["lines"].append({"line": n, "hsn_sac": hsn, "gst_rate": rate, "reference_rate": ref})
        if not hsn:
            notes.append(f"line {n} has no product category code (HSN/SAC)")
        elif not HSN_RE.fullmatch(hsn):
            problems.append(f"line {n} product category code {hsn} isn't a valid HSN/SAC")
        if rate not in GST_SLABS:
            problems.append(f"line {n} GST rate {rate:g}% isn't a GST rate slab")
        elif ref is not None and rate != ref:
            problems.append(f"line {n} GST rate {rate:g}% doesn't match the {ref:g}% for code {hsn}")
        if vendor_state and rate:
            if intra and (ig or cg != sg):
                problems.append(f"line {n}: vendor is in the same state as the place of supply, so tax should be "
                                "CGST + SGST split equally, not IGST")
            elif not intra and (cg or sg):
                problems.append(f"line {n}: vendor is in another state, so tax should be IGST, not CGST + SGST")

    c = _conf(inv, "vendor_gstin", "buyer_gstin", *_line_keys(inv, "hsn_sac", "cgst_rate", "sgst_rate", "igst_rate"))
    if problems:
        return "fail", "Tax check failed: " + "; ".join(problems) + ".", ev, c
    if notes:
        return "warn", "Tax checks passed, but " + "; ".join(notes) + ".", ev, c
    return "pass", (f"Both tax IDs are valid{' and active' if check_active else ''}; every line's product code "
                    f"and GST rate check out ({ev['supply']})."), ev, c


def op_coding(inv, ctx, d):
    v = _vendor(ctx, d)
    gl, acct = v["default_gl_account"], ctx.accounts.get(v["default_gl_account"], {})
    lines = [{"line": n, "desc": li.desc, "gl_account": gl, "gl_name": acct.get("name"),
              "cost_center": v["default_cost_center"], "capex_opex": acct.get("capex_opex"),
              "amount": li.taxable_value} for n, li in enumerate(inv.line_items, 1)]
    return "pass", (f"Suggested coding (vendor default): {acct.get('name')} ({gl}, {acct.get('capex_opex')}), "
                    f"cost center {v['default_cost_center']}. Advisory only; the analyst confirms."), \
        {"source": "vendor master default", "lines": lines}, _conf(inv, "vendor_gstin")


# (op_id, name, stage, tier, fn, config toggle)
OPS = [
    ("1", "Document is a tax invoice", "A", "T1", op_doc_type, None),
    ("2", "Billed to our company", "A", "T1", op_bill_to, None),
    ("3", "Vendor is in our vendor master", "A", "T1", op_vendor, None),
    ("4", "Bank details match the vendor master", "A", "T1", op_bank, None),
    ("5", "Not a duplicate of an earlier invoice", "A", "T1", op_hard_dup, None),
    ("6", "Not a near-duplicate", "A", "T3", op_near_dup, "near_dup_check"),
    ("7", "Purchase order is valid and has balance left", "B", "T2", op_po, None),
    ("8", "Matches the purchase order", "C", "T3", op_po_match, None),
    ("9", "Arithmetic adds up", "D", "T3", op_arithmetic, None),
    ("10", "Tax IDs and GST rates are valid", "E", "T3", op_tax, None),
    ("F1", "Suggested accounting code", "F", "T4", op_coding, "coding_suggestion"),
]


def _severity(op_id, tier, result):
    if result == "fail":
        return "critical" if op_id == "4" else "high" if tier == "T1" else "medium"
    if result == "warn":
        return "low"
    return "info" if tier == "T4" and result == "pass" else "none"


def _stage_status(ops: list[OpResult]) -> str:
    if any(o.result == "fail" for o in ops):
        return "failed"
    if all(o.result in ("skipped", "not_evaluated") for o in ops):
        return "skipped"
    return "passed"


# ----------------------------------------------------------------- run -----
def run(dossier: Dossier, ctx: Context) -> Dossier:
    inv = dossier.invoice_extracted
    dossier.resolved = {"entity_id": None, "vendor_id": None, "po_number": None}
    dossier.missing_required_fields = [f for f in ctx.config["required_fields"] if getattr(inv, f) in (None, "")]

    results, blocker = [], None
    for op_id, name, stage, tier, fn, toggle in OPS:
        meta = {"op_id": op_id, "name": name, "stage": stage, "tier": tier}
        if blocker:
            results.append(OpResult(**meta, result="skipped", severity="none", confidence=None, evidence={},
                                    reason=f"Skipped: Op {blocker} stopped the run."))
        elif op_id == "8" and next(r for r in results if r.op_id == "7").result == "fail":
            results.append(OpResult(**meta, result="not_evaluated", severity="none", confidence=None, evidence={},
                                    reason="Not evaluated: the purchase order check (Op 7) failed."))
        elif toggle and not ctx.config["op_toggles"].get(toggle, True):
            results.append(OpResult(**meta, result="skipped", severity="none", confidence=None, evidence={},
                                    reason="Turned off in Settings."))
        else:
            result, reason, evidence, conf = fn(inv, ctx, dossier)
            results.append(OpResult(**meta, result=result, severity=_severity(op_id, tier, result),
                                    confidence=conf, evidence=evidence, reason=reason))
            if result == "fail" and tier == "T1":
                blocker = op_id

    dossier.stages = {s: Stage(status=_stage_status(ops), ops=ops)
                      for s in "ABCDEF" for ops in [[r for r in results if r.stage == s]]}
    dossier.blocker_hit = blocker is not None
    dossier.failures = [r.op_id for r in results if r.result == "fail"]
    dossier.warnings = [r.op_id for r in results if r.result == "warn"]
    dossier.advisories = [r.op_id for r in results if r.tier == "T4" and r.result == "pass"]
    dossier.skipped = [r.op_id for r in results if r.result in ("skipped", "not_evaluated")]
    inv.buyer_entity_id = dossier.resolved["entity_id"]
    return dossier


def decision_hint(d: Dossier) -> str:
    """First half of Verdict V1: fraud_alert / reject / flag / approve.
    Verdict splits approve into auto vs pending (confidence band + OCR review policy)."""
    if "4" in d.failures:
        return "fraud_alert"
    if d.blocker_hit:
        return "reject"
    if d.failures or d.missing_required_fields:
        return "flag"
    return "approve"
