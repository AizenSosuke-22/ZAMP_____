"use client";

import { useCallback, useRef, useState } from "react";
import { IconAlert, IconCheck, IconX } from "./Icons";

export type ToastKind = "success" | "error" | "info";
interface Toast {
  id: number;
  kind: ToastKind;
  text: string;
}

export function useToasts() {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const next = useRef(1);
  const dismiss = useCallback((id: number) => setToasts((t) => t.filter((x) => x.id !== id)), []);
  const notify = useCallback(
    (kind: ToastKind, text: string) => {
      const id = next.current++;
      setToasts((t) => [...t.slice(-3), { id, kind, text }]);
      setTimeout(() => dismiss(id), kind === "error" ? 7000 : 3800);
    },
    [dismiss],
  );
  return { toasts, notify, dismiss };
}

const TONE: Record<ToastKind, string> = {
  success: "text-ok",
  error: "text-bad",
  info: "text-accent",
};

export function Toaster({ toasts, dismiss }: { toasts: Toast[]; dismiss: (id: number) => void }) {
  return (
    <div className="pointer-events-none fixed right-5 bottom-5 z-50 flex w-[min(380px,calc(100vw-2.5rem))] flex-col gap-2" aria-live="polite" role="status">
      {toasts.map((t) => (
        <div
          key={t.id}
          className="anim-toast pointer-events-auto flex items-start gap-2.5 rounded-lg border border-line bg-panel px-3.5 py-3 text-sm text-ink shadow-[0_8px_24px_-6px_rgb(16_26_46/0.22)]"
        >
          <span className={`mt-0.5 ${TONE[t.kind]}`}>{t.kind === "success" ? <IconCheck /> : t.kind === "error" ? <IconAlert /> : <IconCheck />}</span>
          <p className="flex-1 leading-snug">{t.text}</p>
          <button
            onClick={() => dismiss(t.id)}
            className="-m-1 rounded p-1 text-ink-3 hover:bg-sunk hover:text-ink"
            aria-label="Dismiss"
          >
            <IconX className="size-3.5" />
          </button>
        </div>
      ))}
    </div>
  );
}
