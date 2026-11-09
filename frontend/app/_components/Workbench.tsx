"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api, uploadInvoice } from "../_lib/api";
import type { CaseRow, Config, RunView } from "../_lib/types";
import { DecisionCard } from "./DecisionCard";
import { LiveRun, opsOf, stepCount, type CollectionMeta, type Phase } from "./LiveRun";
import { RecentRuns } from "./RecentRuns";
import { SettingsPanel } from "./SettingsPanel";
import { Toaster, useToasts } from "./Toaster";
import { UploadZone, type UploadState } from "./UploadZone";

const STEP_MS = 150; // pace of the replay, per check
const SLOW_STEP_MS = 380; // Categorization and Verdict get a beat longer

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));

export default function Workbench() {
  const { toasts, notify, dismiss } = useToasts();
  const [online, setOnline] = useState<boolean | null>(null);
  const [config, setConfig] = useState<Config | null>(null);
  const [savingConfig, setSavingConfig] = useState(false);
  const [cases, setCases] = useState<CaseRow[] | null>(null);

  const [phase, setPhase] = useState<Phase>("idle");
  const [revealed, setRevealed] = useState(0);
  const [upload, setUpload] = useState<UploadState | null>(null);
  const [meta, setMeta] = useState<CollectionMeta | null>(null);
  const [view, setView] = useState<RunView | null>(null);
  const [previous, setPrevious] = useState<RunView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [runningMs, setRunningMs] = useState(0);
  const cardRef = useRef<HTMLDivElement>(null);
  const liveRef = useRef<HTMLDivElement>(null);
  const scrollOnDone = useRef(false);

  const busy = phase === "uploading" || phase === "running" || phase === "replaying";

  const refreshCases = useCallback(async () => {
    try {
      setCases(await api.cases(20));
    } catch {
      /* the connection banner covers this */
    }
  }, []);

  // Connect: health + config + runs. Retry quietly while the backend is down.
  useEffect(() => {
    let stop = false;
    let timer: ReturnType<typeof setTimeout>;
    const connect = async () => {
      try {
        await api.health();
        const [c] = await Promise.all([api.config(), refreshCases()]);
        if (stop) return;
        setConfig(c);
        setOnline(true);
      } catch {
        if (stop) return;
        setOnline(false);
        timer = setTimeout(connect, 4000);
      }
    };
    connect();
    return () => {
      stop = true;
      clearTimeout(timer);
    };
  }, [refreshCases]);

  // Live timer while the run request is in flight.
  useEffect(() => {
    if (phase !== "running") return;
    const t0 = performance.now();
    const id = setInterval(() => setRunningMs(performance.now() - t0), 100);
    return () => clearInterval(id);
  }, [phase]);

  // Replay: reveal the real results one step at a time.
  const total = view ? stepCount(opsOf(view.dossier).length) : 0;
  useEffect(() => {
    if (phase !== "replaying") return;
    const slow = revealed === 1 || revealed === total - 1;
    const t = setTimeout(() => {
      if (revealed + 1 >= total) setPhase("done");
      setRevealed(revealed + 1);
    }, slow ? SLOW_STEP_MS : STEP_MS);
    return () => clearTimeout(t);
  }, [phase, revealed, total]);

  // After a run (not when reopening a past case), bring the decision into view.
  useEffect(() => {
    if (phase !== "done" || !scrollOnDone.current) return;
    scrollOnDone.current = false;
    refreshCases(); // only now, so the list doesn't reveal the verdict before the run trace does
    cardRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [phase, refreshCases]);

  const runCase = async (m: CollectionMeta, prev: RunView | null) => {
    scrollOnDone.current = true;
    setPrevious(prev);
    setMeta(m);
    setError(null);
    setRunningMs(0);
    setRevealed(1);
    setPhase("running");
    try {
      const r = await api.run(m.caseId);
      setView({ ...m, dossier: r.dossier, card: r.decision_card, record: r.processed_invoice_record });
      setRevealed(1);
      setPhase("replaying");
    } catch (e) {
      setError(message(e));
      setPhase("error");
      notify("error", message(e));
      refreshCases();
    }
  };

  const handleFile = async (file: File) => {
    if (busy) return;
    if (!/\.pdf$/i.test(file.name) && file.type !== "application/pdf") {
      notify("error", `${file.name} isn't a PDF. Only PDF invoices are accepted.`);
      return;
    }
    setView(null);
    setPrevious(null);
    setMeta(null);
    setError(null);
    setRevealed(0);
    setUpload({ name: file.name, size: file.size, progress: 0 });
    setPhase("uploading");
    const t0 = performance.now();
    try {
      const res = await uploadInvoice(file, (p) => setUpload((u) => u && { ...u, progress: p }));
      const caseId = res.case_id ?? res.duplicate_of;
      if (!caseId) throw new ApiError(500, "Upload returned no case ID.");
      setUpload((u) => u && { ...u, caseId });
      const m: CollectionMeta = { caseId, filename: file.name, sizeBytes: file.size, sha256: res.sha256, uploadMs: performance.now() - t0 };
      if (res.status === "needs_human") {
        setMeta(m);
        setError(res.status_reason ?? "This file needs a person to look at it before it can be processed.");
        setPhase("error");
        notify("error", `${caseId} needs a person: ${res.status_reason ?? "it can't be read automatically"}.`);
        refreshCases();
        return;
      }
      if (res.status === "duplicate_dropped") notify("info", `This exact file was already received as ${caseId}. Re-running that case.`);
      await runCase(m, null);
    } catch (e) {
      setError(message(e));
      setPhase("error");
      notify("error", message(e));
    }
  };

  const openCase = async (id: string) => {
    if (busy) return;
    try {
      const c = await api.caseDetail(id);
      const m: CollectionMeta = { caseId: c.case_id, filename: c.filename, sizeBytes: c.size_bytes, sha256: c.sha256, uploadMs: null };
      setUpload(null);
      if (!c.dossier || !c.decision_card || !c.processed_invoice_record) {
        setView(null);
        notify("info", `${id} hasn't been run yet. Running it now.`);
        await runCase(m, null);
        return;
      }
      const v: RunView = { ...m, dossier: c.dossier, card: c.decision_card, record: c.processed_invoice_record };
      setPrevious(null);
      setError(null);
      setMeta(m);
      setView(v);
      setRevealed(stepCount(opsOf(v.dossier).length));
      setPhase("done");
    } catch (e) {
      notify("error", message(e));
    }
  };

  const commitTolerance = async (pct: number): Promise<boolean> => {
    setSavingConfig(true);
    try {
      const c = await api.setPriceTolerance(pct);
      setConfig(c);
      notify("success", `Config v${c.config_version} saved · price tolerance ±${c.tolerances.price_pct.toFixed(1)}%`);
      return true;
    } catch (e) {
      notify("error", `Couldn't save the setting: ${message(e)}`);
      return false;
    } finally {
      setSavingConfig(false);
    }
  };

  const rerun = () => {
    if (!view || busy) return;
    // Re-run is clicked at the bottom of the page: bring the run trace up so the checks are seen re-running.
    liveRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    runCase({ caseId: view.caseId, filename: view.filename, sizeBytes: view.sizeBytes, sha256: view.sha256, uploadMs: null }, view);
  };

  // A re-run keeps showing the previous decision (dimmed) until the new verdict is revealed.
  const verdictRevealed = view && revealed >= total && (phase === "done" || phase === "replaying");
  const cardView = verdictRevealed ? view : previous && busy ? previous : null;

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-40 bg-navy text-white">
        <div className="mx-auto flex h-14 max-w-[1440px] items-center justify-between gap-4 px-4 sm:px-6">
          <div className="flex items-baseline gap-2.5">
            <span className="text-[15px] font-semibold tracking-[-0.01em]">Invoice AP</span>
            <span className="text-sm text-[#a9b4c9]">Workbench</span>
          </div>
          <div className="flex items-center gap-4 text-[13px] text-[#c4cddd]">
            {config && (
              <span className="num hidden rounded-md bg-navy-2 px-2 py-1 sm:inline">
                config v{config.config_version} · price ±{config.tolerances.price_pct.toFixed(1)}%
              </span>
            )}
            <span className="inline-flex items-center gap-1.5">
              <span
                className={`size-2 rounded-full ${online ? "bg-ok-dot" : online === false ? "bg-bad-dot" : "bg-idle-dot"}`}
                aria-hidden="true"
              />
              {online ? "Backend connected" : online === false ? "Backend offline" : "Connecting…"}
            </span>
          </div>
        </div>
      </header>

      {online === false && (
        <div className="border-b border-bad-line bg-bad-bg">
          <p className="mx-auto max-w-[1440px] px-4 py-2.5 text-[13px] text-bad sm:px-6">
            Can&rsquo;t reach the backend at localhost:8000. Start it with{" "}
            <code className="num rounded bg-panel px-1">uvicorn app.main:app --reload</code> in <code className="num">backend/</code>. Retrying every few seconds.
          </p>
        </div>
      )}

      <main className="mx-auto grid max-w-[1440px] gap-6 px-4 py-6 sm:px-6 lg:grid-cols-[minmax(0,65fr)_minmax(0,35fr)]">
        <div className="min-w-0 space-y-6">
          <UploadZone upload={upload} busy={busy || !online} onFile={handleFile} />
          <div ref={liveRef} className="scroll-mt-20">
          <LiveRun
            phase={phase}
            revealed={revealed}
            meta={meta}
            upload={upload}
            view={view}
            previous={previous}
            runningMs={runningMs}
            error={error}
            configVersion={config?.config_version ?? null}
          />
          </div>
          {cardView && (
            <div ref={cardRef} className={`scroll-mt-20 ${verdictRevealed && !previous ? "anim-rise" : ""}`}>
              <DecisionCard view={cardView} previous={previous} pendingRerun={!verdictRevealed} />
            </div>
          )}
          <SettingsPanel
            config={config}
            saving={savingConfig}
            rerunCaseId={view?.caseId ?? null}
            lastRunVersion={view?.record.audit.config_version ?? null}
            running={busy}
            onCommit={commitTolerance}
            onRerun={rerun}
          />
        </div>

        <aside className="min-w-0 lg:sticky lg:top-20 lg:self-start">
          <RecentRuns cases={cases} activeId={view?.caseId ?? meta?.caseId ?? null} disabled={busy} onOpen={openCase} />
        </aside>
      </main>

      <Toaster toasts={toasts} dismiss={dismiss} />
    </div>
  );
}
