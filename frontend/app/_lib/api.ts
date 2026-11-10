import type { CaseDetail, CaseRow, Config, RunResponse, UploadResult } from "./types";

export const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, init);
  } catch {
    throw new ApiError(0, `Can't reach the backend at ${API_BASE}. Is uvicorn running?`);
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {}
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => request<{ status: string; config_version: number }>("/health"),
  config: () => request<Config>("/api/config"),
  setPriceTolerance: (price_pct: number) =>
    request<Config>("/api/config", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ price_pct }),
    }),
  cases: (limit = 20) => request<{ cases: CaseRow[] }>(`/api/cases?limit=${limit}`).then((r) => r.cases),
  caseDetail: (id: string) => request<CaseDetail>(`/api/cases/${encodeURIComponent(id)}`),
  run: (id: string) => request<RunResponse>(`/api/cases/${encodeURIComponent(id)}/run`, { method: "POST" }),
};

/** Upload one PDF with progress events (fetch has no upload progress). */
export function uploadInvoice(file: File, onProgress: (fraction: number) => void): Promise<UploadResult> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/api/invoices/upload`);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onerror = () => reject(new ApiError(0, `Can't reach the backend at ${API_BASE}. Is uvicorn running?`));
    xhr.onload = () => {
      let body: { results?: UploadResult[]; detail?: string } = {};
      try {
        body = JSON.parse(xhr.responseText);
      } catch {}
      if (xhr.status >= 200 && xhr.status < 300 && body.results?.[0]) {
        onProgress(1);
        resolve(body.results[0]);
      } else reject(new ApiError(xhr.status, body.detail ?? `Upload failed (${xhr.status})`));
    };
    const form = new FormData();
    form.append("files", file);
    xhr.send(form);
  });
}
