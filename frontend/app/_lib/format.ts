import type { DecisionState, OpOutcome } from "./types";

const inr = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", minimumFractionDigits: 2 });
const plain = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 });

export const money = (n: number | null | undefined) => (n == null ? "—" : inr.format(n));
export const num = (n: number) => plain.format(n);

export function ms(v: number | null | undefined): string | null {
  if (v == null) return null;
  if (v < 1) return "<1 ms";
  if (v < 1000) return `${Math.round(v)} ms`;
  return `${(v / 1000).toFixed(1)} s`;
}

export function shortTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const sameDay = d.toDateString() === new Date().toDateString();
  const time = d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false });
  return sameDay ? time : `${d.toLocaleDateString("en-IN", { day: "numeric", month: "short" })} ${time}`;
}

export const bytes = (n: number) => (n < 1024 * 1024 ? `${Math.max(1, Math.round(n / 1024))} KB` : `${(n / 1048576).toFixed(1)} MB`);

export const STATE_LABEL: Record<DecisionState, string> = {
  auto_approve: "Auto-approved",
  approve_pending_review: "Approve pending review",
  flag: "Flagged for review",
  reject: "Rejected",
  fraud_alert: "Fraud alert",
};

export const OUTCOME_LABEL: Record<OpOutcome, string> = {
  pass: "Passed",
  warn: "Warning",
  fail: "Failed",
  skipped: "Skipped",
  not_evaluated: "Not evaluated",
};

/** Processing stages in plain English (PRD §7 stages A–F). */
export const STAGE_LABEL: Record<string, string> = {
  A: "Pre-flight checks",
  B: "Purchase order",
  C: "Match against the order",
  D: "Arithmetic",
  E: "Tax",
  F: "Accounting code (suggestion)",
};

export const DOC_TYPE: Record<string, string> = {
  tax_invoice: "Tax invoice",
  proforma: "Proforma invoice",
  proforma_invoice: "Proforma invoice",
  credit_note: "Credit note",
  debit_note: "Debit note",
  quote: "Quotation",
  receipt: "Receipt",
  statement: "Statement",
  other: "Not an invoice",
};

// Evidence keys -> plain-English labels. Anything not listed is humanised mechanically, with jargon swapped out.
const KEY_LABEL: Record<string, string> = {
  po_number: "Purchase order",
  po_reference: "Purchase order",
  po_unit_price: "Order price",
  po_status: "Order status",
  po_total_value: "Order value",
  po_vendor_id: "Order vendor",
  unit_price: "Invoice price",
  price_variance_pct: "Price diff %",
  qty: "Qty",
  qty_ordered: "Qty ordered",
  qty_billed_before: "Billed before",
  item_code: "Item code",
  desc: "Description",
  ok: "Within limit",
  expected_total: "Order total",
  invoiced_total: "Invoiced total",
  total_variance: "Difference",
  total_variance_pct: "Difference %",
  total_tolerance: "Allowed difference",
  match_type: "Match type",
  grand_total: "Invoice total",
  gl_account: "Account",
  gl_name: "Account name",
  capex_opex: "Capex / opex",
  hsn_sac: "Product code",
};

export function labelFor(key: string): string {
  if (KEY_LABEL[key]) return KEY_LABEL[key];
  const words = key
    .replace(/gstin/gi, "tax ID")
    .replace(/\bhsn\b|\bsac\b/gi, "product code")
    .replace(/(^|_)po(_|$)/gi, "$1purchase order$2")
    .split("_")
    .join(" ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export const FIELD_LABEL: Record<string, string> = {
  vendor_name: "Vendor",
  vendor_gstin: "Vendor tax ID",
  invoice_number: "Invoice no.",
  invoice_date: "Invoice date",
  po_reference: "Purchase order",
  grand_total: "Total",
};
