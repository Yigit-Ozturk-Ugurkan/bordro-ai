import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  CurrentUser,
  PayrollApprovalState,
  PayrollDetailReview,
  PayrollImport,
  PayrollMappedDetailList,
  PayrollMaterializationState,
  PayrollReview,
  PayrollValidationRun,
} from "../api/types";
import { ApiError } from "../api/client";
import { AuthProvider } from "../auth/AuthContext";
import { AppRoutes } from "../routes/AppRoutes";

const authMocks = vi.hoisted(() => ({ restoreSession: vi.fn(), login: vi.fn(), logout: vi.fn() }));
const importMocks = vi.hoisted(() => ({
  listPayrollImports: vi.fn(), uploadPayrollImport: vi.fn(), getPayrollImport: vi.fn(), processPayrollImport: vi.fn(),
  runScalarMapping: vi.fn(), getMappedFields: vi.fn(), startScalarReview: vi.fn(), getScalarReview: vi.fn(), correctScalarField: vi.fn(), finalizeScalarReview: vi.fn(),
  runDetailMapping: vi.fn(), getMappedDetails: vi.fn(), getDetailReview: vi.fn(), correctDetailRow: vi.fn(), finalizeDetailReview: vi.fn(),
  listValidations: vi.fn(), runValidation: vi.fn(), getApproval: vi.fn(), getApprovalHistory: vi.fn(), acknowledgeWarning: vi.fn(), approveImport: vi.fn(), rejectImport: vi.fn(),
  getMaterialization: vi.fn(), materializePayroll: vi.fn(), getDetailMaterialization: vi.fn(), materializeDetails: vi.fn(),
  optionalNotFound: vi.fn(async <T,>(request: Promise<T>) => request),
}));

vi.mock("../api/auth", () => authMocks);
vi.mock("../api/payrollImports", () => importMocks);

const admin: CurrentUser = { id: "user-1", organization_id: "org-1", email: "admin@example.com", roles: ["PAYROLL_ADMIN"], employee_id: null };
const auditor: CurrentUser = { ...admin, id: "user-2", email: "auditor@example.com", roles: ["AUDITOR"] };
const employee: CurrentUser = { ...admin, id: "user-3", email: "employee@example.com", roles: ["EMPLOYEE"] };
const hrAdmin: CurrentUser = { ...admin, id: "user-4", email: "hr@example.com", roles: ["HR_ADMIN"] };

const payrollImport: PayrollImport = {
  id: "import-1", status: "EXTRACTED", source_type: "DOCUMENT", reader_provider: "GENERAL_READER", content_sha256: "a".repeat(64),
  detected_employee_id: "employee-1", detected_year: 2026, detected_month: 8, template_external_id: null, template_version: null, template_scope: null,
  template_match_score: null, extraction_schema_version: "1", reader_table_count: 1, reader_warning_codes: [], processing_attempt: 1,
  processing_started_at: "2026-09-09T08:00:00Z", processed_at: "2026-09-09T08:01:00Z", last_error_code: null, last_error_message: null,
  created_at: "2026-09-09T08:00:00Z", updated_at: "2026-09-09T08:01:00Z",
  document: { id: "doc-1", file_id: "file-1", original_filename: "agustos-bordro.png", declared_mime_type: "image/png", detected_mime_type: "image/png", size_bytes: 2048, sha256: "a".repeat(64), storage_provider: "LOCAL", reader_document_id: "reader-1", page_count: 1, created_at: "2026-09-09T08:00:00Z" },
};

const scalarReview: PayrollReview = {
  id: "review-1", import_id: "import-1", status: "READY_FOR_SNAPSHOT", version: 1, started_by_user_id: "user-1", started_at: "2026-09-09T08:02:00Z",
  last_reviewed_by_user_id: "user-1", last_reviewed_at: "2026-09-09T08:02:00Z", current_snapshot_id: null, complete: true, issues: [],
  fields: [{
    source: { field_id: "field-1", external_field_id: "ext-1", label: "Net Ücret", source_text: "Net Ücret 84.400,00", raw_value: "84400.00", normalized_value: "84400.00", source_value_type: "money", confidence: "0.98", page_number: 1, bbox: null, extraction_source: "reader", staging_review_status: "UNREVIEWED" },
    adapter: { mapped_field_id: "mapped-field-1", canonical_key: "net_pay", section_key: "TOTALS", mapping_status: "MAPPED", parse_status: "PARSED", typed_value: { type: "DECIMAL", value: "84400.00" }, candidate_canonical_keys: ["net_pay"], review_status: "RESOLVED", review_reason_codes: [], fingerprint: "fingerprint" },
    correction: null, correction_history: [], effective: { canonical_key: "net_pay", section_key: "TOTALS", typed_value: { type: "DECIMAL", value: "84400.00" }, provenance: "ADAPTER" }, review_status: "RESOLVED", issue_codes: [],
  }],
};

const mappedDetails: PayrollMappedDetailList = {
  import_id: "import-1", count: 1, mapping_checksum: "b".repeat(64), items: [{
    id: "mapped-row-1", source_table_id: "table-1", source_row_id: "row-1", source_table_index: 0, source_row_index: 0, mapping_id: "map-1",
    source_label: "Temel Maaş", source_values: [{ column_index: 0, source_column_id: "col-1", column_label: "Açıklama", raw_value: "Temel Maaş" }], source_checksum: "c".repeat(64),
    detail_type: "EARNING", canonical_code: "BASE", canonical_name: "Temel Maaş", category: "SALARY", amount: "100000.00", quantity: null, rate: null,
    target_values: { sgk_subject_amount: "100000.00", income_tax_subject_amount: "100000.00", stamp_tax_subject_amount: "100000.00" }, mapping_status: "MAPPED", review_required: true,
  }],
};

const detailReview: PayrollDetailReview = { import_id: "import-1", status: "IN_PROGRESS", row_version: 1, mapping_checksum: "b".repeat(64), current_snapshot_id: null, mapped_count: 1, corrected_count: 0, unresolved_count: 1, corrections: [] };

function validation(results: PayrollValidationRun["results"]): PayrollValidationRun {
  return { id: "run-1", import_id: "import-1", snapshot_id: "snapshot-1", validation_version: 1, ruleset_version: 1, status: "COMPLETED", readiness: results.some((item) => item.severity === "ERROR" || item.severity === "BLOCKING") ? "NOT_READY" : "READY_FOR_FUTURE_APPROVAL", snapshot_checksum: "d".repeat(64), result_checksum: "e".repeat(64), started_at: "2026-09-09T08:03:00Z", completed_at: "2026-09-09T08:03:01Z", created_by_user_id: "user-1", info_count: results.filter((item) => item.severity === "INFO").length, warning_count: results.filter((item) => item.severity === "WARNING").length, error_count: results.filter((item) => item.severity === "ERROR").length, blocking_count: results.filter((item) => item.severity === "BLOCKING").length, created_at: "2026-09-09T08:03:00Z", results };
}

function finding(id: string, severity: "BLOCKING" | "ERROR" | "WARNING" | "INFO") {
  return { id, validation_code: `${severity}_CHECK`, validation_version: 1, category: "STRUCTURAL", severity, message: `${severity} bulgusu`, canonical_key: null, related_snapshot_field_ids: [], expected_value: null, actual_value: null, details: {}, blocks_future_approval: severity === "BLOCKING" || severity === "ERROR", created_at: "2026-09-09T08:03:00Z" };
}

const emptyApproval: PayrollApprovalState = { import_id: "import-1", snapshot_id: "snapshot-1", validation_run_id: "run-1", validation_readiness: "READY_FOR_FUTURE_APPROVAL", approval_status: "NOT_DECIDED", decision: null, warnings: { total: 0, acknowledged: 0, remaining: 0 } };
const noMaterialization: PayrollMaterializationState = { import_id: "import-1", materialized: false, materialization: null };

function renderRoute(path: string, actor: CurrentUser = admin) {
  authMocks.restoreSession.mockResolvedValue(actor);
  return render(<MemoryRouter initialEntries={[path]}><AuthProvider><AppRoutes /></AuthProvider></MemoryRouter>);
}

function reviewDefaults() {
  importMocks.getPayrollImport.mockResolvedValue(payrollImport);
  importMocks.getScalarReview.mockResolvedValue(scalarReview);
  importMocks.getMappedDetails.mockResolvedValue(mappedDetails);
  importMocks.getDetailReview.mockResolvedValue(detailReview);
  importMocks.listValidations.mockResolvedValue({ import_id: "import-1", count: 0, items: [] });
  importMocks.getApproval.mockResolvedValue(emptyApproval);
  importMocks.getApprovalHistory.mockResolvedValue({ import_id: "import-1", approval_count: 0, acknowledgement_count: 0, approvals: [], acknowledgements: [] });
  importMocks.getMaterialization.mockResolvedValue(noMaterialization);
  importMocks.getDetailMaterialization.mockResolvedValue(null);
}

describe("V2.2A payroll import experience", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    importMocks.listPayrollImports.mockResolvedValue({ count: 0, items: [] });
    reviewDefaults();
  });

  it("lists imports for authorized users and exposes upload only to write roles", async () => {
    importMocks.listPayrollImports.mockResolvedValue({ count: 1, items: [{ id: "import-1", status: "EXTRACTED", original_filename: "agustos-bordro.png", size_bytes: 2048, content_sha256: "a".repeat(64), processing_attempt: 1, created_at: "2026-09-09T08:00:00Z", processed_at: "2026-09-09T08:01:00Z" }] });
    renderRoute("/imports");
    expect(await screen.findByText("agustos-bordro.png")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Yeni Bordro Yükle/ })).toHaveAttribute("href", "/imports/upload");
  });

  it("keeps employee users out and makes auditor access read-only", async () => {
    const first = renderRoute("/imports", employee);
    expect(await screen.findByText("Erişim izniniz yok")).toBeInTheDocument();
    first.unmount();
    renderRoute("/imports", auditor);
    expect(await screen.findByText("Henüz bordro içe aktarımı yok")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Yeni Bordro Yükle/ })).not.toBeInTheDocument();
  });

  it("uploads first and then explicitly processes through the backend flow", async () => {
    const user = userEvent.setup();
    const uploaded = { ...payrollImport, status: "UPLOADED" as const };
    importMocks.uploadPayrollImport.mockResolvedValue(uploaded);
    importMocks.processPayrollImport.mockResolvedValue(payrollImport);
    renderRoute("/imports/upload");
    const file = new File(["payroll"], "bordro.png", { type: "image/png" });
    await user.upload(await screen.findByLabelText(/Bordro belgesi seçin/), file);
    await user.click(screen.getByRole("button", { name: "Belgeyi Yükle" }));
    expect(await screen.findByText("Belge güvenle kaydedildi")).toBeInTheDocument();
    expect(importMocks.uploadPayrollImport).toHaveBeenCalledWith(file);
    await user.click(screen.getByRole("button", { name: "Belgeyi İşle" }));
    expect(importMocks.processPayrollImport).toHaveBeenCalledWith("import-1");
    expect(await screen.findByRole("link", { name: "İncelemeye Devam Et" })).toHaveAttribute("href", "/imports/import-1");
  });

  it("shows safe upload and process failures without exposing backend detail", async () => {
    const user = userEvent.setup();
    importMocks.uploadPayrollImport.mockRejectedValue(new ApiError(500, "storage path C:\\secret"));
    const view = renderRoute("/imports/upload");
    await user.upload(await screen.findByLabelText(/Bordro belgesi seçin/), new File(["x"], "bordro.pdf", { type: "application/pdf" }));
    await user.click(screen.getByRole("button", { name: "Belgeyi Yükle" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Sunucuya şu anda ulaşılamıyor");
    expect(screen.queryByText(/storage path/)).not.toBeInTheDocument();
    view.unmount();

    importMocks.uploadPayrollImport.mockResolvedValue({ ...payrollImport, status: "UPLOADED" });
    importMocks.processPayrollImport.mockRejectedValue(new ApiError(500, "reader secret"));
    renderRoute("/imports/upload");
    await user.upload(await screen.findByLabelText(/Bordro belgesi seçin/), new File(["x"], "bordro.pdf", { type: "application/pdf" }));
    await user.click(screen.getByRole("button", { name: "Belgeyi Yükle" }));
    await user.click(await screen.findByRole("button", { name: "Belgeyi İşle" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Sunucuya şu anda ulaşılamıyor");
    expect(screen.queryByText(/reader secret/)).not.toBeInTheDocument();
  });

  it("shows all validation severity levels without calculating them in the browser", async () => {
    const run = validation([finding("b", "BLOCKING"), finding("e", "ERROR"), finding("w", "WARNING"), finding("i", "INFO")]);
    importMocks.getScalarReview.mockResolvedValue({ ...scalarReview, current_snapshot_id: "snapshot-1", status: "SNAPSHOTTED" });
    importMocks.listValidations.mockResolvedValue({ import_id: "import-1", count: 1, items: [run] });
    importMocks.getApproval.mockResolvedValue({ ...emptyApproval, validation_readiness: "NOT_READY", warnings: { total: 1, acknowledged: 0, remaining: 1 } });
    renderRoute("/imports/import-1");
    expect(await screen.findByText("BLOCKING bulgusu")).toBeInTheDocument();
    expect(screen.getByText("ERROR bulgusu")).toBeInTheDocument();
    expect(screen.getByText("WARNING bulgusu")).toBeInTheDocument();
    expect(screen.getByText("INFO bulgusu")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Onayla" })).toBeDisabled();
  });

  it("saves scalar and detail human review with optimistic evidence versions", async () => {
    const user = userEvent.setup();
    let currentDetail = detailReview;
    importMocks.getDetailReview.mockImplementation(() => Promise.resolve(currentDetail));
    importMocks.correctScalarField.mockResolvedValue({ ...scalarReview, version: 2 });
    importMocks.correctDetailRow.mockImplementation((_importId, _rowId, input) => {
      currentDetail = { ...detailReview, row_version: 2, corrected_count: 1, unresolved_count: 0, corrections: [{ id: "correction-1", mapped_detail_id: "mapped-row-1", source_checksum: "c".repeat(64), revision: 1, detail_type: input.detail_type, canonical_code: input.canonical_code, canonical_name: input.canonical_name, category: input.category, amount: input.amount, quantity: input.quantity, rate: input.rate, target_values: input.target_values, ignored: input.ignored, reason: input.reason, reviewed_by_user_id: "user-1", created_at: "2026-09-09T08:05:00Z" }] };
      return Promise.resolve(currentDetail.corrections[0]);
    });
    importMocks.finalizeScalarReview.mockResolvedValue({ id: "snapshot-1" });
    importMocks.finalizeDetailReview.mockResolvedValue({ id: "detail-snapshot-1" });
    renderRoute("/imports/import-1");

    await user.click(await screen.findByRole("button", { name: /Net Ücret/ }));
    await user.type(screen.getByLabelText("Net Ücret düzeltme gerekçesi"), "Belge ile karşılaştırıldı");
    await user.click(screen.getByRole("button", { name: /Düzeltmeyi Kaydet/ }));
    expect(importMocks.correctScalarField).toHaveBeenCalledWith("import-1", "mapped-field-1", { expected_review_version: 1, canonical_key: "net_pay", value: "84400.00", reason: "Belge ile karşılaştırıldı" });

    await user.click(await screen.findByRole("button", { name: /Temel Maaş/ }));
    const detailForm = screen.getByRole("button", { name: /Satır İncelemesini Kaydet/ }).closest("form")!;
    await user.type(within(detailForm).getByLabelText("İnceleme gerekçesi"), "Satır doğrulandı");
    await user.click(within(detailForm).getByRole("button", { name: /Satır İncelemesini Kaydet/ }));
    expect(importMocks.correctDetailRow).toHaveBeenCalledWith("import-1", "mapped-row-1", expect.objectContaining({ expected_row_version: 1, expected_source_checksum: "c".repeat(64), detail_type: "EARNING", amount: "100000.00", reason: "Satır doğrulandı" }));
    await waitFor(() => expect(screen.getByRole("button", { name: /Detay İncelemesini Tamamla/ })).toBeEnabled());
  });

  it("keeps unresolved detail finalization disabled and submits explicit ignore evidence", async () => {
    const user = userEvent.setup();
    importMocks.correctDetailRow.mockResolvedValue({});
    renderRoute("/imports/import-1");
    expect(await screen.findByRole("button", { name: /Detay İncelemesini Tamamla/ })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: /Temel Maaş/ }));
    const form = screen.getByRole("button", { name: /Satır İncelemesini Kaydet/ }).closest("form")!;
    await user.click(within(form).getByLabelText("Bu satırı yok say"));
    await user.type(within(form).getByLabelText("İnceleme gerekçesi"), "Bordro detayı değil");
    await user.click(within(form).getByRole("button", { name: /Satır İncelemesini Kaydet/ }));
    expect(importMocks.correctDetailRow).toHaveBeenCalledWith("import-1", "mapped-row-1", expect.objectContaining({ detail_type: "UNMAPPED", ignored: true, canonical_code: null, amount: null, target_values: {} }));
  });

  it("keeps HR_ADMIN review actions but hides PAYROLL_ADMIN decisions", async () => {
    const run = validation([finding("warning-1", "WARNING")]);
    importMocks.getScalarReview.mockResolvedValue({ ...scalarReview, current_snapshot_id: "snapshot-1", status: "SNAPSHOTTED" });
    importMocks.listValidations.mockResolvedValue({ import_id: "import-1", count: 1, items: [run] });
    importMocks.getApproval.mockResolvedValue({ ...emptyApproval, warnings: { total: 1, acknowledged: 0, remaining: 1 } });
    renderRoute("/imports/import-1", hrAdmin);
    expect(await screen.findByRole("button", { name: "Doğrulamayı Çalıştır" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Uyarıyı Kabul Et" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Onayla" })).not.toBeInTheDocument();
    expect(screen.getByText(/yalnızca PAYROLL_ADMIN yetkisindedir/)).toBeInTheDocument();
  });

  it("reloads and explains a stale optimistic-concurrency conflict", async () => {
    const user = userEvent.setup();
    importMocks.correctScalarField.mockRejectedValue(new ApiError(409, "internal conflict detail"));
    renderRoute("/imports/import-1");
    await user.click(await screen.findByRole("button", { name: /Net Ücret/ }));
    await user.type(screen.getByLabelText("Net Ücret düzeltme gerekçesi"), "Kontrol edildi");
    await user.click(screen.getByRole("button", { name: /Düzeltmeyi Kaydet/ }));
    expect(await screen.findByText(/Başka bir değişiklik kaydedildi/)).toBeInTheDocument();
    expect(screen.queryByText("internal conflict detail")).not.toBeInTheDocument();
    expect(importMocks.getPayrollImport.mock.calls.length).toBeGreaterThan(1);
  });

  it("uses a safe generic message for import-list server failures", async () => {
    importMocks.listPayrollImports.mockRejectedValue(new ApiError(500, "SELECT * FROM payroll_secret"));
    renderRoute("/imports");
    expect(await screen.findByRole("alert")).toHaveTextContent("Sunucuya şu anda ulaşılamıyor");
    expect(screen.queryByText(/SELECT/)).not.toBeInTheDocument();
  });

  it("acknowledges warnings, approves, then materializes scalar and detail in order", async () => {
    const user = userEvent.setup();
    const run = validation([finding("warning-1", "WARNING")]);
    let acknowledged = false;
    let approved = false;
    let scalarDone = false;
    let detailDone = false;
    importMocks.getScalarReview.mockResolvedValue({ ...scalarReview, current_snapshot_id: "snapshot-1", status: "SNAPSHOTTED" });
    importMocks.getDetailReview.mockResolvedValue({ ...detailReview, status: "SNAPSHOTTED", row_version: 2, current_snapshot_id: "detail-snapshot-1", corrected_count: 1, unresolved_count: 0 });
    importMocks.listValidations.mockResolvedValue({ import_id: "import-1", count: 1, items: [run] });
    importMocks.acknowledgeWarning.mockImplementation(() => { acknowledged = true; return Promise.resolve(emptyApproval); });
    importMocks.approveImport.mockImplementation(() => { approved = true; return Promise.resolve(emptyApproval); });
    importMocks.getApproval.mockImplementation(() => Promise.resolve({ ...emptyApproval, approval_status: approved ? "APPROVED" : "NOT_DECIDED", warnings: { total: 1, acknowledged: acknowledged ? 1 : 0, remaining: acknowledged ? 0 : 1 }, decision: approved ? { id: "approval-1", snapshot_id: "snapshot-1", validation_run_id: "run-1", detail_snapshot_id: "detail-snapshot-1", detail_snapshot_checksum: "f".repeat(64), snapshot_checksum: "d".repeat(64), validation_result_checksum: "e".repeat(64), validation_ruleset_version: 1, decision: "APPROVED", decision_reason: null, acknowledged_warning_result_ids: ["warning-1"], approval_checksum: "g".repeat(64), decided_by_user_id: "user-1", decided_at: "2026-09-09T08:06:00Z" } : null }));
    importMocks.getApprovalHistory.mockImplementation(() => Promise.resolve({ import_id: "import-1", approval_count: approved ? 1 : 0, acknowledgement_count: acknowledged ? 1 : 0, approvals: [], acknowledgements: acknowledged ? [{ id: "ack-1", validation_run_id: "run-1", validation_result_id: "warning-1", acknowledged_by_user_id: "user-1", note: null, acknowledged_at: "2026-09-09T08:05:00Z" }] : [] }));
    importMocks.materializePayroll.mockImplementation(() => { scalarDone = true; return Promise.resolve({}); });
    importMocks.getMaterialization.mockImplementation(() => Promise.resolve(scalarDone ? { import_id: "import-1", materialized: true, materialization: { id: "mat-1", import_id: "import-1", approval_id: "approval-1", snapshot_id: "snapshot-1", validation_run_id: "run-1", payroll_id: "payroll-1", payroll_version_id: "version-1", revision_no: 1, version_status: "APPROVED", employee_id: "employee-1", period_year: 2026, period_month: 8, materialization_version: 1, materialization_checksum: "h".repeat(64), materialized_by_user_id: "user-1", materialized_at: "2026-09-09T08:07:00Z" } } : noMaterialization));
    importMocks.materializeDetails.mockImplementation(() => { detailDone = true; return Promise.resolve({}); });
    importMocks.getDetailMaterialization.mockImplementation(() => Promise.resolve(detailDone ? { id: "dmat-1", import_id: "import-1", detail_snapshot_id: "detail-snapshot-1", approval_id: "approval-1", payroll_materialization_id: "mat-1", payroll_id: "payroll-1", payroll_version_id: "version-1", materialization_checksum: "i".repeat(64), earning_count: 1, deduction_count: 0, absence_count: 0, materialized_by_user_id: "user-1", materialized_at: "2026-09-09T08:08:00Z", earnings: [], deductions: [], absences: [] } : null));

    renderRoute("/imports/import-1");
    await user.click(await screen.findByRole("button", { name: "Uyarıyı Kabul Et" }));
    expect(await screen.findByText("Kabul edildi")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Onayla" }));
    await user.click(await screen.findByRole("button", { name: "Skaler Bordroyu Aktar" }));
    expect(importMocks.materializePayroll).toHaveBeenCalledWith("import-1", "approval-1");
    await user.click(await screen.findByRole("button", { name: "Detayları Bordroya Aktar" }));
    expect(importMocks.materializeDetails).toHaveBeenCalledAfter(importMocks.materializePayroll);
    expect(await screen.findByRole("link", { name: /Bordroyu Gör/ })).toHaveAttribute("href", "/employees/employee-1/payrolls/2026/8");
  });
});
