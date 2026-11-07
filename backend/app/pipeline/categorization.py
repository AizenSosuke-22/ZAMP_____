"""Bucket 2 (PRD §6): raw file -> canonical invoice JSON + per-field confidence + routing bucket.

Buckets built: B (text-layer PDF) and C (image -> OCR). A (e-invoice QR) is not built yet;
D-G (low confidence, handwritten, wrong doc type, missing fields) are decided downstream.

Per-field confidence = Gemini's self-reported score, then checked against the source text
("grounding"): a value we can't find in the document is capped at 0.5; on the OCR path a
value is also capped at the OCR engine's score for the text box it came from.
"""
import json
import os
import re
from datetime import date
from functools import cache

import numpy as np
import pymupdf

from app import settings
from app.models import Categorization, ExtractionResult, InvoiceFields, LineItem

PROMPT_VERSION = "extract-v1"
MIN_TEXT_CHARS = 50          # below this the text layer is treated as absent -> OCR
OCR_DPI = 200
UNGROUNDED_CAP = 0.5

SYSTEM_PROMPT = """\
You extract fields from Indian GST invoices for an accounts-payable system. You receive the raw
text of ONE document, from a PDF text layer or from OCR (OCR text may contain character errors
and imperfect reading order; OCR rows are joined with " | ").

Rules:
1. Extract only what is printed. Never calculate, infer or fill in a value that is not on the
   document. If a field is absent, return null with confidence 0.
2. Numbers: plain decimals, no commas or currency symbols. Indian grouping "1,83,136.00" -> 183136.00.
3. Dates: ISO YYYY-MM-DD. Indian documents are day-first ("05-11-2026" = 5 Nov 2026).
4. GSTIN: 15 chars, uppercase, no spaces. PAN: 10 chars.
5. Vendor = the party issuing the document. Buyer = the "Bill To" party.
6. document_type from the title and content: tax_invoice | proforma_invoice | credit_note |
   debit_note | quotation | statement | receipt | other.
7. line_items: one per row of the item table, in printed order. Tax rates are percentages (9 = 9%).
   A description that wraps onto several lines is one line item.
8. Give every field a confidence 0-1:
   1.0       printed clearly, label unambiguous
   0.7-0.9   present, but label ambiguous or characters uncertain (OCR)
   0.3-0.6   you had to choose between candidate values
   0         absent
"""


# ------------------------------------------------------------ classify -----
def classify(pdf_bytes: bytes) -> tuple[str, str, int, str]:
    """-> (routing_bucket, text_source, page_count, text_layer_text)."""
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    text = "\n".join(page.get_text() for page in doc)
    # Bucket A (e-invoice with signed IRN QR) would be detected here - not built yet.
    if len(re.sub(r"\s", "", text)) > MIN_TEXT_CHARS:
        return "B", "text_layer", doc.page_count, text
    return "C", "ocr", doc.page_count, ""


# ----------------------------------------------------------------- OCR -----
@cache
def _ocr_engine():
    from rapidocr import RapidOCR  # heavy import; only needed on the OCR path
    return RapidOCR(params={"Global.log_level": "critical"})


def ocr_pdf(pdf_bytes: bytes) -> tuple[str, list[tuple[str, float]]]:
    """-> (text with boxes grouped into reading-order rows joined by ' | ', [(box_text, score)])."""
    rows_out, boxes_out = [], []
    for page in pymupdf.open(stream=pdf_bytes, filetype="pdf"):
        pix = page.get_pixmap(dpi=OCR_DPI)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        res = _ocr_engine()(img)
        if res.txts is None:
            continue
        items = []
        for box, txt, score in zip(res.boxes, res.txts, res.scores):
            ys, xs = box[:, 1], box[:, 0]
            items.append(((ys.min() + ys.max()) / 2, ys.max() - ys.min(), xs.min(), txt, float(score)))
            boxes_out.append((txt, float(score)))
        tol = 0.5 * float(np.median([h for _, h, *_ in items]))
        rows = []
        for it in sorted(items):
            if rows and abs(it[0] - rows[-1][0][0]) <= tol:
                rows[-1].append(it)
            else:
                rows.append([it])
        rows_out += [" | ".join(i[3] for i in sorted(r, key=lambda i: i[2])) for r in rows]
    return "\n".join(rows_out), boxes_out


# -------------------------------------------------------------- Gemini -----
def call_gemini(text: str, source: str) -> dict:
    """The only network call. Returns ExtractionResult as a dict."""
    from google import genai
    from google.genai import types

    client = genai.Client(  # retry transient overload (429/5xx) with backoff before giving up
        api_key=os.environ["GEMINI_API_KEY"],
        http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(
            attempts=4, initial_delay=2, max_delay=20, http_status_codes=[429, 500, 502, 503, 504])))
    resp = client.models.generate_content(
        model=settings.GEMINI_MODEL,
        contents=f"SOURCE: {source}\n<<<\n{text}\n>>>",
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT, temperature=0,
            response_mime_type="application/json", response_schema=ExtractionResult),
    )
    return ExtractionResult.model_validate_json(resp.text).model_dump()


def extract_cached(sha256: str, text: str, source: str, use_cache: bool = True) -> tuple[dict, bool]:
    """Cache Gemini output by file hash + model + prompt version (PRD §14b offline demo)."""
    path = settings.CACHE_DIR / f"{sha256}_{settings.GEMINI_MODEL}_{PROMPT_VERSION}.json"
    if use_cache and path.exists():
        return json.loads(path.read_text(encoding="utf-8")), True
    result = call_gemini(text, source)
    settings.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result, False


# ----------------------------------------------------------- grounding -----
NUM_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
NOT_GROUNDED = {"document_type"}  # a classification, not text on the page


def _tokens(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", s.lower()))


def _numbers(s: str) -> list[float]:
    return [float(n.replace(",", "")) for n in NUM_RE.findall(s) if n.replace(",", "").strip("-")]


def _date_forms(iso: str) -> list[str]:
    d = date.fromisoformat(iso)
    return [d.strftime(f).lower() for f in
            ("%d-%b-%Y", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%Y-%m-%d", "%d%b%Y", "%d%B%Y", "%b%d,%Y")]


def is_grounded(field: str, value, text: str) -> bool:
    """Does `value` actually appear in the source text?"""
    if field in NOT_GROUNDED or isinstance(value, bool) or value == 0:
        return True  # classification / booleans / zeros ("no tax column") aren't literal text
    if isinstance(value, (int, float)):
        return any(abs(n - value) < 0.005 for n in _numbers(text))
    value = str(value)
    if field.endswith("_date"):
        try:
            squashed = re.sub(r"\s", "", text.lower())
            return any(f in squashed for f in _date_forms(value))
        except ValueError:
            return False
    toks = _tokens(value)
    return bool(toks) and toks <= _tokens(text)


def _box_score(value, boxes: list[tuple[str, float]]) -> float | None:
    """Best OCR score among boxes that contain the value (None if it spans boxes)."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        hits = [s for t, s in boxes if any(abs(n - value) < 0.005 for n in _numbers(t))]
    else:
        toks = _tokens(str(value))
        hits = [s for t, s in boxes if toks and toks <= _tokens(t)]
    return max(hits) if hits else None


def ground(result: dict, text: str, boxes: list | None = None) -> tuple[dict[str, float], list[str]]:
    """Flatten confidences to {"field": c, "line_items[i].field": c} and apply grounding caps."""
    inv, conf = result["invoice"], result["confidence"]
    pairs = [(k, inv[k], conf[k]) for k in InvoiceFields.model_fields if k != "line_items"]
    for i, li in enumerate(inv["line_items"]):
        lc = conf["line_items"][i] if i < len(conf["line_items"]) else {}
        pairs += [(f"line_items[{i}].{k}", li[k], lc.get(k, 0.0)) for k in LineItem.model_fields]

    mean_ocr = float(np.mean([s for _, s in boxes])) if boxes else None
    out, ungrounded = {}, []
    for key, value, c in pairs:
        field = key.rsplit(".", 1)[-1]
        if value is None:
            c = 0.0
        elif not is_grounded(field, value, text):
            c = min(c, UNGROUNDED_CAP)
            ungrounded.append(key)
        elif boxes is not None and field not in NOT_GROUNDED and not isinstance(value, bool) and value != 0:
            c = min(c, _box_score(value, boxes) or mean_ocr)
        out[key] = round(float(c), 3)
    return out, ungrounded


# ---------------------------------------------------------------- run ------
def categorize(pdf_bytes: bytes, sha256: str, use_cache: bool = True) -> tuple[Categorization, dict, dict]:
    """-> (Categorization, extracted invoice fields, per_field_confidence)."""
    bucket, source, pages, text = classify(pdf_bytes)
    boxes = None
    if source == "ocr":
        text, boxes = ocr_pdf(pdf_bytes)
    result, hit = extract_cached(sha256, text, source, use_cache)
    confidence, ungrounded = ground(result, text, boxes)
    cat = Categorization(
        routing_bucket=bucket, text_source=source, page_count=pages,
        ocr_mean_confidence=round(float(np.mean([s for _, s in boxes])), 3) if boxes else None,
        model=settings.GEMINI_MODEL, prompt_version=PROMPT_VERSION, cache_hit=hit,
        ungrounded_fields=ungrounded)
    return cat, result["invoice"], confidence
