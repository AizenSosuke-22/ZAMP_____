import type { DecisionState } from "../_lib/types";
import { STATE_LABEL } from "../_lib/format";
import { IconAlert, IconCheck, IconClock, IconMinus, IconShield, IconSpinner, IconX } from "./Icons";

export const STATE_TONE: Record<DecisionState, string> = {
  auto_approve: "bg-ok-bg text-ok border-ok-line",
  approve_pending_review: "bg-pend-bg text-pend border-pend-line",
  flag: "bg-flag-bg text-flag border-flag-line",
  reject: "bg-bad-bg text-bad border-bad-line",
  fraud_alert: "bg-fraud text-white border-fraud",
};

const STATE_ICON = {
  auto_approve: IconCheck,
  approve_pending_review: IconClock,
  flag: IconAlert,
  reject: IconX,
  fraud_alert: IconShield,
} as const;

const BADGE_SIZE = {
  sm: "text-xs px-1.5 py-0.5 gap-1 [&_svg]:size-3",
  md: "text-[13px] px-2 py-1 gap-1.5 [&_svg]:size-3.5",
  lg: "text-base px-3 py-1.5 gap-2 [&_svg]:size-[18px]",
};

export function StatusBadge({
  state,
  size = "md",
  className = "",
}: {
  state: DecisionState;
  size?: keyof typeof BADGE_SIZE;
  className?: string;
}) {
  const Icon = STATE_ICON[state];
  return (
    <span
      className={`inline-flex shrink-0 items-center whitespace-nowrap rounded-md border font-semibold ${STATE_TONE[state]} ${BADGE_SIZE[size]} ${className}`}
    >
      <Icon />
      {STATE_LABEL[state]}
    </span>
  );
}

export type NodeStatus = "pending" | "running" | "passed" | "failed" | "warn" | "skipped" | "not_evaluated";

export const NODE_LABEL: Record<NodeStatus, string> = {
  pending: "Pending",
  running: "Running",
  passed: "Passed",
  failed: "Failed",
  warn: "Warning",
  skipped: "Skipped",
  not_evaluated: "Not evaluated",
};

const MARK_TONE: Record<NodeStatus, string> = {
  pending: "border-idle-line bg-panel text-idle-dot",
  running: "border-accent-line bg-accent-soft text-accent",
  passed: "border-ok-line bg-ok-bg text-ok",
  failed: "border-bad-dot bg-bad-dot text-white",
  warn: "border-flag-line bg-flag-bg text-flag",
  skipped: "border-idle-line bg-idle-bg text-idle",
  not_evaluated: "border-dashed border-idle-dot bg-idle-bg text-idle",
};

export const NODE_TEXT: Record<NodeStatus, string> = {
  pending: "text-ink-3",
  running: "text-accent",
  passed: "text-ok",
  failed: "text-bad",
  warn: "text-flag",
  skipped: "text-ink-3",
  not_evaluated: "text-ink-3",
};

export function StatusMark({ status, size = "md" }: { status: NodeStatus; size?: "sm" | "md" }) {
  const box = size === "md" ? "size-6 [&_svg]:size-3.5" : "size-5 [&_svg]:size-3";
  const icon =
    status === "running" ? (
      <IconSpinner />
    ) : status === "passed" ? (
      <IconCheck />
    ) : status === "failed" ? (
      <IconX />
    ) : status === "warn" ? (
      <IconAlert />
    ) : status === "skipped" || status === "not_evaluated" ? (
      <IconMinus />
    ) : null;
  return (
    <span
      className={`relative z-10 inline-flex shrink-0 items-center justify-center rounded-full border transition-colors duration-300 ${box} ${MARK_TONE[status]}`}
    >
      {icon}
    </span>
  );
}

export function Panel({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <section className={`rounded-xl border border-line bg-panel shadow-[0_1px_2px_rgb(16_26_46/0.04)] ${className}`}>
      {children}
    </section>
  );
}

export function PanelHeader({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <header className="flex min-h-12 flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b border-line px-5 py-2.5">
      <h2 className="text-[15px] font-semibold tracking-[-0.01em] text-ink">{title}</h2>
      {children && <div className="flex items-center gap-3 text-[13px] text-ink-3">{children}</div>}
    </header>
  );
}

export function ConfidenceChip({ value }: { value: number | undefined }) {
  if (value == null) return null;
  const tone = value >= 0.85 ? "text-ok bg-ok-bg" : value >= 0.7 ? "text-pend bg-pend-bg" : "text-bad bg-bad-bg";
  return (
    <span className={`num rounded px-1 py-px text-[11px] font-medium ${tone}`} title="How sure we are we read this field correctly">
      {value.toFixed(2)}
    </span>
  );
}
