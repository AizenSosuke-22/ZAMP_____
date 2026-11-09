"use client";

import { useRef, useState } from "react";
import type { Config } from "../_lib/types";
import { IconRerun, IconSpinner } from "./Icons";
import { Panel, PanelHeader } from "./ui";

const MIN = 1;
const MAX = 5;

export function SettingsPanel({
  config,
  saving,
  rerunCaseId,
  lastRunVersion,
  running,
  onCommit,
  onRerun,
}: {
  config: Config | null;
  saving: boolean;
  rerunCaseId: string | null;
  lastRunVersion: number | null;
  running: boolean;
  onCommit: (pct: number) => Promise<boolean>;
  onRerun: () => void;
}) {
  const saved = config?.tolerances.price_pct ?? null;
  const [value, setValue] = useState<number>(saved ?? 2);
  const [synced, setSynced] = useState<number | null>(saved);
  // Follow the server's value whenever it changes (load, or a save from here).
  if (saved !== synced) {
    setSynced(saved);
    if (saved != null) setValue(saved);
  }
  const dirty = saved != null && Math.abs(value - saved) > 1e-9;
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const change = (v: number) => {
    setValue(v);
    if (timer.current) clearTimeout(timer.current);
    // Save once the slider settles, so a drag is one config version, not thirty.
    timer.current = setTimeout(() => {
      if (saved != null && Math.abs(v - saved) > 1e-9) onCommit(v);
    }, 450);
  };

  const rerun = async () => {
    if (timer.current) clearTimeout(timer.current);
    if (dirty && !(await onCommit(value))) return;
    onRerun();
  };

  const fill = `${((value - MIN) / (MAX - MIN)) * 100}%`;
  const version = config?.config_version;

  return (
    <Panel>
      <PanelHeader title="Settings">
        {version != null && (
          <span className="inline-flex items-center gap-1.5">
            {saving && <IconSpinner className="size-3.5 text-accent" />}
            <span className="num">config v{version}</span>
          </span>
        )}
      </PanelHeader>
      <div className="grid gap-5 px-5 py-5 sm:grid-cols-[1fr_auto] sm:items-end">
        <div>
          <label htmlFor="price-tol" className="flex items-baseline justify-between gap-3">
            <span className="text-sm font-medium text-ink">Price tolerance</span>
            <span className="num text-xl font-semibold text-ink">±{value.toFixed(1)}%</span>
          </label>
          <p className="mt-0.5 text-[13px] text-ink-3">How far an invoice line&rsquo;s unit price may differ from the purchase order before we flag it.</p>
          <input
            id="price-tol"
            type="range"
            min={MIN}
            max={MAX}
            step={0.1}
            value={value}
            disabled={!config}
            onChange={(e) => change(Number(e.target.value))}
            className="tol-range mt-3"
            style={{ "--fill": fill } as React.CSSProperties}
            aria-valuetext={`plus or minus ${value.toFixed(1)} percent`}
          />
          <div className="num flex justify-between text-xs text-ink-3" aria-hidden="true">
            {[1, 2, 3, 4, 5].map((n) => (
              <span key={n}>{n}%</span>
            ))}
          </div>
        </div>

        <div className="space-y-1.5 sm:text-right">
          <button
            type="button"
            onClick={rerun}
            disabled={!rerunCaseId || running || saving || !config}
            className="inline-flex items-center gap-2 rounded-lg bg-accent px-4 py-2.5 text-sm font-semibold text-white shadow-[0_1px_2px_rgb(16_26_46/0.2)] transition-colors hover:bg-accent-hover active:translate-y-px disabled:cursor-not-allowed disabled:bg-line-strong disabled:text-ink-3 disabled:shadow-none"
          >
            {running ? <IconSpinner /> : <IconRerun />}
            {rerunCaseId ? (
              <>
                Re-run <span className="num">{rerunCaseId}</span> under v{dirty ? (version ?? 0) + 1 : version}
              </>
            ) : (
              "Re-run last invoice"
            )}
          </button>
          <p className="text-xs text-ink-3">
            {rerunCaseId && lastRunVersion != null
              ? `Its last run used config v${lastRunVersion}. Earlier runs keep the config they ran under.`
              : "Upload or open an invoice to re-run it."}
          </p>
        </div>
      </div>
    </Panel>
  );
}
