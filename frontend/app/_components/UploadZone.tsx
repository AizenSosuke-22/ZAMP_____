"use client";

import { useRef, useState } from "react";
import { bytes } from "../_lib/format";
import { IconCheck, IconDoc, IconUpload } from "./Icons";

export interface UploadState {
  name: string;
  size: number;
  progress: number; // 0..1
  caseId?: string;
}

export function UploadZone({
  upload,
  busy,
  onFile,
}: {
  upload: UploadState | null;
  busy: boolean;
  onFile: (file: File) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);

  const take = (files: FileList | null) => {
    if (busy || !files?.length) return;
    onFile(files[0]);
  };

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        if (!busy) setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        take(e.dataTransfer.files);
      }}
      className={`flex flex-wrap items-center gap-x-5 gap-y-3 rounded-xl border border-dashed px-5 py-4 transition-colors duration-200 ${
        over ? "border-accent bg-accent-soft" : "border-line-strong bg-panel"
      }`}
    >
      <span
        className={`inline-flex size-10 shrink-0 items-center justify-center rounded-lg transition-colors ${
          over ? "bg-accent text-white" : "bg-accent-soft text-accent"
        } [&_svg]:size-5`}
      >
        <IconUpload />
      </span>

      <div className="min-w-0 flex-1">
        {upload ? (
          <>
            <p className="flex min-w-0 items-center gap-2 text-sm font-medium text-ink">
              <IconDoc className="shrink-0 text-ink-3" />
              <span className="truncate">{upload.name}</span>
              <span className="num shrink-0 text-xs font-normal text-ink-3">{bytes(upload.size)}</span>
              {upload.caseId && (
                <span className="num inline-flex shrink-0 items-center gap-1 rounded bg-ok-bg px-1.5 py-0.5 text-xs text-ok">
                  <IconCheck className="size-3" />
                  {upload.caseId}
                </span>
              )}
            </p>
            <div className="mt-2 h-1 overflow-hidden rounded-full bg-line" aria-hidden="true">
              <div
                className="h-full rounded-full bg-accent transition-[width] duration-300 ease-out"
                style={{ width: `${Math.round(upload.progress * 100)}%` }}
              />
            </div>
          </>
        ) : (
          <>
            <p className="text-sm font-medium text-ink">Drop an invoice PDF here</p>
            <p className="mt-0.5 text-[13px] text-ink-3">One file at a time. It uploads, then runs through every check straight away.</p>
          </>
        )}
      </div>

      <button
        type="button"
        disabled={busy}
        onClick={() => input.current?.click()}
        className="rounded-lg border border-line-strong bg-panel px-3.5 py-2 text-sm font-medium text-ink shadow-[0_1px_1px_rgb(16_26_46/0.05)] transition-colors hover:border-ink-3 hover:bg-sunk disabled:cursor-not-allowed disabled:opacity-50"
      >
        Choose PDF
      </button>
      <input
        ref={input}
        type="file"
        accept="application/pdf,.pdf"
        className="sr-only"
        tabIndex={-1}
        onChange={(e) => {
          take(e.target.files);
          e.target.value = "";
        }}
      />
    </div>
  );
}
