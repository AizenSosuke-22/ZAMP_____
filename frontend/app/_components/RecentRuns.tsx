"use client";

import type { CaseRow } from "../_lib/types";
import { money, shortTime } from "../_lib/format";
import { IconSpinner } from "./Icons";
import { Panel, PanelHeader, StatusBadge } from "./ui";

export function RecentRuns({
  cases,
  activeId,
  disabled,
  onOpen,
}: {
  cases: CaseRow[] | null;
  activeId: string | null;
  disabled: boolean;
  onOpen: (id: string) => void;
}) {
  return (
    <Panel className="flex max-h-[calc(100vh-5.5rem)] flex-col">
      <PanelHeader title="Recent runs">{cases && cases.length > 0 && <span className="num">{cases.length}</span>}</PanelHeader>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {cases == null ? (
          <p className="flex items-center gap-2 px-5 py-6 text-sm text-ink-3">
            <IconSpinner className="text-accent" /> Loading runs…
          </p>
        ) : cases.length === 0 ? (
          <div className="px-5 py-8">
            <p className="text-sm font-medium text-ink">Upload an invoice to begin.</p>
            <p className="mt-1 text-[13px] text-ink-3">Each invoice you run appears here. Click one to reopen its decision.</p>
          </div>
        ) : (
          <ul className="divide-y divide-line">
            {cases.map((c) => {
              const state = c.override_state ?? c.decision_state;
              const active = c.case_id === activeId;
              return (
                <li key={c.case_id}>
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={() => onOpen(c.case_id)}
                    aria-current={active ? "true" : undefined}
                    className={`block w-full px-5 py-3 text-left transition-colors disabled:cursor-wait ${
                      active ? "bg-accent-soft" : "hover:bg-sunk"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <span className={`num text-[13px] font-semibold ${active ? "text-accent" : "text-ink"}`}>{c.case_id}</span>
                      <span className="num text-xs text-ink-3">{shortTime(c.decided_at ?? c.ingested_at)}</span>
                    </div>
                    <p className="mt-0.5 truncate text-xs text-ink-3">{c.filename}</p>
                    <div className="mt-2 flex items-center justify-between gap-3">
                      {state ? (
                        <StatusBadge state={state} size="sm" />
                      ) : (
                        <span className="rounded-md border border-idle-line bg-idle-bg px-1.5 py-0.5 text-xs font-semibold text-idle">
                          {c.status === "needs_human" ? "Needs a person" : "Not run"}
                        </span>
                      )}
                      <span className="num text-[13px] text-ink">{money(c.grand_total)}</span>
                    </div>
                    {(c.vendor_name || c.routing_label) && (
                      <p className="mt-1.5 truncate text-xs text-ink-2">
                        {c.vendor_name}
                        {c.routing_label && <span className="text-ink-3"> · {c.routing_label.replace(/^(Flag|Reject) — /, "")}</span>}
                      </p>
                    )}
                    {c.override_state && <p className="mt-1 text-xs text-accent">Overridden by an analyst</p>}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </Panel>
  );
}
