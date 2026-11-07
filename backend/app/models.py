"""PRD §9 schemas: canonical Invoice + the Dossier that flows Processing -> Verdict."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, create_model

DocType = Literal["tax_invoice", "proforma_invoice", "credit_note", "debit_note",
                  "quotation", "statement", "receipt", "other"]


class LineItem(BaseModel):
    desc: str | None = None
    hsn_sac: str | None = None
    qty: float | None = None
    uom: str | None = None
    unit_price: float | None = None
    discount: float | None = None
    taxable_value: float | None = None
    cgst_rate: float | None = None
    cgst_amt: float | None = None
    sgst_rate: float | None = None
    sgst_amt: float | None = None
    igst_rate: float | None = None
    igst_amt: float | None = None


class InvoiceFields(BaseModel):
    """What the LLM extracts from the document. Dates are ISO strings (YYYY-MM-DD)."""
    document_type: DocType | None = None
    vendor_name: str | None = None
    vendor_gstin: str | None = None
    vendor_pan: str | None = None
    vendor_bank_acct: str | None = None
    vendor_bank_ifsc: str | None = None
    buyer_name: str | None = None
    buyer_gstin: str | None = None
    invoice_number: str | None = None
    invoice_date: str | None = None
    due_date: str | None = None
    payment_terms: str | None = None
    po_reference: str | None = None
    place_of_supply: str | None = None
    currency: str | None = None
    line_items: list[LineItem] = []
    subtotal: float | None = None
    total_tax: float | None = None
    round_off: float | None = None
    grand_total: float | None = None
    reverse_charge_flag: bool | None = None


# Confidence models mirror the field models one-to-one (0-1 per field).
LineConfidence = create_model("LineConfidence", **{k: (float, ...) for k in LineItem.model_fields})
InvoiceConfidence = create_model(
    "InvoiceConfidence",
    **{k: (float, ...) for k in InvoiceFields.model_fields if k != "line_items"},
    line_items=(list[LineConfidence], ...),
)


class ExtractionResult(BaseModel):
    """Gemini response_schema."""
    invoice: InvoiceFields
    confidence: InvoiceConfidence


class Invoice(InvoiceFields):
    """PRD §9 canonical invoice = extracted fields + ingest metadata + per-field confidence."""
    case_id: str
    ingested_at: str
    source_channel: str
    file_hash: str
    buyer_entity_id: str | None = None
    per_field_confidence: dict[str, float]  # "invoice_number", "line_items[0].unit_price", ...


class Categorization(BaseModel):
    routing_bucket: Literal["A", "B", "C"]
    text_source: Literal["text_layer", "ocr"]
    page_count: int
    ocr_mean_confidence: float | None = None
    model: str
    prompt_version: str
    cache_hit: bool
    ungrounded_fields: list[str]


class OpResult(BaseModel):
    """One Processing check (PRD §7). `confidence` = weakest extracted field it relied on (None if not run)."""
    op_id: str            # "1".."10", "F1"
    name: str
    stage: str            # "A".."F"
    tier: str             # "T1".."T4"
    result: Literal["pass", "warn", "fail", "skipped", "not_evaluated"]
    severity: Literal["critical", "high", "medium", "low", "info", "none"]
    confidence: float | None
    evidence: dict
    reason: str


class Stage(BaseModel):
    status: str           # passed | failed | skipped
    ops: list[OpResult] = []


class Dossier(BaseModel):
    case_id: str
    config_version: int
    run_started: datetime
    run_ended: datetime | None = None
    categorization: Categorization | None = None
    invoice_extracted: Invoice | None = None
    stages: dict[str, Stage] = {}  # A-F, filled by Processing
    resolved: dict = {}            # {entity_id, vendor_id, po_number} as ops resolve them
    missing_required_fields: list[str] = []
    blocker_hit: bool = False
    failures: list = []
    warnings: list = []
    advisories: list = []
    skipped: list = []
