"""Upload PDFs, run the pipeline in-process (Collection -> Categorization -> Processing -> Verdict), compare to the manifest.

Run from backend/:
    ../.venv/Scripts/python.exe scripts/run_case.py data/invoices/01_happy_path.pdf [--no-cache]
    ../.venv/Scripts/python.exe scripts/run_case.py --reset data/invoices/*.pdf

One file -> full extraction report + processing summary. Several -> one summary row each (in the order given;
#7/#8 need #1 first, #6 needs #5 first). --reset wipes the runtime DB and uploads but keeps the Gemini cache.
Uses the real runtime DB (data/ap.db), uploads and extraction cache (data/cache/).
Re-uploading the same file reuses its existing case (hard-duplicate drop at ingest).
"""
import argparse
import glob
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient  # noqa: E402

from app import settings  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Dossier, InvoiceFields, LineItem  # noqa: E402
from app.pipeline import categorization as cat  # noqa: E402
from app.pipeline import processing  # noqa: E402

META = {"case_id", "ingested_at", "source_channel", "file_hash", "buyer_entity_id", "per_field_confidence"}
HINT = {"auto_approve": "approve", "approve_pending_review": "approve", "flag": "flag", "reject": "reject",
        "fraud_alert": "fraud_alert"}
# The manifest names one failing op per invoice; #8 also fails Op 7 (PO used up by #1, per its notes).
EXTRA_FAILS = {"08_near_duplicate.pdf": ["7"]}


def same(a, b):
    if a in (None, 0) and b in (None, 0):
        return True
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return abs(a - b) < 0.005
    return " ".join(str(a).split()).casefold() == " ".join(str(b).split()).casefold()


def extraction_report(pdf: bytes, d: dict, entry: dict | None):
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


def compare(path: Path, d: Dossier, entry: dict | None) -> dict:
    """Actual vs manifest: bucket (B/C only - F/G are outcomes), decision hint, failed ops, missing fields."""
    got = {"bucket": d.categorization.routing_bucket, "hint": processing.decision_hint(d),
           "fails": d.failures, "missing": d.missing_required_fields}
    if not entry:
        return {**got, "exp_bucket": "?", "exp_hint": "?", "exp_fails": [], "ok": None}
    e = entry["expected"]
    exp_fails = ([str(e["failing_op"])] if "failing_op" in e else []) + EXTRA_FAILS.get(path.name, [])
    exp_bucket = e["routing_bucket"]
    ok = (HINT[e["decision"]] == got["hint"] and sorted(exp_fails) == sorted(got["fails"])
          and (exp_bucket not in "BC" or exp_bucket == got["bucket"])
          and (exp_bucket != "G" or bool(got["missing"])))
    return {**got, "exp_bucket": exp_bucket, "exp_hint": HINT[e["decision"]], "exp_fails": exp_fails, "ok": ok}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdfs", nargs="+", help="PDF paths (globs are expanded, for shells that don't)")
    ap.add_argument("--no-cache", action="store_true", help="force a fresh Gemini call")
    ap.add_argument("--reset", action="store_true", help="wipe runtime DB, uploads + saved config first (keeps Gemini cache)")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    paths = [Path(p) for pat in args.pdfs for p in (sorted(glob.glob(pat)) if any(ch in pat for ch in "*?[") else [pat])]

    if args.reset:
        settings.DB_PATH.unlink(missing_ok=True)
        shutil.rmtree(settings.UPLOAD_DIR, ignore_errors=True)
        settings.CONFIG_PATH.unlink(missing_ok=True)
        print("Reset: runtime DB, uploads + saved Settings config wiped (Gemini cache kept)")

    manifest = json.loads((settings.DATA_DIR / "invoices" / "manifest.json").read_text(encoding="utf-8"))
    client = TestClient(app)
    rows = []
    for path in paths:
        pdf = path.read_bytes()
        up = client.post("/api/invoices/upload", files=[("files", (path.name, pdf, "application/pdf"))])
        up.raise_for_status()
        r = up.json()["results"][0]
        case_id = r["case_id"] or r["duplicate_of"]
        print(f"Upload {path.name}: {r['status']} -> {case_id}  (sha256 {r['sha256'][:16]}...)")
        resp = client.post(f"/api/cases/{case_id}/run", params={"use_cache": not args.no_cache})
        if resp.status_code != 200:
            sys.exit(f"Run failed: {resp.status_code} {resp.text}")
        out = resp.json()
        d = Dossier.model_validate(out["dossier"])
        entry = next((e for e in manifest["invoices"] if e["sha256"] == r["sha256"]), None)
        if len(paths) == 1:
            extraction_report(pdf, out["dossier"], entry)
        rows.append((path, case_id, d, d.categorization.cache_hit, compare(path, d, entry), out["decision_card"], entry))

    print("\n=== PROCESSING vs MANIFEST ===")
    print(f"{'file':<27} {'case':<12} {'cache':<5} {'bucket':<7} {'hint (got / exp)':<26} "
          f"{'failed ops (got / exp)':<24} {'missing required':<18} ok")
    for path, case_id, d, hit, c, _, _ in rows:
        mark = "?" if c["ok"] is None else ("✓" if c["ok"] else "✗")
        print(f"{path.name:<27} {case_id:<12} {'hit' if hit else 'MISS':<5} {c['bucket'] + '/' + c['exp_bucket']:<7} "
              f"{c['hint'] + ' / ' + c['exp_hint']:<26} "
              f"{(','.join(c['fails']) or '-') + ' / ' + (','.join(c['exp_fails']) or '-'):<24} "
              f"{','.join(c['missing']) or '-':<18} {mark}")
    n_ok = sum(1 for row in rows if row[4]["ok"])
    print(f"\n{n_ok}/{len(rows)} match the manifest")

    print("\n=== VERDICT vs MANIFEST (expected.decision + routing_label) ===")
    print(f"{'file':<27} {'decision (got / exp)':<46} {'conf':>5} {'band':<6} {'routing label (got / exp)':<64} ok")
    n_ok = 0
    for path, _, _, _, _, card, entry in rows:
        exp = entry["expected"] if entry else {}
        ok = None if not entry else (card["state"] == exp["decision"] and card["routing_label"] == exp["routing_label"])
        n_ok += bool(ok)
        labels = f"{card['routing_label'] or '-'} / {exp.get('routing_label') or '-'}"
        print(f"{path.name:<27} {card['state'] + ' / ' + exp.get('decision', '?'):<46} "
              f"{card['confidence']['score']:>5.2f} {card['confidence']['band']:<6} {labels:<64} "
              f"{'?' if ok is None else '✓' if ok else '✗'}")
    print(f"\n{n_ok}/{len(rows)} decisions match the manifest")

    print("\n=== DECISION CARDS ===")
    for path, case_id, _, _, _, card, _ in rows:
        print(f"{path.name}  [{case_id}]  {card['status_badge']}" +
              (f"  ·  {card['routing_label']}" if card["routing_label"] else ""))
        print(f"    narrative ({card['narrative_source']}): {card['narrative']}")
        if card["narrative_rejected"]:
            print(f"    LLM text not used -> {card['narrative_rejected']}")
        if card["secondary_labels"]:
            print(f"    also: {'; '.join(card['secondary_labels'])}")
        print(f"    next: {card['next_action']}  ·  approver: {card['approver_role']}  ·  "
              f"confidence {card['confidence']['score']} {card['confidence']['components']}")

    print("\n=== WHY (every op that didn't pass) ===")
    for path, case_id, d, *_ in rows:
        notable = [o for s in d.stages.values() for o in s.ops if o.result in ("fail", "warn")]
        print(f"{path.name}  [{case_id}]" + ("  - all checks passed" if not notable else ""))
        for o in notable:
            print(f"    Op {o.op_id:<3} {o.result.upper():<5} ({o.severity}) {o.reason}")


if __name__ == "__main__":
    main()
