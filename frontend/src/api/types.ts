export type UserRole =
  | "EMPLOYEE"
  | "PAYROLL_ADMIN"
  | "HR_ADMIN"
  | "AUDITOR"
  | "SYSTEM_ADMIN";

export interface CurrentUser {
  id: string;
  organization_id: string;
  email: string;
  roles: UserRole[];
  employee_id: string | null;
}

export interface AccessTokenResponse {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
}

export interface PayrollPeriod {
  year: number;
  month: number;
  payroll_id: string;
  payroll_version_id: string | null;
  revision_no: number | null;
  status: string | null;
  is_current: boolean | null;
  gross_earnings: string | null;
  net_pay: string | null;
}

export interface PayrollPeriodList {
  employee_id: string;
  count: number;
  periods: PayrollPeriod[];
}

export interface MoneyLine {
  code: string;
  description?: string;
  label?: string;
  category?: string;
  amount: string;
  is_statutory?: boolean;
}

export interface TaxBracket {
  sort_order: number;
  lower_limit: string;
  upper_limit: string | null;
  rate: string;
}

export interface DashboardData {
  employee_id: string;
  period: { year: number; month: number };
  salary: {
    gross: string;
    net: string;
    previous_net: string | null;
    net_delta: string | null;
    net_delta_percent: string | null;
  };
  earnings: { items: MoneyLine[]; total: string };
  deductions: { items: MoneyLine[]; total: string };
  attendance: { paid_days: string; missing_days: string };
  tax: {
    income_tax: string;
    monthly_taxable_base: string | null;
    cumulative_tax_base: string;
    current_bracket_rate: string | null;
    next_bracket_rate: string | null;
    distance_to_next_bracket: string | null;
    rule_set_version: string | null;
    current_bracket: TaxBracket | null;
    next_bracket: TaxBracket | null;
  };
}

export interface PayrollDetail {
  employee_id: string;
  year: number;
  month: number;
  payroll_id: string;
  revision: {
    payroll_version_id: string;
    revision_no: number;
    status: string;
    source_type: string;
    calculation_mode: string;
    is_current: boolean;
    currency: string;
  };
  gross: string;
  net: string;
  earnings: { items: MoneyLine[]; total: string };
  deductions: { items: MoneyLine[]; total: string };
  attendance: {
    paid_days: string;
    missing_days: string;
    absences: Array<{
      reason_code: string;
      description: string | null;
      day_count: string;
      is_paid: boolean;
      gross_effect: string | null;
    }>;
  };
}

export interface TaxStatus {
  employee_id: string;
  tax_year: number;
  period_month: number | null;
  monthly_taxable_base: string | null;
  cumulative_taxable_base: string;
  current_bracket: TaxBracket | null;
  next_bracket: TaxBracket | null;
  distance_to_next_bracket: string | null;
  rule_set_version: string;
}

interface ComparisonAmounts {
  previous: string;
  current: string;
  delta: string;
  delta_percent?: string | null;
}

export interface PayrollComparison {
  previous_payroll_version_id: string;
  current_payroll_version_id: string;
  employee_id: string;
  comparison_date: string;
  net: ComparisonAmounts & { delta_percent: string | null };
  earnings: ComparisonAmounts & {
    delta_percent: string | null;
    by_code: Record<string, ComparisonAmounts>;
  };
  deductions: ComparisonAmounts & {
    delta_percent: string | null;
    by_code: Record<string, ComparisonAmounts>;
  };
  income_tax: ComparisonAmounts & { delta_percent: string | null };
  attendance: {
    previous_missing_days: string;
    current_missing_days: string;
    missing_days_delta: string;
  };
}

export type PayrollImportStatus =
  | "UPLOADED"
  | "PROCESSING"
  | "EXTRACTED"
  | "REVIEW_REQUIRED"
  | "FAILED"
  | "REJECTED";

export type MappingStatus = "MAPPED" | "UNMAPPED" | "AMBIGUOUS" | "PARSE_FAILED";
export type ParseStatus = "PARSED" | "NOT_APPLICABLE" | "FAILED";
export type ReviewStatus = "IN_PROGRESS" | "READY_FOR_SNAPSHOT" | "SNAPSHOTTED";
export type ReviewFieldStatus = "PENDING" | "RESOLVED" | "STALE";
export type DetailType = "EARNING" | "DEDUCTION" | "ABSENCE" | "UNMAPPED";
export type ValidationSeverity = "BLOCKING" | "ERROR" | "WARNING" | "INFO";
export type ValidationReadiness = "READY_FOR_FUTURE_APPROVAL" | "NOT_READY";
export type ApprovalStatus = "NOT_DECIDED" | "APPROVED" | "REJECTED";

export interface PayrollImportDocument {
  id: string;
  file_id: string;
  original_filename: string;
  declared_mime_type: string;
  detected_mime_type: string;
  size_bytes: number;
  sha256: string;
  storage_provider: string;
  reader_document_id: string | null;
  page_count: number | null;
  created_at: string;
}

export interface PayrollImport {
  id: string;
  status: PayrollImportStatus;
  source_type: string;
  reader_provider: string;
  content_sha256: string;
  detected_employee_id: string | null;
  detected_year: number | null;
  detected_month: number | null;
  template_external_id: string | null;
  template_version: number | null;
  template_scope: string | null;
  template_match_score: string | null;
  extraction_schema_version: string | null;
  reader_table_count: number;
  reader_warning_codes: string[];
  processing_attempt: number;
  processing_started_at: string | null;
  processed_at: string | null;
  last_error_code: string | null;
  last_error_message: string | null;
  created_at: string;
  updated_at: string;
  document: PayrollImportDocument;
}

export interface PayrollImportListItem {
  id: string;
  status: PayrollImportStatus;
  original_filename: string;
  size_bytes: number;
  content_sha256: string;
  processing_attempt: number;
  created_at: string;
  processed_at: string | null;
}

export interface PayrollImportList {
  count: number;
  items: PayrollImportListItem[];
}

export interface TypedValue {
  type: "DECIMAL" | "INTEGER" | "DAY_COUNT" | "DATE" | "TEXT" | "IDENTIFIER";
  value: string | number;
}

export interface PayrollMappedField {
  id: string;
  source_field_id: string;
  source_external_field_id: string;
  source_label: string;
  raw_value: string | null;
  canonical_key: string | null;
  section_key: string | null;
  mapping_id: string | null;
  mapping_version: number | null;
  typed_value: TypedValue | null;
  candidate_canonical_keys: string[];
  mapping_status: MappingStatus;
  parse_status: ParseStatus;
  review_status: string;
  review_reason_codes: string[];
}

export interface PayrollMappedFieldList {
  import_id: string;
  count: number;
  items: PayrollMappedField[];
}

export interface PayrollImportMappingSummary {
  import_id: string;
  source_field_count: number;
  mapped_count: number;
  unmapped_count: number;
  ambiguous_count: number;
  parse_failed_count: number;
  missing_count: number;
  review_required_count: number;
  issues: Array<{
    canonical_key: string;
    section_key: string;
    target_value_type: TypedValue["type"];
    issue_code: string;
    review_status: string;
  }>;
}

export interface PayrollReviewSource {
  field_id: string;
  external_field_id: string;
  label: string;
  source_text: string | null;
  raw_value: string | null;
  normalized_value: string | null;
  source_value_type: string | null;
  confidence: string | null;
  page_number: number | null;
  bbox: unknown[] | null;
  extraction_source: string | null;
  staging_review_status: string;
}

export interface PayrollReviewField {
  source: PayrollReviewSource;
  adapter: {
    mapped_field_id: string;
    canonical_key: string | null;
    section_key: string | null;
    mapping_status: MappingStatus;
    parse_status: ParseStatus;
    typed_value: TypedValue | null;
    candidate_canonical_keys: string[];
    review_status: string;
    review_reason_codes: string[];
    fingerprint: string;
  };
  correction: {
    id: string;
    revision: number;
    action: "APPLY" | "REVERT";
    canonical_key: string | null;
    typed_value: TypedValue | null;
    reviewer_user_id: string;
    reason: string;
    created_at: string;
    is_stale: boolean;
  } | null;
  correction_history: unknown[];
  effective: {
    canonical_key: string | null;
    section_key: string | null;
    typed_value: TypedValue | null;
    provenance: "ADAPTER" | "REVIEWER_CORRECTION" | null;
  };
  review_status: ReviewFieldStatus;
  issue_codes: string[];
}

export interface PayrollReview {
  id: string;
  import_id: string;
  status: ReviewStatus;
  version: number;
  started_by_user_id: string;
  started_at: string;
  last_reviewed_by_user_id: string;
  last_reviewed_at: string;
  current_snapshot_id: string | null;
  complete: boolean;
  issues: Array<{ code: string; canonical_key: string | null; source_field_id: string | null }>;
  fields: PayrollReviewField[];
}

export interface PayrollReviewCorrectionInput {
  expected_review_version: number;
  canonical_key?: string | null;
  value: string;
  reason: string;
}

export interface PayrollReviewSnapshot {
  id: string;
  import_id: string;
  review_id: string;
  snapshot_version: number;
  created_by_user_id: string;
  created_at: string;
  source_staging_checksum: string;
  adapter_output_checksum: string;
  review_corrections_checksum: string;
  snapshot_checksum: string;
  field_count: number;
  issue_count: number;
  fields: unknown[];
}

export interface SourceValue {
  column_index: number;
  source_column_id: string;
  column_label: string;
  raw_value: string | null;
}

export interface PayrollMappedDetail {
  id: string;
  source_table_id: string;
  source_row_id: string;
  source_table_index: number;
  source_row_index: number;
  mapping_id: string | null;
  source_label: string | null;
  source_values: SourceValue[];
  source_checksum: string;
  detail_type: DetailType;
  canonical_code: string | null;
  canonical_name: string | null;
  category: string | null;
  amount: string | null;
  quantity: string | null;
  rate: string | null;
  target_values: Record<string, unknown>;
  mapping_status: MappingStatus;
  review_required: boolean;
}

export interface PayrollMappedDetailList {
  import_id: string;
  count: number;
  mapping_checksum: string | null;
  items: PayrollMappedDetail[];
}

export interface PayrollDetailCorrection {
  id: string;
  mapped_detail_id: string;
  source_checksum: string;
  revision: number;
  detail_type: DetailType;
  canonical_code: string | null;
  canonical_name: string | null;
  category: string | null;
  amount: string | null;
  quantity: string | null;
  rate: string | null;
  target_values: Record<string, unknown>;
  ignored: boolean;
  reason: string;
  reviewed_by_user_id: string;
  created_at: string;
}

export interface PayrollDetailReview {
  import_id: string;
  status: ReviewStatus;
  row_version: number;
  mapping_checksum: string;
  current_snapshot_id: string | null;
  mapped_count: number;
  corrected_count: number;
  unresolved_count: number;
  corrections: PayrollDetailCorrection[];
}

export interface PayrollDetailCorrectionInput {
  expected_row_version: number;
  expected_source_checksum: string;
  detail_type: DetailType;
  canonical_code: string | null;
  canonical_name: string | null;
  category: string | null;
  amount: string | null;
  quantity: string | null;
  rate: string | null;
  target_values: Record<string, unknown>;
  ignored: boolean;
  reason: string;
}

export interface PayrollDetailSnapshot {
  id: string;
  import_id: string;
  revision: number;
  mapping_checksum: string;
  corrections_checksum: string;
  snapshot_checksum: string;
  row_count: number;
  finalized_by_user_id: string;
  finalized_at: string;
  rows: unknown[];
}

export interface PayrollValidationResult {
  id: string;
  validation_code: string;
  validation_version: number;
  category: string;
  severity: ValidationSeverity;
  message: string;
  canonical_key: string | null;
  related_snapshot_field_ids: string[];
  expected_value: string | null;
  actual_value: string | null;
  details: Record<string, unknown>;
  blocks_future_approval: boolean;
  created_at: string;
}

export interface PayrollValidationRun {
  id: string;
  import_id: string;
  snapshot_id: string;
  validation_version: number;
  ruleset_version: number;
  status: "RUNNING" | "COMPLETED" | "FAILED";
  readiness: ValidationReadiness;
  snapshot_checksum: string;
  result_checksum: string;
  started_at: string;
  completed_at: string;
  created_by_user_id: string;
  info_count: number;
  warning_count: number;
  error_count: number;
  blocking_count: number;
  created_at: string;
  results: PayrollValidationResult[];
}

export interface PayrollValidationRunList {
  import_id: string;
  count: number;
  items: PayrollValidationRun[];
}

export interface PayrollApprovalState {
  import_id: string;
  snapshot_id: string | null;
  validation_run_id: string | null;
  validation_readiness: ValidationReadiness | null;
  approval_status: ApprovalStatus;
  decision: {
    id: string;
    snapshot_id: string;
    validation_run_id: string;
    detail_snapshot_id: string | null;
    detail_snapshot_checksum: string | null;
    snapshot_checksum: string;
    validation_result_checksum: string;
    validation_ruleset_version: number;
    decision: "APPROVED" | "REJECTED";
    decision_reason: string | null;
    acknowledged_warning_result_ids: string[];
    approval_checksum: string;
    decided_by_user_id: string;
    decided_at: string;
  } | null;
  warnings: { total: number; acknowledged: number; remaining: number };
}

export interface PayrollWarningAcknowledgement {
  id: string;
  validation_run_id: string;
  validation_result_id: string;
  acknowledged_by_user_id: string;
  note: string | null;
  acknowledged_at: string;
}

export interface PayrollApprovalHistory {
  import_id: string;
  approval_count: number;
  acknowledgement_count: number;
  approvals: NonNullable<PayrollApprovalState["decision"]>[];
  acknowledgements: PayrollWarningAcknowledgement[];
}

export interface PayrollMaterialization {
  id: string;
  import_id: string;
  approval_id: string;
  snapshot_id: string;
  validation_run_id: string;
  payroll_id: string;
  payroll_version_id: string;
  revision_no: number;
  version_status: string;
  employee_id: string;
  period_year: number;
  period_month: number;
  materialization_version: number;
  materialization_checksum: string;
  materialized_by_user_id: string;
  materialized_at: string;
}

export interface PayrollMaterializationState {
  import_id: string;
  materialized: boolean;
  materialization: PayrollMaterialization | null;
}

export interface PayrollDetailMaterialization {
  id: string;
  import_id: string;
  detail_snapshot_id: string;
  approval_id: string;
  payroll_materialization_id: string;
  payroll_id: string;
  payroll_version_id: string;
  materialization_checksum: string;
  earning_count: number;
  deduction_count: number;
  absence_count: number;
  materialized_by_user_id: string;
  materialized_at: string;
  earnings: unknown[];
  deductions: unknown[];
  absences: unknown[];
}
