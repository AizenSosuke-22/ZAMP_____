// Shapes returned by the FastAPI backend (backend/app/models.py, verdict.py, runner.py).

export type DecisionState = "auto_approve" | "approve_pending_review" | "flag" | "reject" | "fraud_alert";
export type OpOutcome = "pass" | "warn" | "fail" | "skipped" | "not_evaluated";

export interface OpResult {
  op_id: string;
  name: string;
  stage: string;
  tier: string;
  result: OpOutcome;
  severity: string;
  confidence: number | null;
  evidence: Record<string, unknown>;
  reason: string;
  elapsed_ms?: number | null;
}

export interface Stage {
  status: string;
  ops: OpResult[];
}

export interface Categorization {
  routing_bucket: string;
  text_source: "text_layer" | "ocr";
  page_count: number;
  ocr_mean_confidence: number | null;
  model: string;
  prompt_version: string;
  cache_hit: boolean;
  ungrounded_fields: string[];
}

export interface Invoice {
  document_type: string | null;
  vendor_name: string | null;
  vendor_gstin: string | null;
  invoice_number: string | null;
  invoice_date: string | null;
  po_reference: string | null;
  grand_total: number | null;
  currency: string | null;
  per_field_confidence: Record<string, number>;
  [key: string]: unknown;
}

export interface Dossier {
  case_id: string;
  config_version: number;
  run_started: string;
  run_ended: string | null;
  categorization: Categorization | null;
  invoice_extracted: Invoice | null;
  stages: Record<string, Stage>;
  missing_required_fields: string[];
  blocker_hit: boolean;
  timings_ms?: { categorization?: number; processing?: number; verdict?: number };
}

export interface FailedCheck {
  op_id: string;
  name: string;
  result: OpOutcome;
  severity: string;
  reason: string;
  evidence: Record<string, unknown>;
}

export interface DecisionCard {
  case_id: string;
  state: DecisionState;
  status_badge: string;
  confidence: {
    score: number;
    band: "High" | "Medium" | "Low";
    components: { fields: number; checks: number; totals: number };
  };
  routing_label: string | null;
  secondary_labels: string[];
  narrative: string;
  narrative_source: string;
  next_action: string;
  approver_role: string | null;
  policy_notes: string[];
  failed_checks: FailedCheck[];
}

export interface JournalLine {
  dr_cr: "Dr" | "Cr";
  account: string;
  account_name: string;
  cost_center: string | null;
  amount: number;
}

export interface Journal {
  status: string;
  balanced: boolean | null;
  total_debit?: number;
  total_credit?: number;
  lines: JournalLine[];
  note?: string;
}

export interface ProcessedRecord {
  case_id: string;
  decision_state: DecisionState;
  computed_journal_entry: Journal | null;
  audit: { config_version: number; decided_at: string; text_source: string; [key: string]: unknown };
  [key: string]: unknown;
}

export interface CaseDetail {
  case_id: string;
  filename: string;
  size_bytes: number;
  sha256: string;
  ingested_at: string;
  status: string;
  status_reason: string | null;
  dossier: Dossier | null;
  decision_card: DecisionCard | null;
  processed_invoice_record: ProcessedRecord | null;
  override_state: DecisionState | null;
}

export interface RunResponse {
  case_id: string;
  dossier: Dossier;
  decision_card: DecisionCard;
  processed_invoice_record: ProcessedRecord;
}

export interface CaseRow {
  case_id: string;
  filename: string;
  ingested_at: string;
  status: string;
  status_reason: string | null;
  decided_at: string | null;
  vendor_name: string | null;
  invoice_number: string | null;
  grand_total: number | null;
  decision_state: DecisionState | null;
  override_state: DecisionState | null;
  routing_label: string | null;
  confidence: number | null;
  band: string | null;
}

export interface Config {
  config_version: number;
  tolerances: { price_pct: number; qty_pct: number; total_pct: number; total_absolute_cap_inr: number };
  [key: string]: unknown;
}

export interface UploadResult {
  filename: string;
  case_id: string | null;
  sha256: string;
  status: string; // ingested | needs_human | duplicate_dropped
  duplicate_of?: string;
  status_reason?: string;
}

/** One loaded run: everything the left column renders. */
export interface RunView {
  caseId: string;
  filename: string;
  sizeBytes: number | null;
  sha256: string | null;
  uploadMs: number | null;
  dossier: Dossier;
  card: DecisionCard;
  record: ProcessedRecord;
}
