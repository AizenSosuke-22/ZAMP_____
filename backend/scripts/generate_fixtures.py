"""Generate the synthetic AP fixture pack (PRD §13).

Writes to backend/data/: entity.json, vendor_master.json, po_master.json,
chart_of_accounts.json, invoices/*.pdf, invoices/manifest.json.

Deterministic: fixed seed + reportlab invariant mode, so every run produces
byte-identical files (stable SHA-256 — duplicate detection depends on it).

Run from backend/:  ../.venv/Scripts/python.exe scripts/generate_fixtures.py
All companies, GSTINs, PANs and bank accounts are fictional.
"""
import hashlib
import io
import json
import random
import re
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw, ImageFilter
from reportlab import rl_config
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

rl_config.invariant = 1  # no timestamps / random IDs in PDFs -> reproducible bytes

DATA = Path(__file__).resolve().parents[1] / "data"
INV_DIR = DATA / "invoices"


def money(x):
    return Decimal(str(x)).quantize(Decimal("0.01"), ROUND_HALF_UP)


# ---------------------------------------------------------------- GSTIN ----
B36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
GSTIN_RE = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")


def gstin_checksum(first14):
    total = 0
    for i, c in enumerate(first14):
        p = B36.index(c) * (2 if i % 2 else 1)
        total += p // 36 + p % 36
    return B36[(36 - total % 36) % 36]


def make_gstin(state_code, pan):
    base = f"{state_code}{pan}1Z"
    return base + gstin_checksum(base)


# ------------------------------------------------------------ master data --
STATES = {"27": "Maharashtra", "29": "Karnataka", "24": "Gujarat", "33": "Tamil Nadu"}

ENTITY = {
    "entity_id": "ENT-01",
    "legal_name": "Meridian Retail Pvt Ltd",
    "aliases": ["Meridian Retail Private Limited", "Meridian Retail"],
    "pan": "AAKCM4821Q",
    "state_code": "27",
    "state": STATES["27"],
    "address": "4th Floor, Meridian House, Andheri-Kurla Road, Andheri (East), Mumbai 400059, Maharashtra",
}
ENTITY["gstin"] = make_gstin(ENTITY["state_code"], ENTITY["pan"])

VENDORS = [
    {"vendor_id": "V001", "legal_name": "Shreeji Office Solutions Pvt Ltd",
     "aliases": ["Shreeji Office Solutions", "Shreeji Office", "SOS Pvt Ltd"],
     "pan": "AAFCS7342L", "state_code": "27",
     "address": "Unit 14, Kamala Mills Compound, Senapati Bapat Marg, Lower Parel, Mumbai 400013, Maharashtra",
     "bank_name": "HDFC Bank", "bank_acct": "50200041873215", "bank_ifsc": "HDFC0001234",
     "bank_last_updated": "2025-04-01", "default_gl_account": "1510",
     "default_cost_center": "CC-ADMIN", "category": "goods"},
    {"vendor_id": "V002", "legal_name": "Kaveri Infotech Services Pvt Ltd",
     "aliases": ["Kaveri Infotech", "Kaveri Infotech Services"],
     "pan": "AADCK5519H", "state_code": "29",
     "address": "No. 42, 2nd Cross, Koramangala 5th Block, Bengaluru 560095, Karnataka",
     "bank_name": "ICICI Bank", "bank_acct": "071905003318", "bank_ifsc": "ICIC0004521",
     "bank_last_updated": "2024-11-18", "default_gl_account": "5200",
     "default_cost_center": "CC-IT", "category": "services"},
    {"vendor_id": "V003", "legal_name": "Sahyadri Facility Management Pvt Ltd",
     "aliases": ["Sahyadri Facility Management", "Sahyadri FM", "Sahyadri Facilities"],
     "pan": "AAGCS2287M", "state_code": "27",
     "address": "Office 7, Sai Plaza, Baner Road, Pune 411045, Maharashtra",
     "bank_name": "State Bank of India", "bank_acct": "38214567902", "bank_ifsc": "SBIN0011987",
     "bank_last_updated": "2025-01-09", "default_gl_account": "5300",
     "default_cost_center": "CC-FACILITIES", "category": "services"},
    {"vendor_id": "V004", "legal_name": "Sabarmati Packaging Industries Pvt Ltd",
     "aliases": ["Sabarmati Packaging", "Sabarmati Packaging Industries"],
     "pan": "AAJCS6631B", "state_code": "24",
     "address": "Plot 118, GIDC Estate, Vatva, Ahmedabad 382445, Gujarat",
     "bank_name": "Axis Bank", "bank_acct": "918020047712650", "bank_ifsc": "UTIB0002233",
     "bank_last_updated": "2025-06-23", "default_gl_account": "5400",
     "default_cost_center": "CC-WAREHOUSE", "category": "goods"},
    {"vendor_id": "V005", "legal_name": "Coromandel Computers Pvt Ltd",
     "aliases": ["Coromandel Computers", "Coromandel Computer Systems"],
     "pan": "AABCC9084R", "state_code": "33",
     "address": "22, Anna Salai, Teynampet, Chennai 600018, Tamil Nadu",
     "bank_name": "Kotak Mahindra Bank", "bank_acct": "4612398870", "bank_ifsc": "KKBK0000611",
     "bank_last_updated": "2024-08-30", "default_gl_account": "1500",
     "default_cost_center": "CC-IT", "category": "goods"},
]
for v in VENDORS:
    v["gstin"] = make_gstin(v["state_code"], v["pan"])
    v["status"] = "active"
VENDOR = {v["vendor_id"]: v for v in VENDORS}

CHART_OF_ACCOUNTS = [
    {"code": "1310", "name": "Input CGST Receivable", "type": "asset", "capex_opex": None},
    {"code": "1320", "name": "Input SGST Receivable", "type": "asset", "capex_opex": None},
    {"code": "1330", "name": "Input IGST Receivable", "type": "asset", "capex_opex": None},
    {"code": "1500", "name": "Computer Equipment", "type": "asset", "capex_opex": "capex"},
    {"code": "1510", "name": "Furniture & Fixtures", "type": "asset", "capex_opex": "capex"},
    {"code": "2100", "name": "Trade Payables", "type": "liability", "capex_opex": None},
    {"code": "5100", "name": "Office Supplies & Consumables", "type": "expense", "capex_opex": "opex"},
    {"code": "5110", "name": "Repairs & Maintenance", "type": "expense", "capex_opex": "opex"},
    {"code": "5200", "name": "IT Support & Services", "type": "expense", "capex_opex": "opex"},
    {"code": "5210", "name": "Software Subscriptions", "type": "expense", "capex_opex": "opex"},
    {"code": "5300", "name": "Housekeeping & Facility Services", "type": "expense", "capex_opex": "opex"},
    {"code": "5400", "name": "Packaging Materials", "type": "expense", "capex_opex": "opex"},
    {"code": "5500", "name": "Rent", "type": "expense", "capex_opex": "opex"},
    {"code": "5600", "name": "Travel & Conveyance", "type": "expense", "capex_opex": "opex"},
    {"code": "5700", "name": "Professional & Legal Fees", "type": "expense", "capex_opex": "opex"},
]

# --------------------------------------------------------------- POs -------
# Values are the taxable value (excluding GST). billed: "full" for closed POs.
def po(number, vendor_id, status, raised, approver, lines, billed=0):
    items = [{"item_code": c, "desc": d, "hsn_sac": h, "qty_ordered": q,
              "unit_price": money(p), "line_total": money(q * p)} for c, d, h, q, p in lines]
    total = sum(i["line_total"] for i in items)
    billed = total if billed == "full" else money(billed)
    return {"po_number": number, "vendor_id": vendor_id, "status": status,
            "raised_date": raised, "approved_by": approver, "total_value": total,
            "billed_to_date": billed, "remaining_balance": total - billed, "line_items": items}


DESK = ("FUR-WS-1200", "Modular workstation desk, 1200 mm, with pedestal", "9403")
CABINET = ("FUR-FC-4D", "Steel filing cabinet, 4-drawer", "9403")
BOX5 = ("PKG-5PLY-18", "5-ply corrugated box, 18x12x12 in", "4819")
BOX3 = ("PKG-3PLY-12", "3-ply corrugated carton, 12x10x8 in", "4819")
HK_OCT = ("HK-MON", "Housekeeping services, Andheri HQ - October 2026", "998533")
HK_CONS = ("HK-CONS", "Housekeeping consumables - October 2026", "998533")
LAPTOP = ("LAP-14-I7", "Laptop 14 in, Core i7, 16 GB RAM, 512 GB SSD", "8471")
AMC_OCT = ("IT-AMC-MON", "IT infrastructure support (AMC) - October 2026", "998313")
VISITS = ("IT-ONSITE", "On-site engineer visits", "998313")
ENDPOINT = ("IT-EPS-ANN", "Managed endpoint security, annual, per device", "998313")
HELPDESK = ("IT-HD-Q3", "Helpdesk support retainer - Q3 FY26-27", "998313")

POS = [
    # --- POs backing the invoice pack ---
    po("PO-2026-0412", "V001", "open", "2026-10-06", "Manager - Admin",
       [(*DESK, 8, 14500), (*CABINET, 4, 9800)]),                                  # PO-A: #1, #7, #8
    po("PO-2026-0398", "V004", "open", "2026-10-01", "Manager - Warehouse",
       [(*BOX5, 2000, 42.00), (*BOX3, 3000, 18.00)]),                              # PO-B: #2
    po("PO-2026-0377", "V003", "open", "2026-09-26", "Manager - Facilities",
       [(*HK_OCT, 1, 68000), (*HK_CONS, 1, 7500)]),                                # PO-C: #3
    po("PO-2026-0420", "V005", "open", "2026-10-08", "CFO",
       [(*LAPTOP, 30, 65000)]),                                                    # PO-D: split, #5 + #6
    po("PO-2026-0391", "V002", "open", "2026-09-30", "Manager - IT",
       [(*AMC_OCT, 1, 85000), (*VISITS, 6, 2500)]),                                # PO-E: #9
    po("PO-2026-0405", "V002", "open", "2026-10-03", "Head - IT",
       [(*ENDPOINT, 60, 1000), (*HELPDESK, 1, 40000)]),                            # PO-F: #10
    # --- background POs: closed / cancelled / partially billed / unbilled ---
    po("PO-2026-0301", "V001", "closed", "2026-07-14", "Manager - Admin",
       [("FUR-CT-2400", "Conference table, 2400 mm", "9403", 1, 48000)], "full"),
    po("PO-2026-0355", "V001", "open", "2026-08-28", "Manager - Admin",
       [("FUR-LK-12", "Steel storage locker, 12-door", "9403", 6, 11200)], 33600),
    po("PO-2026-0288", "V002", "closed", "2026-06-30", "Head - IT",
       [("IT-AMC-Q2", "IT infrastructure support (AMC) - Q2 FY26-27", "998313", 1, 240000)], "full"),
    po("PO-2026-0366", "V002", "cancelled", "2026-09-04", "Manager - IT",
       [("IT-NETAUD", "Network security audit", "998313", 1, 75000)]),
    po("PO-2026-0430", "V002", "open", "2026-10-28", "Manager - IT",
       [("IT-AMC-MON", "IT infrastructure support (AMC) - November 2026", "998313", 1, 85000)]),
    po("PO-2026-0310", "V003", "closed", "2026-08-27", "Manager - Facilities",
       [("HK-MON", "Housekeeping services, Andheri HQ - September 2026", "998533", 1, 68000),
        ("HK-CONS", "Housekeeping consumables - September 2026", "998533", 1, 7500)], "full"),
    po("PO-2026-0378", "V003", "open", "2026-10-27", "Manager - Facilities",
       [("HK-MON", "Housekeeping services, Andheri HQ - November 2026", "998533", 1, 68000),
        ("HK-CONS", "Housekeeping consumables - November 2026", "998533", 1, 7500)]),
    po("PO-2026-0350", "V003", "open", "2026-08-20", "Manager - Facilities",
       [("HK-DEEP-WH", "Deep cleaning, Bhiwandi warehouse (quarterly visit)", "998533", 4, 22000)], 44000),
    po("PO-2026-0295", "V004", "closed", "2026-07-02", "Manager - Warehouse",
       [(*BOX5, 2500, 41.50)], "full"),
    po("PO-2026-0362", "V004", "open", "2026-09-08", "Manager - Warehouse",
       [(*BOX3, 6000, 18.00)], 54000),
    po("PO-2026-0415", "V004", "cancelled", "2026-10-05", "Manager - Warehouse",
       [("PKG-MAILER", "Printed corrugated mailer box", "4819", 1500, 26.00)]),
    po("PO-2026-0305", "V005", "closed", "2026-07-10", "Head - IT",
       [("DT-I5", "Desktop PC, Core i5, 16 GB RAM, 512 GB SSD", "8471", 5, 52000)], "full"),
    po("PO-2026-0384", "V005", "open", "2026-09-15", "Head - IT",
       [("LAP-DOCK", "Laptop docking station, USB-C", "8471", 20, 9500)], 95000),
    po("PO-2026-0408", "V005", "cancelled", "2026-10-02", "Head - IT",
       [("SRV-RACK", "Rack server, 2U, dual Xeon", "8471", 1, 380000)]),
]
PO_BY_NUM = {p["po_number"]: p for p in POS}

# ----------------------------------------------------------- invoice pack --
GST_RATE = {"9403": 18, "4819": 5, "998533": 18, "8471": 18, "998313": 18}
ONE = [(*DESK[1:], 8, "Nos", 14500), (*CABINET[1:], 4, "Nos", 9800)]  # #1 / #7 / #8 lines

INVOICES = [
    {"file": "01_happy_path.pdf", "scenario": "Clean digital, matches PO exactly",
     "vendor": "V001", "po": "PO-2026-0412", "number": "SOS/26-27/0187", "date": "2026-10-20",
     "lines": ONE,
     "expected": {"routing_bucket": "B", "decision": "auto_approve", "routing_label": None,
                  "notes": "Happy path. Intra-state (MH->MH): CGST 9% + SGST 9%."}},
    {"file": "02_within_tolerance.pdf", "scenario": "Clean digital, within tolerance",
     "vendor": "V004", "po": "PO-2026-0398", "number": "SPI/2026/1147", "date": "2026-10-21",
     "lines": [(*BOX5[1:], 2000, "Nos", 42.63), (*BOX3[1:], 3000, "Nos", 18.00)],
     "expected": {"routing_bucket": "B", "decision": "auto_approve", "routing_label": None,
                  "notes": "Line 1 unit price 42.63 vs PO 42.00 (+1.5%, inside 2%). Total +0.91% (Rs 1,260). "
                           "Inter-state GJ->MH: IGST 5% (HSN 4819, corrugated)."}},
    {"file": "03_scanned.pdf", "scenario": "Scanned image (no text layer) - OCR + cold demo",
     "vendor": "V003", "po": "PO-2026-0377", "number": "SFM/1026/0342", "date": "2026-10-31",
     "lines": [(*HK_OCT[1:], 1, "Month", 68000), (*HK_CONS[1:], 1, "Lot", 7500)], "scanned": True,
     "expected": {"routing_bucket": "C", "decision": "approve_pending_review", "routing_label": None,
                  "notes": "Exact PO match. Image-only PDF (skew, speckle, blur, JPEG) so it must go through OCR; "
                           "OCR confidence should land in the medium band. Must not be flagged."}},
    {"file": "04_proforma.pdf", "scenario": "Pro forma formatted exactly like an invoice",
     "vendor": "V005", "po": None, "number": "CC/PI/26-27/044", "date": "2026-10-15",
     "title": "PROFORMA INVOICE", "lines": [(*LAPTOP[1:], 5, "Nos", 65000)],
     "expected": {"routing_bucket": "F", "decision": "reject", "routing_label": "Reject — not a tax invoice",
                  "failing_op": 1, "notes": "Same layout as a tax invoice; only the title and PI number differ."}},
    {"file": "05_split_po_1of3.pdf", "scenario": "Invoice 1 of 3 on split PO",
     "vendor": "V005", "po": "PO-2026-0420", "number": "CC/26-27/1102", "date": "2026-10-22",
     "lines": [(*LAPTOP[1:], 10, "Nos", 65000)],
     "expected": {"routing_bucket": "B", "decision": "auto_approve", "routing_label": None,
                  "po_remaining_after": 1300000.0,
                  "notes": "10 of 30 laptops. PO remaining 19,50,000 -> 13,00,000."}},
    {"file": "06_split_po_2of3.pdf", "scenario": "Invoice 2 of 3 on same split PO",
     "vendor": "V005", "po": "PO-2026-0420", "number": "CC/26-27/1158", "date": "2026-11-04",
     "lines": [(*LAPTOP[1:], 10, "Nos", 65000)],
     "expected": {"routing_bucket": "B", "decision": "auto_approve", "routing_label": None,
                  "po_remaining_after": 650000.0,
                  "notes": "Next 10 laptops; process after #5. PO remaining 13,00,000 -> 6,50,000. "
                           "Same amount as #5 but 13 days apart, so outside the near-duplicate +/-7d window."}},
    {"file": "07_hard_duplicate.pdf", "scenario": "Hard duplicate of #1 (re-sent copy, different file)",
     "vendor": "V001", "po": "PO-2026-0412", "number": "SOS/26-27/0187", "date": "2026-10-20",
     "copy": "DUPLICATE FOR TRANSPORTER", "lines": ONE,
     "expected": {"routing_bucket": "B", "decision": "reject", "routing_label": "Reject — hard duplicate",
                  "failing_op": 5, "duplicate_of": "01_happy_path.pdf",
                  "notes": "Same vendor + invoice number + amount as #1, different SHA-256 (copy label differs), "
                           "so it passes ingest hash dedup and must be caught by Op 5 on vendor + invoice #. "
                           "Requires #1 processed first."}},
    {"file": "08_near_duplicate.pdf", "scenario": "Near-duplicate of #1 (new inv #, same amount, same vendor)",
     "vendor": "V001", "po": "PO-2026-0412", "number": "SOS/26-27/0193", "date": "2026-10-23",
     "lines": ONE,
     "expected": {"routing_bucket": "B", "decision": "flag", "routing_label": "Flag — near duplicate",
                  "failing_op": 6, "duplicate_of": "01_happy_path.pdf",
                  "notes": "Same vendor + grand total as #1, 3 days later. Requires #1 processed first. "
                           "PO-2026-0412 is fully billed by then, so Op 7 (PO exceeded) also fails."}},
    {"file": "09_missing_invoice_no.pdf", "scenario": "Missing invoice number",
     "vendor": "V002", "po": "PO-2026-0391", "number": None, "date": "2026-10-31",
     "lines": [(*AMC_OCT[1:], 1, "Month", 85000), (*VISITS[1:], 6, "Visit", 2500)],
     "expected": {"routing_bucket": "G", "decision": "flag", "routing_label": "Flag — missing mandatory fields",
                  "notes": "Invoice No. field is absent from the document entirely."}},
    {"file": "10_outside_tolerance.pdf", "scenario": "Price outside tolerance",
     "vendor": "V002", "po": "PO-2026-0405", "number": "KIS/26-27/0921", "date": "2026-10-27",
     "lines": [(*ENDPOINT[1:], 60, "Device", 1028), (*HELPDESK[1:], 1, "Lot", 40000)], "round_off": True,
     "expected": {"routing_bucket": "B", "decision": "flag", "routing_label": "Flag — tolerance breach",
                  "failing_op": 8,
                  "flips_to": {"decision": "auto_approve", "when": "tolerances.price_pct >= 2.8 (e.g. 3)"},
                  "notes": "Line 1 unit price 1,028 vs PO 1,000 (+2.8%, policy 2%). Total only +1.68% "
                           "(Rs 1,680), inside total tolerance -- so price_pct alone flips the verdict "
                           "(Settings demo spine). Grand total rounded to the rupee (round_off -0.40)."}},
]


def build_canonical(spec):
    """Ground-truth invoice in the PRD §9 canonical schema (runtime fields omitted)."""
    v = VENDOR[spec["vendor"]]
    intra = v["state_code"] == ENTITY["state_code"]
    items = []
    for desc, hsn, qty, uom, rate in spec["lines"]:
        taxable = money(qty * rate)
        r = GST_RATE[hsn]
        half = money(taxable * r / 200) if intra else Decimal("0.00")
        items.append({
            "desc": desc, "hsn_sac": hsn, "qty": qty, "uom": uom, "unit_price": money(rate),
            "discount": Decimal("0.00"), "taxable_value": taxable,
            "cgst_rate": r / 2 if intra else 0, "cgst_amt": half,
            "sgst_rate": r / 2 if intra else 0, "sgst_amt": half,
            "igst_rate": 0 if intra else r,
            "igst_amt": Decimal("0.00") if intra else money(taxable * r / 100),
        })
    subtotal = sum(i["taxable_value"] for i in items)
    total_tax = sum(i["cgst_amt"] + i["sgst_amt"] + i["igst_amt"] for i in items)
    pre = subtotal + total_tax
    grand = pre.quantize(Decimal("1"), ROUND_HALF_UP) if spec.get("round_off") else pre
    inv_date = date.fromisoformat(spec["date"])
    return {
        "vendor_name": v["legal_name"], "vendor_gstin": v["gstin"], "vendor_pan": v["pan"],
        "vendor_bank_acct": v["bank_acct"], "vendor_bank_ifsc": v["bank_ifsc"],
        "buyer_name": ENTITY["legal_name"], "buyer_gstin": ENTITY["gstin"],
        "invoice_number": spec["number"], "invoice_date": spec["date"],
        "due_date": (inv_date + timedelta(days=30)).isoformat(), "payment_terms": "Net 30",
        "po_reference": spec["po"],
        "place_of_supply": f"{ENTITY['state']} ({ENTITY['state_code']})", "currency": "INR",
        "line_items": items, "subtotal": subtotal, "total_tax": total_tax,
        "round_off": grand - pre, "grand_total": grand, "reverse_charge_flag": False,
    }


# ------------------------------------------------------------- rendering ---
def inr(d):
    """Indian digit grouping: 1234567.5 -> '12,34,567.50'."""
    whole, frac = f"{Decimal(d):.2f}".split(".")
    sign = "-" if whole.startswith("-") else ""
    whole = whole.lstrip("-")
    if len(whole) > 3:
        whole = re.sub(r"(\d)(?=(\d{2})+$)", r"\1,", whole[:-3]) + "," + whole[-3:]
    return f"{sign}{whole}.{frac}"


S = ParagraphStyle("s", fontName="Helvetica", fontSize=8, leading=10)
SB = ParagraphStyle("sb", parent=S, fontName="Helvetica-Bold")
TITLE = ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=15, leading=18, alignment=1)
GRID = [("GRID", (0, 0), (-1, -1), 0.5, colors.black), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTSIZE", (0, 0), (-1, -1), 8)]


def render_pdf(spec, c):
    v = VENDOR[spec["vendor"]]
    intra = v["state_code"] == ENTITY["state_code"]
    P = lambda t, st=S: Paragraph(t, st)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm,
                            topMargin=12 * mm, bottomMargin=12 * mm,
                            title="", author="", creator="", producer="")
    W = doc.width
    story = [Table([[P(spec.get("copy", "ORIGINAL FOR RECIPIENT"), ParagraphStyle("c", parent=S, alignment=2))]],
                   colWidths=[W]),
             P(spec.get("title", "TAX INVOICE"), TITLE), Spacer(1, 4 * mm)]

    seller = P(f"<b>{v['legal_name']}</b><br/>{v['address']}<br/>GSTIN: {v['gstin']}<br/>PAN: {v['pan']}<br/>"
               f"State: {STATES[v['state_code']]} ({v['state_code']})")
    meta_rows = ([f"Invoice No.: <b>{c['invoice_number']}</b>"] if c["invoice_number"] else []) + [
        f"Invoice Date: {date.fromisoformat(c['invoice_date']).strftime('%d-%b-%Y')}",
        f"Due Date: {date.fromisoformat(c['due_date']).strftime('%d-%b-%Y')}",
        f"Payment Terms: {c['payment_terms']}",
        f"PO Ref.: {c['po_reference'] or '-'}",
        f"Place of Supply: {c['place_of_supply']}",
        "Reverse Charge: No"]
    story += [Table([[seller, P("<br/>".join(meta_rows))]], colWidths=[W * 0.55, W * 0.45], style=GRID)]
    buyer = P(f"<b>Bill To:</b><br/><b>{ENTITY['legal_name']}</b><br/>{ENTITY['address']}<br/>"
              f"GSTIN: {ENTITY['gstin']}<br/>State: {ENTITY['state']} ({ENTITY['state_code']})")
    story += [Table([[buyer]], colWidths=[W], style=GRID), Spacer(1, 3 * mm)]

    tax_hdr = (["CGST<br/>%", "CGST<br/>Amt", "SGST<br/>%", "SGST<br/>Amt"] if intra
               else ["IGST<br/>%", "IGST<br/>Amt"])
    rows = [[P(h, SB) for h in ["#", "Description", "HSN/SAC", "Qty", "UoM", "Rate", "Taxable Value", *tax_hdr]]]
    for n, li in enumerate(c["line_items"], 1):
        tax = ([f"{li['cgst_rate']:g}", inr(li["cgst_amt"]), f"{li['sgst_rate']:g}", inr(li["sgst_amt"])]
               if intra else [f"{li['igst_rate']:g}", inr(li["igst_amt"])])
        rows.append([str(n), P(li["desc"]), li["hsn_sac"], f"{li['qty']:g}", li["uom"],
                     inr(li["unit_price"]), inr(li["taxable_value"]), *tax])
    fixed = [7 * mm, None, 18 * mm, 11 * mm, 13 * mm, 18 * mm, 22 * mm] + \
            ([13 * mm, 18 * mm] * (2 if intra else 1))
    fixed[1] = W - sum(x for x in fixed if x)
    story += [Table(rows, colWidths=fixed, repeatRows=1, style=GRID + [
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("ALIGN", (3, 1), (-1, -1), "RIGHT")]), Spacer(1, 3 * mm)]

    totals = [["Total Taxable Value", inr(c["subtotal"])]]
    if intra:
        totals += [["CGST", inr(sum(li["cgst_amt"] for li in c["line_items"]))],
                   ["SGST", inr(sum(li["sgst_amt"] for li in c["line_items"]))]]
    else:
        totals += [["IGST", inr(c["total_tax"])]]
    if c["round_off"]:
        totals += [["Round Off", inr(c["round_off"])]]
    totals += [["Grand Total (INR)", inr(c["grand_total"])]]
    story += [Table(totals, colWidths=[45 * mm, 35 * mm], hAlign="RIGHT", style=GRID + [
        ("ALIGN", (1, 0), (1, -1), "RIGHT"), ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold")]),
        Spacer(1, 5 * mm)]

    bank = P(f"<b>Bank Details</b><br/>A/c Name: {v['legal_name']}<br/>Bank: {v['bank_name']}<br/>"
             f"A/c No.: {v['bank_acct']}<br/>IFSC: {v['bank_ifsc']}")
    sign = P(f"For <b>{v['legal_name']}</b><br/><br/><br/><br/>Authorised Signatory",
             ParagraphStyle("r", parent=S, alignment=2))
    story += [Table([[bank, sign]], colWidths=[W * 0.55, W * 0.45], style=GRID),
              Spacer(1, 3 * mm), P("This is a computer-generated invoice.")]
    doc.build(story)
    return buf.getvalue()


def make_scanned(pdf_bytes, seed=1103):
    """Rasterise, then degrade like a desk scanner: skew, paper tone, speckle, blur, JPEG."""
    src = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    pix = src[0].get_pixmap(dpi=200, colorspace=pymupdf.csGRAY)
    img = Image.frombytes("L", (pix.width, pix.height), pix.samples)
    img = img.rotate(1.3, resample=Image.BICUBIC, expand=True, fillcolor=255)
    img = img.point(lambda p: int(28 + p * 0.85))  # grey paper, lifted blacks
    rng = random.Random(seed)
    draw = ImageDraw.Draw(img)
    for _ in range(6000):
        draw.point((rng.randrange(img.width), rng.randrange(img.height)), fill=rng.randint(70, 190))
    img = img.filter(ImageFilter.GaussianBlur(0.7))
    jpg = io.BytesIO()
    img.save(jpg, "JPEG", quality=55)
    out = pymupdf.open()
    page = out.new_page(width=A4[0], height=A4[1])
    page.insert_image(page.rect, stream=jpg.getvalue())
    out.set_metadata({})
    return out.tobytes(garbage=3, deflate=True, no_new_id=True)


# ---------------------------------------------------------------- checks ---
def self_checks(specs, canon, pdfs):
    results = []

    def check(name, ok):
        results.append((name, bool(ok)))

    for v in [ENTITY, *VENDORS]:
        g = v["gstin"]
        check(f"GSTIN {g} format + checksum + PAN + state ({v.get('vendor_id', 'ENTITY')})",
              GSTIN_RE.match(g) and gstin_checksum(g[:14]) == g[14]
              and g[2:12] == v["pan"] and g[:2] == v["state_code"])
    for v in VENDORS:
        check(f"IFSC {v['bank_ifsc']} format ({v['vendor_id']})", re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", v["bank_ifsc"]))
    for p in POS:
        check(f"{p['po_number']} arithmetic + vendor ref",
              all(li["line_total"] == money(li["qty_ordered"] * li["unit_price"]) for li in p["line_items"])
              and p["total_value"] == sum(li["line_total"] for li in p["line_items"])
              and p["remaining_balance"] == p["total_value"] - p["billed_to_date"]
              and p["vendor_id"] in VENDOR and p["status"] in ("open", "closed", "cancelled"))

    for s in specs:
        c, f = canon[s["file"]], s["file"]
        v = VENDOR[s["vendor"]]
        intra = v["state_code"] == ENTITY["state_code"]
        lines_ok = all(li["taxable_value"] == money(li["qty"] * li["unit_price"]) for li in c["line_items"])
        tax_ok = all((li["igst_amt"] == 0 and li["cgst_amt"] == li["sgst_amt"] > 0) if intra
                     else (li["cgst_amt"] == li["sgst_amt"] == 0 and li["igst_amt"] > 0) for li in c["line_items"])
        sums_ok = (c["subtotal"] == sum(li["taxable_value"] for li in c["line_items"])
                   and c["grand_total"] == c["subtotal"] + c["total_tax"] + c["round_off"]
                   and abs(c["round_off"]) < 1)
        check(f"{f}: arithmetic lines -> subtotal -> tax -> total", lines_ok and sums_ok)
        check(f"{f}: {'CGST+SGST (intra)' if intra else 'IGST (inter)'} applied correctly", tax_ok)
        if s["po"]:
            p = PO_BY_NUM.get(s["po"])
            check(f"{f}: PO {s['po']} exists, open, same vendor", p and p["vendor_id"] == s["vendor"] and p["status"] == "open")

        doc = pymupdf.open(stream=pdfs[f], filetype="pdf")
        text = doc[0].get_text()
        if s.get("scanned"):
            check(f"{f}: no text layer, 1 embedded image", text.strip() == "" and len(doc[0].get_images()) == 1)
        else:
            has_num = c["invoice_number"] in text if c["invoice_number"] else "Invoice No." not in text
            check(f"{f}: 1 page, text layer has {'invoice no.' if c['invoice_number'] else 'NO invoice no.'} + grand total",
                  doc.page_count == 1 and has_num and inr(c["grand_total"]) in text)

    sha = {f: hashlib.sha256(b).hexdigest() for f, b in pdfs.items()}
    a, d7, d8 = canon["01_happy_path.pdf"], canon["07_hard_duplicate.pdf"], canon["08_near_duplicate.pdf"]
    check("#7 vs #1: same vendor + inv # + amount, different SHA-256",
          (d7["vendor_gstin"], d7["invoice_number"], d7["grand_total"]) == (a["vendor_gstin"], a["invoice_number"], a["grand_total"])
          and sha["07_hard_duplicate.pdf"] != sha["01_happy_path.pdf"])
    days = (date.fromisoformat(d8["invoice_date"]) - date.fromisoformat(a["invoice_date"])).days
    check(f"#8 vs #1: same vendor + amount, new inv #, {days}d apart (<=7)",
          d8["vendor_gstin"] == a["vendor_gstin"] and d8["grand_total"] == a["grand_total"]
          and d8["invoice_number"] != a["invoice_number"] and 0 < days <= 7)
    s5, s6 = canon["05_split_po_1of3.pdf"], canon["06_split_po_2of3.pdf"]
    pd_ = PO_BY_NUM["PO-2026-0420"]
    check("#5 + #6 split PO leaves balance (remaining > 0)",
          pd_["remaining_balance"] - s5["subtotal"] - s6["subtotal"] == 650000)
    gap = (date.fromisoformat(s6["invoice_date"]) - date.fromisoformat(s5["invoice_date"])).days
    check(f"#5 vs #6: same amount but {gap}d apart (outside near-dup window)", gap > 7)

    def variance(fname):
        p = PO_BY_NUM[canon[fname]["po_reference"]]
        line = max(abs(li["unit_price"] - pl["unit_price"]) / pl["unit_price"] * 100
                   for li, pl in zip(canon[fname]["line_items"], p["line_items"]))
        diff = canon[fname]["subtotal"] - p["total_value"]
        return line, diff / p["total_value"] * 100, diff

    lp, tp, td = variance("02_within_tolerance.pdf")
    check(f"#2: max line +{lp:.2f}% (<2), total +{tp:.2f}% / Rs {td} (<2% and <5000)", lp < 2 and tp < 2 and td < 5000)
    lp, tp, td = variance("10_outside_tolerance.pdf")
    check(f"#10: max line +{lp:.2f}% (>2, <3), total +{tp:.2f}% / Rs {td} (<2% and <5000)",
          2 < lp < 3 and tp < 2 and td < 5000)
    return results, sha


# ------------------------------------------------------------------ main ---
def dump(path, obj):
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=float) + "\n",
                    encoding="utf-8", newline="\n")


def main():
    INV_DIR.mkdir(parents=True, exist_ok=True)
    for old in INV_DIR.glob("*.pdf"):
        old.unlink()

    canon = {s["file"]: build_canonical(s) for s in INVOICES}
    pdfs = {}
    for s in INVOICES:
        b = render_pdf(s, canon[s["file"]])
        pdfs[s["file"]] = make_scanned(b) if s.get("scanned") else b
        (INV_DIR / s["file"]).write_bytes(pdfs[s["file"]])

    results, sha = self_checks(INVOICES, canon, pdfs)

    dump(DATA / "entity.json", ENTITY)
    dump(DATA / "vendor_master.json", VENDORS)
    dump(DATA / "po_master.json", POS)
    dump(DATA / "chart_of_accounts.json", CHART_OF_ACCOUNTS)
    dump(INV_DIR / "manifest.json", {
        "note": "Answer key. Process invoices in file order: #7/#8 need #1 first, #6 needs #5 first. "
                "Expected decisions assume config_default.json (config_version 1).",
        "invoices": [{"file": s["file"], "sha256": sha[s["file"]], "scenario": s["scenario"],
                      "vendor_id": s["vendor"], "po_number": s["po"], "expected": s["expected"],
                      "ground_truth": canon[s["file"]]} for s in INVOICES],
    })

    for name, ok in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    failed = sum(not ok for _, ok in results)
    print(f"\n{len(results) - failed}/{len(results)} checks passed")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
