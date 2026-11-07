"""Upload one PDF, run Collection -> Categorization -> Extraction in-process, compare to the manifest.

Run from backend/:
    ../.venv/Scripts/python.exe scripts/run_case.py data/invoices/01_happy_path.pdf [--no-cache]

Uses the real runtime DB (data/ap.db), uploads and extraction cache (data/cache/).
Re-uploading the same file reuses its existing case (hard-duplicate drop at ingest).
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient  # noqa: E402

from app import settings  # noqa: E402
from app.main import app  # noqa: E402
from app.models import InvoiceFields, LineItem  # noqa: E402
from app.pipeline import categorization as cat  # noqa: E402

META = {"case_id", "ingested_at", "source_channel", "file_hash", "buyer_entity_id", "per_field_confidence"}


def same(a, b):
    if a in (None, 0) and b in (None, 0):
        return True
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return abs(a - b) < 0.005
    return " ".join(str(a).split()).casefold() == " ".join(str(b).split()).casefold()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--no-cache", action="store_true", help="force a fresh Gemini call")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    client = TestClient(app)
    pdf = args.pdf.read_bytes()
    up = client.post("/api/invoices/upload", files=[("files", (args.pdf.name, pdf, "application/pdf"))])
    up.raise_for_status()
    r = up.json()["results"][0]
    case_id = r["case_id"] or r["duplicate_of"]
    print(f"Upload: {r['status']} -> {case_id}  (sha256 {r['sha256'][:16]}...)")

    resp = client.post(f"/api/cases/{case_id}/run", params={"use_cache": not args.no_cache})
    if resp.status_code != 200:
        sys.exit(f"Run failed: {resp.status_code} {resp.text}")
    d = resp.json()
    c, inv = d["categorization"], d["invoice_extracted"]
    conf = inv["per_field_confidence"]

    print(f"\nROUTING BUCKET: {c['routing_bucket']}  (text source: {c['text_source']}, pages: {c['page_count']}"
          + (f", OCR mean score: {c['ocr_mean_confidence']}" if c["ocr_mean_confidence"] is not None else "") + ")")
    print(f"document_type: {inv['document_type']}  |  model: {c['model']}  |  prompt: {c['prompt_version']}"
          f"  |  cache hit: {c['cache_hit']}")

    print("\n=== EXTRACTED JSON (invoice_extracted, metadata omitted) ===")
    print(json.dumps({k: v for k, v in inv.items() if k not in META}, indent=2, ensure_ascii=False))

    # Source text, to tell "not printed on the document" apart from "extracted wrong".
    _, source, _, text = cat.classify(pdf)
    if source == "ocr":
        text, _ = cat.ocr_pdf(pdf)

    manifest = json.loads((settings.DATA_DIR / "invoices" / "manifest.json").read_text(encoding="utf-8"))
    entry = next((e for e in manifest["invoices"] if e["sha256"] == r["sha256"]), None)
    gt = entry["ground_truth"] if entry else None

    rows = [(k, inv[k], gt.get(k) if gt else None) for k in InvoiceFields.model_fields
            if k not in ("line_items", "document_type")]
    for i in range(max(len(inv["line_items"]), len(gt["line_items"]) if gt else 0)):
        got_li = inv["line_items"][i] if i < len(inv["line_items"]) else {}
        exp_li = gt["line_items"][i] if gt and i < len(gt["line_items"]) else {}
        rows += [(f"line_items[{i}].{k}", got_li.get(k), exp_li.get(k)) for k in LineItem.model_fields]

    print("\n=== PER-FIELD CONFIDENCE vs MANIFEST ===")
    print(f"{'field':<28} {'conf':>5}  {'grounded':<8}  {'match':<11} extracted  [expected]")
    ungrounded = set(c["ungrounded_fields"])
    n_match = n_cmp = n_np = n_np_ok = 0
    for key, got, exp in rows:
        field = key.rsplit(".", 1)[-1]
        grounded = "-" if got is None else ("NO" if key in ungrounded else "yes")
        if gt is None:
            status = ""
        elif exp is not None and not cat.is_grounded(field, exp, text):
            n_np += 1
            n_np_ok += got is None
            status = "n/p null" if got is None else "n/p FILLED"  # rule 1: not printed -> must be null
        else:
            n_cmp += 1
            ok = same(got, exp)
            n_match += ok
            status = "ok" if ok else "MISMATCH"
        tail = "" if gt is None or same(got, exp) else f"  [{exp}]"
        print(f"{key:<28} {conf.get(key, 0):>5.2f}  {grounded:<8}  {status:<11} {got}{tail}")

    n_vals = sum(1 for _, got, _ in rows if got is not None)
    print("\n=== SUMMARY ===")
    print(f"Routing bucket:            {c['routing_bucket']}")
    print(f"Grounding (source text):   {n_vals - len(ungrounded)}/{n_vals} extracted values found on the document"
          + (f"  -> ungrounded: {sorted(ungrounded)}" if ungrounded else ""))
    if gt:
        print(f"Accuracy (vs manifest):    {n_match}/{n_cmp} printed fields match")
        print(f"Not printed on document:   {n_np} answer-key field(s) aren't on the page (derived totals);"
              f" {n_np_ok}/{n_np} left null by the model, {n_np - n_np_ok} filled in anyway")
    mand = settings.load_config()["required_fields"]
    print(f"Required fields confidence: " + ", ".join(f"{f}={conf.get(f, 0):.2f}" for f in mand)
          + f"  -> min {min(conf.get(f, 0) for f in mand):.2f}")


if __name__ == "__main__":
    main()
