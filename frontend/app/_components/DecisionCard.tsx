"use client";

import { useEffect, useRef, useState } from "react";
import type { RunView } from "../_lib/types";
import { FIELD_LABEL, STATE_LABEL, money, shortTime } from "../_lib/format";
import { Evidence } from "./Evidence";
import { IconArrow, IconChevron, IconSpinner } from "./Icons";
import { Panel, StatusBadge } from "./ui";

/** Animates a number from `from` to `to` (exponential ease-out). Jumps straight there with reduced motion. */
function useCountUp(to: number, from: number | null, duration = 1100) {
  // `frame.key` ties a frame to one from->to animation, so a new one starts at `from`, never flashing `to`.
  const key = `${from}->${to}`;
  const [frame, setFrame] = useState<{ key: string; value: number } | null>(null);
  const raf = useRef(0);
  const animate = from != null && from !== to;
  const reduced = typeof window !== "undefined" && matchMedia("(prefers-reduced-motion: reduce)").matches;
  useEffect(() => {
    if (!animate || reduced) return;
    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      setFrame({ key, value: from! + (to - from!) * (1 - Math.pow(2, -10 * t)) });
      if (t < 1) raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf.current);
  }, [animate, reduced, key, to, from, duration]);
  if (!animate || reduced) return to;
  return frame?.key === key ? frame.value : from!;
}

const BAND_TONE = { High: "text-ok bg-ok-bg border-ok-line", Medium: "text-pend bg-pend-bg border-pend-line", Low: "text-bad bg-bad-bg border-bad-line" };
const SEVERITY_TONE: Record<string, string> = {
  critical: "text-white bg-fraud",
  high: "text-bad bg-bad-bg",
  medium: "text-flag bg-flag-bg",
  low: "text-pend bg-pend-bg",
};

function Fact({ label, children, mono = false }: { label: string; children: React.ReactNode; mono?: boolean }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-ink-3">{label}</dt>
      <dd className={`mt-0.5 truncate text-sm text-ink ${mono ? "num" : ""}`}>{children}</dd>
    </div>
  );
}

export function DecisionCard({ view, previous, pendingRerun }: { view: RunView; previous: RunView | null; pendingRerun: boolean }) {
  const { card, record, dossier } = view;
  const diff = previous && previous.caseId === view.caseId && !pendingRerun ? previous : null;
  const score = useCountUp(card.confidence.score, diff ? diff.card.confidence.score : null);
  const inv = dossier.invoice_extracted;
  const journal = record.computed_journal_entry;
  const missing = dossier.missing_required_fields;
  const weakest = Object.entries(card.confidence.components).sort((a, b) => a[1] - b[1])[0];
  const changedState = diff && diff.card.state !== card.state;
  const issues = card.failed_checks;
  // Re-key on each verdict so the new narrative and badge animate in.
  const verdictKey = `${view.caseId}-${record.audit.decided_at}-${card.state}`;

  return (
    <Panel className={`relative overflow-hidden transition-[opacity,filter] duration-500 ${pendingRerun ? "opacity-55 saturate-50" : ""}`}>
      {pendingRerun && (
        <div className="absolute top-3 right-4 z-10 inline-flex items-center gap-2 rounded-md border border-accent-line bg-panel px-2.5 py-1 text-xs font-medium text-accent shadow-sm">
          <IconSpinner className="size-3.5" /> Re-running…
        </div>
      )}

      {/* Decision + confidence */}
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-4 border-b border-line px-5 pt-5 pb-4">
        <div className="min-w-0 space-y-2">
          <h2 className="text-[15px] font-semibold tracking-[-0.01em] text-ink">Decision</h2>
          <div className="flex flex-wrap items-center gap-2.5">
            {diff && (
              <>
                <span className="inline-flex items-center gap-1.5 text-sm text-ink-3">
                  <span className="struck">{STATE_LABEL[diff.card.state]}</span>
                  <span className="num text-xs">v{diff.record.audit.config_version}</span>
                </span>
                <IconArrow className="size-4 text-ink-3" />
              </>
            )}
            <span key={verdictKey} className="anim-badge-in inline-flex" style={{ animationDelay: diff ? "350ms" : "0ms" }}>
              <StatusBadge state={card.state} size="lg" />
            </span>
            {diff && (
              <span className="num text-xs text-ink-3">
                v{record.audit.config_version}
                {!changedState && <span className="font-sans"> · unchanged</span>}
              </span>
            )}
          </div>
          {card.routing_label && <p className="text-sm text-ink-2">{card.routing_label}</p>}
        </div>

        <div className="text-right">
          <p className="text-xs text-ink-3">Confidence</p>
          <div className="mt-0.5 flex items-center justify-end gap-2">
            <span className="num text-[28px] leading-none font-semibold text-ink">{score.toFixed(2)}</span>
            <span className={`rounded-md border px-1.5 py-0.5 text-xs font-semibold ${BAND_TONE[card.confidence.band]}`}>{card.confidence.band}</span>
          </div>
          <p className="mt-1.5 text-xs text-ink-3">
            {missing.length > 0 && card.confidence.components.fields === 0 ? (
              <span className="text-bad">{missing.map((f) => FIELD_LABEL[f] ?? f).join(", ")} missing from the invoice</span>
            ) : weakest[1] < 1 ? (
              <>
                Weakest link:{" "}
                {weakest[0] === "fields" ? "fields read" : weakest[0] === "checks" ? "checks passed" : "totals agree"}{" "}
                <span className="num">{weakest[1].toFixed(2)}</span>
              </>
            ) : (
              "Fields read, checks passed and totals agree"
            )}
          </p>
        </div>
      </div>

      {/* Narrative + next step */}
      <div key={verdictKey + "-n"} className="anim-fade-in space-y-3 px-5 py-4" style={{ animationDelay: diff ? "450ms" : "0ms" }}>
        <blockquote className="max-w-[70ch] text-[16px] leading-relaxed text-ink">&ldquo;{card.narrative}&rdquo;</blockquote>
        {card.policy_notes.map((n) => (
          <p key={n} className="max-w-[70ch] rounded-md bg-pend-bg px-3 py-2 text-[13px] text-pend">
            {n}
          </p>
        ))}
        <p className="flex items-start gap-2 text-sm text-ink-2">
          <span className="font-semibold text-ink">Next step</span>
          <span>{card.next_action}</span>
        </p>
      </div>

      {/* Facts */}
      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 border-t border-line px-5 py-4 sm:grid-cols-3">
        <Fact label="Routing label">{card.routing_label ?? "None — clean"}</Fact>
        <Fact label="Approver role">{card.approver_role ?? "—"}</Fact>
        <Fact label="Amount" mono>
          {money(inv?.grand_total)}
        </Fact>
        <Fact label="Vendor">{inv?.vendor_name ?? "—"}</Fact>
        <Fact label="Invoice no." mono>
          {inv?.invoice_number ?? <span className="font-sans text-bad">Missing</span>}
        </Fact>
        <Fact label="Decided">
          {shortTime(record.audit.decided_at)} · <span className="num">config v{record.audit.config_version}</span>
        </Fact>
      </dl>

      {/* Failed checks */}
      <details className="group border-t border-line" open={issues.length > 0 && issues.length <= 2}>
        <summary className="flex cursor-pointer list-none items-center gap-2 px-5 py-3 text-sm font-semibold text-ink select-none hover:bg-sunk [&::-webkit-details-marker]:hidden">
          <IconChevron className="size-3.5 text-ink-3 transition-transform duration-200 group-open:rotate-90" />
          Failed checks
          <span className={`num rounded px-1.5 text-xs ${issues.length ? "bg-bad-bg text-bad" : "bg-ok-bg text-ok"}`}>{issues.length}</span>
          {issues.length === 0 && <span className="text-[13px] font-normal text-ink-3">Every check passed.</span>}
        </summary>
        {issues.length > 0 && (
          <ul className="space-y-3 px-5 pb-4">
            {issues.map((f) => (
              <li key={f.op_id} className="rounded-lg border border-line p-3.5">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-semibold text-ink">{f.name}</span>
                  <span className={`rounded px-1.5 py-0.5 text-xs font-medium capitalize ${SEVERITY_TONE[f.severity] ?? "bg-idle-bg text-idle"}`}>
                    {f.severity} severity
                  </span>
                  {f.result === "warn" && <span className="rounded bg-flag-bg px-1.5 py-0.5 text-xs text-flag">Warning</span>}
                </div>
                <p className="mt-1 max-w-[75ch] text-[13px] text-ink-2">{f.reason}</p>
                <div className="mt-2.5">
                  <Evidence data={f.evidence} />
                </div>
              </li>
            ))}
          </ul>
        )}
      </details>

      {/* Journal entry */}
      <div className="border-t border-line px-5 py-4">
        <div className="mb-2.5 flex flex-wrap items-center gap-2">
          <h3 className="text-sm font-semibold text-ink">Journal entry</h3>
          {journal && (
            <span className="rounded bg-idle-bg px-1.5 py-0.5 text-xs text-ink-2 first-letter:uppercase">{journal.status}</span>
          )}
          {journal?.balanced === false && <span className="rounded bg-bad-bg px-1.5 py-0.5 text-xs text-bad">Doesn&rsquo;t balance</span>}
        </div>
        {!journal || journal.lines.length === 0 ? (
          <p className="text-[13px] text-ink-3">No entry: a rejected or blocked invoice isn&rsquo;t booked.</p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-line">
            <table className="w-full text-[13px]">
              <thead className="bg-sunk text-left text-xs text-ink-3">
                <tr>
                  <th className="px-3 py-2 font-medium">Account</th>
                  <th className="px-3 py-2 font-medium">Cost centre</th>
                  <th className="px-3 py-2 text-right font-medium">Dr</th>
                  <th className="px-3 py-2 text-right font-medium">Cr</th>
                </tr>
              </thead>
              <tbody>
                {journal.lines.map((l, i) => (
                  <tr key={i} className="border-t border-line">
                    <td className="px-3 py-2">
                      <span className="num text-ink-3">{l.account}</span> <span className="text-ink">{l.account_name}</span>
                    </td>
                    <td className="num px-3 py-2 text-ink-2">{l.cost_center ?? "—"}</td>
                    <td className="num px-3 py-2 text-right text-ink">{l.dr_cr === "Dr" ? money(l.amount) : ""}</td>
                    <td className="num px-3 py-2 text-right text-ink">{l.dr_cr === "Cr" ? money(l.amount) : ""}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t border-line-strong bg-sunk font-semibold">
                  <td className="px-3 py-2 text-ink" colSpan={2}>
                    Total
                  </td>
                  <td className="num px-3 py-2 text-right text-ink">{money(journal.total_debit)}</td>
                  <td className="num px-3 py-2 text-right text-ink">{money(journal.total_credit)}</td>
                </tr>
              </tfoot>
            </table>
          </div>
        )}
        {journal?.note && <p className="mt-2 max-w-[75ch] text-xs text-ink-3">{journal.note}</p>}
      </div>
    </Panel>
  );
}
