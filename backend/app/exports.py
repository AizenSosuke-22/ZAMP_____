"""V5 exports of a case's latest verdict: CSV (ERP upload, one row per invoice line) and PDF (archival)."""
import csv
import io
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

CSV_HEADER = ["case_id", "decision_state", "override_state", "routing_label", "vendor_name", "vendor_gstin",
              "invoice_number", "invoice_date", "due_date", "po_reference", "line", "desc", "hsn_sac", "qty", "uom",
              "unit_price", "taxable_value", "cgst_amt", "sgst_amt", "igst_amt", "gl_account", "cost_center",
              "capex_opex", "grand_total"]


def to_csv(record: dict, override_state: str | None) -> str:
    inv, coding = record["canonical_invoice"], record["suggested_coding"]
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(CSV_HEADER)
    for n, li in enumerate(inv["line_items"]):
        c = coding[n] if n < len(coding) else {}
        w.writerow([record["case_id"], record["decision_state"], override_state or "", record["routing_label"] or "",
                    inv["vendor_name"], inv["vendor_gstin"], inv["invoice_number"], inv["invoice_date"],
                    inv["due_date"], inv["po_reference"], n + 1, li["desc"], li["hsn_sac"], li["qty"], li["uom"],
                    li["unit_price"], li["taxable_value"], li["cgst_amt"], li["sgst_amt"], li["igst_amt"],
                    c.get("gl_account", ""), c.get("cost_center", ""), c.get("capex_opex", ""), inv["grand_total"]])
    return buf.getvalue()


def _table(rows, widths):
    t = Table(rows, colWidths=widths, hAlign="LEFT")
    t.setStyle(TableStyle([("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8), ("FONT", (0, 1), (-1, -1), "Helvetica", 8),
                           ("GRID", (0, 0), (-1, -1), 0.3, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return t


def to_pdf(card: dict, record: dict, audit: dict, overrides: list[dict]) -> bytes:
    ss = getSampleStyleSheet()
    body, h = ss["BodyText"], ss["Heading3"]
    inv, je = record["canonical_invoice"], record["computed_journal_entry"]
    badge = card["status_badge"].replace("🚨 ", "").upper()  # Helvetica has no emoji glyphs
    P = lambda s: Paragraph(escape(str(s)), body)  # noqa: E731  (data, not markup)

    story = [Paragraph(f"{badge} &nbsp; · &nbsp; {escape(card['routing_label'] or '')}", ss["Heading2"]),
             P(f"Case {record['case_id']} · confidence {card['confidence']['score']:.2f} ({card['confidence']['band']})"
               f" · approver: {card['approver_role'] or '-'}"),
             Spacer(1, 3 * mm), P(card["narrative"]), Paragraph(f"<b>Next:</b> {escape(card['next_action'])}", body)]
    for note in card["policy_notes"]:
        story.append(Paragraph(f"<i>{escape(note)}</i>", body))
    story += [Paragraph("Invoice", h), _table([
        ["Vendor", "Invoice no.", "Date", "Purchase order", "Grand total"],
        [P(inv["vendor_name"]), inv["invoice_number"] or "-", inv["invoice_date"] or "-", inv["po_reference"] or "-",
         f"Rs {inv['grand_total']:,.2f}" if inv["grand_total"] is not None else "-"]], [60 * mm, 32 * mm, 22 * mm, 32 * mm, 28 * mm])]
    if card["failed_checks"]:
        story += [Paragraph("Checks that did not pass", h), _table(
            [["Check", "Result", "What we found"]] +
            [[P(c["name"]), f"{c['result']} ({c['severity']})", P(c["reason"])] for c in card["failed_checks"]],
            [42 * mm, 24 * mm, 108 * mm])]
    if record["suggested_coding"]:
        story += [Paragraph("Suggested coding (advisory)", h), _table(
            [["Line", "Description", "GL account", "Cost center", "Amount"]] +
            [[c["line"], P(c["desc"]), f"{c['gl_account']} {c['gl_name']}", c["cost_center"], f"{c['amount']:,.2f}"]
             for c in record["suggested_coding"]], [12 * mm, 70 * mm, 46 * mm, 28 * mm, 18 * mm])]
    story += [Paragraph(f"Journal entry — {je['status']}", h)]
    if je["lines"]:
        story += [_table([["Dr/Cr", "Account", "Cost center", "Amount"]] +
                         [[x["dr_cr"], f"{x['account']} {x['account_name']}", x["cost_center"] or "",
                           f"{x['amount']:,.2f}"] for x in je["lines"]], [16 * mm, 90 * mm, 34 * mm, 34 * mm]),
                  Paragraph(f"<i>{escape(je['note'])}</i>", body)]
    for o in overrides:
        story.append(Paragraph(f"<b>Override</b> {o['created_at']}: {o['original_state']} -> {o['new_state']} by "
                               f"{escape(o['overridden_by'])} — {escape(o['reason'])}", body))
    a = record["audit"]
    story += [Spacer(1, 4 * mm), Paragraph(
        f"Audit #{audit['audit_id']} · {audit['created_at']} · pipeline {a['pipeline_version']} · config v{a['config_version']}"
        f" · entry hash {audit['entry_hash']}", ss["Italic"])]

    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=15 * mm,
                      bottomMargin=15 * mm, title=f"{record['case_id']} decision").build(story)
    return buf.getvalue()
