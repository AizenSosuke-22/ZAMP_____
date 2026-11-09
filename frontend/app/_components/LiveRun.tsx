"use client";

import type { Dossier, OpOutcome, OpResult, RunView } from "../_lib/types";
import { DOC_TYPE, FIELD_LABEL, OUTCOME_LABEL, STAGE_LABEL, bytes, labelFor, ms } from "../_lib/format";
import { ConfidenceChip, NODE_LABEL, NODE_TEXT, Panel, PanelHeader, StatusBadge, StatusMark, type NodeStatus } from "./ui";
import { IconArrow } from "./Icons";

export type Phase = "idle" | "uploading" | "running" | "replaying" | "done" | "error";

export interface CollectionMeta {
  caseId: string;
  filename: string;
  sizeBytes: number | null;
  sha256: string | null;
  uploadMs: number | null;
}

// Shown (pending) before any dossier exists, so the pipeline's shape is visible from the start.
export const DEFAULT_OPS: Pick<OpResult, "op_id" | "name" | "stage">[] = [
  { op_id: "1", name: "Document is a tax invoice", stage: "A" },
  { op_id: "2", name: "Billed to our company", stage: "A" },
  { op_id: "3", name: "Vendor is in our vendor master", stage: "A" },
  { op_id: "4", name: "Bank details match the vendor master", stage: "A" },
  { op_id: "5", name: "Not a duplicate of an earlier invoice", stage: "A" },
  { op_id: "6", name: "Not a near-duplicate", stage: "A" },
  { op_id: "7", name: "Purchase order is valid and has balance left", stage: "B" },
  { op_id: "8", name: "Matches the purchase order", stage: "C" },
  { op_id: "9", name: "Arithmetic adds up", stage: "D" },
  { op_id: "10", name: "Tax IDs and GST rates are valid", stage: "E" },
  { op_id: "F1", name: "Suggested accounting code", stage: "F" },
];

export const opsOf = (d: Dossier | null | undefined): OpResult[] =>
  d ? Object.keys(d.stages).sort().flatMap((s) => d.stages[s].ops) : [];

/** Steps revealed in order: 0 Collection, 1 Categorization, 2..n+1 the checks, n+2 Verdict. */
export const stepCount = (opCount: number) => opCount + 3;

const outcomeStatus = (r: OpOutcome): NodeStatus => (r === "pass" ? "passed" : r === "fail" ? "failed" : r);

function Elapsed({ value, note }: { value: string | null; note?: string }) {
  if (!value && !note) return null;
  return (
    <span className="num shrink-0 text-xs text-ink-3">
      {value}
      {note && <span className="font-sans"> {note}</span>}
    </span>
  );
}

function Node({
  title,
  status,
  elapsed,
  last = false,
  children,
}: {
  title: string;
  status: NodeStatus;
  elapsed?: React.ReactNode;
  last?: boolean;
  children?: React.ReactNode;
}) {
  return (
    <li className="relative flex gap-3.5 pb-5 last:pb-0">
      {!last && (
        <span
          aria-hidden="true"
          className={`absolute top-7 bottom-1 left-[11px] w-px transition-colors duration-500 ${
            status === "pending" ? "bg-line" : "bg-line-strong"
          }`}
        />
      )}
      <StatusMark status={status} />
      <div className="min-w-0 flex-1">
        <div className="flex min-h-6 items-center gap-2.5">
          <h3 className={`text-[15px] font-semibold ${status === "pending" ? "text-ink-3" : "text-ink"}`}>{title}</h3>
          <span className={`text-xs font-medium ${NODE_TEXT[status]}`}>{NODE_LABEL[status]}</span>
          <span className="flex-1" />
          {elapsed}
        </div>
        {children && <div className="mt-1.5">{children}</div>}
      </div>
    </li>
  );
}

export function LiveRun({
  phase,
  revealed,
  meta,
  upload,
  view,
  previous,
  runningMs,
  error,
  configVersion,
}: {
  phase: Phase;
  revealed: number;
  meta: CollectionMeta | null;
  upload: { name: string; size: number } | null;
  view: RunView | null;
  previous: RunView | null;
  runningMs: number;
  error: string | null;
  configVersion: number | null;
}) {
  const live = phase === "running" || phase === "replaying" || phase === "uploading";
  // While the request is in flight nothing past Collection is known yet, even on a re-run.
  const dossier = phase === "running" || phase === "uploading" ? null : view?.dossier ?? null;
  const ops = dossier ? opsOf(dossier) : null;
  const shape = ops ?? (view && phase === "running" ? opsOf(view.dossier) : null) ?? DEFAULT_OPS;
  const total = stepCount(shape.length);
  const stepStatus = (i: number, done: NodeStatus): NodeStatus =>
    i < revealed ? done : i === revealed && live ? "running" : "pending";

  const prevOps = new Map(
    previous && view && previous.caseId === view.caseId ? opsOf(previous.dossier).map((o) => [o.op_id, o.result] as const) : [],
  );

  // Collection
  const collectionStatus: NodeStatus =
    phase === "error" && revealed === 0 ? "failed" : phase === "uploading" ? "running" : revealed > 0 ? "passed" : "pending";

  // Categorization
  const cat = dossier?.categorization;
  const inv = dossier?.invoice_extracted;
  const catStatus: NodeStatus = phase === "error" && revealed === 1 ? "failed" : stepStatus(1, "passed");

  // Processing: done when every check is revealed
  const opsDone = revealed >= 2 + shape.length;
  const anyFail = ops?.some((o) => o.result === "fail");
  const procStatus: NodeStatus = !ops
    ? revealed >= 2 && live
      ? "running"
      : "pending"
    : opsDone
      ? anyFail
        ? "failed"
        : "passed"
      : revealed >= 2 && live
        ? "running"
        : "pending";

  // Verdict
  const verdictStatus = stepStatus(total - 1, "passed");
  const card = view?.card;

  const headerNote =
    phase === "uploading"
      ? "Uploading…"
      : phase === "running" || phase === "replaying"
        ? previous && configVersion != null
          ? `Re-running under config v${configVersion}`
          : "Running checks…"
        : phase === "done" && dossier?.timings_ms
          ? `Decided · ${ms(Object.values(dossier.timings_ms).reduce((a, b) => a + (b ?? 0), 0))} on the server`
          : phase === "error"
            ? "Stopped"
            : null;

  return (
    <Panel>
      <PanelHeader title="Live run">
        {meta && <span className="num text-ink-2">{meta.caseId}</span>}
        {headerNote && <span>{headerNote}</span>}
      </PanelHeader>

      <div className="px-5 py-5">
        {phase === "idle" && !view && (
          <p className="mb-5 text-sm text-ink-3">Upload an invoice to watch it run. Every check below lights up as it completes.</p>
        )}

        <ol>
          <Node
            title="Collection"
            status={collectionStatus}
            elapsed={<Elapsed value={ms(meta?.uploadMs)} note={meta && meta.uploadMs == null && revealed > 0 ? "received earlier" : undefined} />}
          >
            {(meta || upload) && collectionStatus !== "pending" && (
              <p className="anim-rise text-[13px] text-ink-2">
                {meta?.filename ?? upload?.name}
                {(meta?.sizeBytes ?? upload?.size) != null && <span className="text-ink-3"> · {bytes((meta?.sizeBytes ?? upload?.size)!)}</span>}
                {meta && (
                  <>
                    <span className="text-ink-3"> · case </span>
                    <span className="num">{meta.caseId}</span>
                  </>
                )}
                {meta?.sha256 && (
                  <>
                    <span className="text-ink-3"> · file fingerprint </span>
                    <span className="num text-ink-3">{meta.sha256.slice(0, 12)}…</span>
                  </>
                )}
              </p>
            )}
            {collectionStatus === "failed" && error && <p className="mt-1 text-[13px] text-bad">{error}</p>}
          </Node>

          <Node
            title="Categorization"
            status={catStatus}
            elapsed={
              catStatus === "running" ? (
                <Elapsed value={ms(runningMs)} />
              ) : catStatus === "passed" ? (
                <Elapsed value={ms(dossier?.timings_ms?.categorization)} note={cat?.cache_hit ? "(cached read)" : undefined} />
              ) : null
            }
          >
            {catStatus === "running" && <p className="text-[13px] text-ink-3">Reading the document and extracting its fields…</p>}
            {catStatus === "failed" && error && <p className="text-[13px] text-bad">{error}</p>}
            {catStatus === "passed" && cat && inv && (
              <div className="anim-rise space-y-2.5">
                <p className="text-[13px] text-ink-2">
                  {cat.text_source === "ocr" ? (
                    <>
                      Scanned page, read with OCR
                      {cat.ocr_mean_confidence != null && (
                        <span className="text-ink-3">
                          {" "}
                          (average read score <span className="num">{cat.ocr_mean_confidence.toFixed(2)}</span>)
                        </span>
                      )}
                    </>
                  ) : (
                    "Digital PDF, text read directly"
                  )}
                  <span className="text-ink-3"> · </span>
                  {DOC_TYPE[inv.document_type ?? ""] ?? labelFor(inv.document_type ?? "unknown")}
                </p>
                <dl className="grid grid-cols-2 gap-x-5 gap-y-1.5 text-[13px] sm:grid-cols-3">
                  {Object.keys(FIELD_LABEL).map((f) => {
                    const v = inv[f];
                    const missing = v == null || v === "";
                    const mono = f !== "vendor_name" && f !== "invoice_date";
                    return (
                      <div key={f} className="min-w-0">
                        <dt className="text-xs text-ink-3">{FIELD_LABEL[f]}</dt>
                        <dd className="flex min-w-0 items-center gap-1.5">
                          {missing ? (
                            <span className="font-medium text-bad">Not on the invoice</span>
                          ) : (
                            <span className={`truncate text-ink ${mono ? "num" : ""}`} title={String(v)}>
                              {f === "grand_total" ? `₹${Number(v).toLocaleString("en-IN", { minimumFractionDigits: 2 })}` : String(v)}
                            </span>
                          )}
                          {!missing && <ConfidenceChip value={inv.per_field_confidence?.[f]} />}
                        </dd>
                      </div>
                    );
                  })}
                </dl>
              </div>
            )}
          </Node>

          <Node title="Processing" status={procStatus} elapsed={opsDone ? <Elapsed value={ms(dossier?.timings_ms?.processing)} /> : null}>
            <div className="space-y-3 pt-0.5">
              {Object.keys(STAGE_LABEL).map((s) => {
                const stageOps = shape.filter((o) => o.stage === s);
                if (!stageOps.length) return null;
                return (
                  <div key={s}>
                    <p className="mb-1 text-xs font-medium text-ink-3">{STAGE_LABEL[s]}</p>
                    <ul className="divide-y divide-line rounded-lg border border-line">
                      {stageOps.map((o) => {
                        const idx = 2 + shape.indexOf(o);
                        const full = (ops?.find((x) => x.op_id === o.op_id) ?? null) as OpResult | null;
                        const status = full ? stepStatus(idx, outcomeStatus(full.result)) : stepStatus(idx, "pending");
                        const shown = full && idx < revealed;
                        const before = prevOps.get(o.op_id);
                        const changed = shown && before && before !== full.result;
                        return (
                          <li key={o.op_id} className={`px-3 py-2 ${status === "failed" ? "bg-bad-bg/50" : ""}`}>
                            <div className="flex items-center gap-2.5">
                              <StatusMark status={status} size="sm" />
                              <span className={`min-w-0 flex-1 truncate text-[13px] ${status === "pending" ? "text-ink-3" : "font-medium text-ink"}`}>
                                {o.name}
                              </span>
                              {changed && (
                                <span className="anim-changed inline-flex shrink-0 items-center gap-1 rounded-md border border-accent-line px-1.5 py-0.5 text-xs font-semibold text-accent">
                                  {OUTCOME_LABEL[before]}
                                  <IconArrow className="size-3" />
                                  {OUTCOME_LABEL[full.result]}
                                </span>
                              )}
                              {shown && status !== "passed" && (
                                <span className={`shrink-0 text-xs font-medium ${NODE_TEXT[status]}`}>{NODE_LABEL[status]}</span>
                              )}
                              {shown && <Elapsed value={ms(full.elapsed_ms)} />}
                            </div>
                            {shown && (
                              <p
                                className={`anim-rise mt-0.5 pl-[30px] text-[13px] leading-snug ${
                                  status === "failed" ? "text-bad" : status === "warn" ? "text-flag" : "text-ink-3"
                                }`}
                              >
                                {full.reason}
                              </p>
                            )}
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                );
              })}
            </div>
          </Node>

          <Node
            title="Verdict"
            status={verdictStatus}
            last
            elapsed={verdictStatus === "passed" ? <Elapsed value={ms(dossier?.timings_ms?.verdict)} /> : null}
          >
            {verdictStatus === "passed" && card && (
              <div className="anim-rise flex flex-wrap items-center gap-2.5 text-[13px] text-ink-2">
                <StatusBadge state={card.state} size="sm" />
                <span>
                  confidence <span className="num">{card.confidence.score.toFixed(2)}</span> ({card.confidence.band})
                </span>
                {card.routing_label && <span className="text-ink-3">· {card.routing_label}</span>}
              </div>
            )}
          </Node>
        </ol>
      </div>
    </Panel>
  );
}
