/**
 * Types transcribed from docs/api-contract.md (Phase 1, frozen).
 * Nothing here may be invented: if a field is not in the contract it does not
 * exist. Fields the contract marks `?` are optional; fields it shows as
 * `| null` are nullable but always present.
 */

/* ---------------------------------------------------------------- Session */

export interface Org {
  id: string;
  name: string;
  is_trial: boolean;
  expires_at: string | null;
}

export type UserRole = string;

export interface User {
  id: string;
  email: string;
  role: UserRole;
}

export interface SessionOut {
  authenticated: boolean;
  anonymous: boolean;
  org: Org | null;
  user: User | null;
}

export interface SignupBody {
  org_name: string;
  email: string;
  password: string;
}

export interface LoginBody {
  email: string;
  password: string;
  org_id?: string;
}

/* ---------------------------------------------------------------- Schemas */

export type FieldType =
  | "string"
  | "email"
  | "phone"
  | "number"
  | "integer"
  | "date"
  | "boolean";

export interface SchemaField {
  name: string;
  field_type: FieldType;
  required: boolean;
  description: string | null;
  position: number;
}

export interface SchemaOut {
  id: string;
  name: string;
  description: string | null;
  from_template: string | null;
  fields: SchemaField[];
}

export interface SchemaTemplate {
  name: string;
  description: string | null;
  fields: SchemaField[];
}

export type SchemaTemplateMap = Record<string, SchemaTemplate>;

/* ---------------------------------------------------------------- Uploads */

export type UploadStatus =
  | "pending"
  | "running"
  | "needs_review"
  | "complete"
  | "error";

export type Severity = "info" | "warning" | "error";

export type DiagnosticCounts = Partial<Record<Severity, number>>;

export interface UploadOut {
  id: string;
  filename: string;
  size_bytes: number;
  schema_id: string;
  status: UploadStatus;
  stage: string | null;
  error: string | null;
  required_action: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  diagnostic_counts: DiagnosticCounts;
  row_count: number | null;
}

/* ----------------------------------------------------------------- Result */

export interface MappingAlternative {
  source_column: string;
  confidence: number;
  rationale: string | null;
}

export interface ColumnMapping {
  target_field: string;
  source_column: string | null;
  confidence: number;
  method: string;
  ambiguous: boolean;
  rationale: string | null;
  alternatives: MappingAlternative[];
}

export interface Diagnostic {
  severity: Severity;
  code: string;
  message: string;
  column: string | null;
  target_field: string | null;
  rows: number[];
}

export interface ResultCell {
  value: string | number | boolean | null;
  mapped: boolean;
  source_column: string | null;
  reason: string | null;
}

export interface ResultRow {
  source_row: number;
  complete: boolean;
  fields: Record<string, ResultCell>;
  warnings: string[];
}

export interface ResultSummary {
  total_rows: number;
  complete_rows: number;
  rows_with_warnings: number;
  mapped_fields: string[];
  unmapped_fields: string[];
}

export interface ResultOut {
  upload_id: string;
  revision: number;
  llm_provider: string;
  human_overridden: boolean;
  schema: { name: string; fields: SchemaField[] };
  column_mapping: Record<string, ColumnMapping>;
  source_columns: string[];
  unmapped_source_columns: string[];
  summary: ResultSummary;
  diagnostics: Diagnostic[];
  rows: ResultRow[];
}

/** PUT /uploads/{id}/mapping body. `null` means "deliberately not mapped". */
export interface MappingOverride {
  mapping: Record<string, string | null>;
}

export type ExportFormat = "csv" | "xlsx" | "json";
