import { ApiError, apiRequest } from "./client";
import type {
  PayrollApprovalState,
  PayrollApprovalHistory,
  PayrollDetailCorrectionInput,
  PayrollDetailCorrection,
  PayrollDetailMaterialization,
  PayrollDetailReview,
  PayrollDetailSnapshot,
  PayrollImport,
  PayrollImportList,
  PayrollImportMappingSummary,
  PayrollMappedDetailList,
  PayrollMappedFieldList,
  PayrollMaterializationState,
  PayrollReview,
  PayrollReviewCorrectionInput,
  PayrollReviewSnapshot,
  PayrollValidationRun,
  PayrollValidationRunList,
} from "./types";

const base = "/api/v1/payroll-imports";

export function listPayrollImports(): Promise<PayrollImportList> {
  return apiRequest<PayrollImportList>(base);
}

export function uploadPayrollImport(file: File): Promise<PayrollImport> {
  const body = new FormData();
  body.append("file", file);
  return apiRequest<PayrollImport>(base, { method: "POST", body });
}

export function getPayrollImport(importId: string): Promise<PayrollImport> {
  return apiRequest<PayrollImport>(`${base}/${importId}`);
}

export function processPayrollImport(importId: string): Promise<PayrollImport> {
  return apiRequest<PayrollImport>(`${base}/${importId}/process`, { method: "POST" });
}

export function runScalarMapping(importId: string): Promise<PayrollImportMappingSummary> {
  return apiRequest<PayrollImportMappingSummary>(`${base}/${importId}/map`, { method: "POST" });
}

export function getMappedFields(importId: string): Promise<PayrollMappedFieldList> {
  return apiRequest<PayrollMappedFieldList>(`${base}/${importId}/mapped-fields`);
}

export function startScalarReview(importId: string): Promise<PayrollReview> {
  return apiRequest<PayrollReview>(`${base}/${importId}/review`, { method: "POST" });
}

export function getScalarReview(importId: string): Promise<PayrollReview> {
  return apiRequest<PayrollReview>(`${base}/${importId}/review`);
}

export function correctScalarField(
  importId: string,
  mappedFieldId: string,
  input: PayrollReviewCorrectionInput,
): Promise<PayrollReview> {
  return apiRequest<PayrollReview>(
    `${base}/${importId}/review/fields/${mappedFieldId}`,
    { method: "POST", body: JSON.stringify(input) },
  );
}

export function finalizeScalarReview(
  importId: string,
  expectedReviewVersion: number,
): Promise<PayrollReviewSnapshot> {
  return apiRequest<PayrollReviewSnapshot>(`${base}/${importId}/review/finalize`, {
    method: "POST",
    body: JSON.stringify({ expected_review_version: expectedReviewVersion }),
  });
}

export function runDetailMapping(importId: string): Promise<PayrollMappedDetailList> {
  return apiRequest<PayrollMappedDetailList>(`${base}/${importId}/detail-mapping`, {
    method: "POST",
  });
}

export function getMappedDetails(importId: string): Promise<PayrollMappedDetailList> {
  return apiRequest<PayrollMappedDetailList>(`${base}/${importId}/mapped-details`);
}

export function getDetailReview(importId: string): Promise<PayrollDetailReview> {
  return apiRequest<PayrollDetailReview>(`${base}/${importId}/detail-review`);
}

export function correctDetailRow(
  importId: string,
  mappedDetailId: string,
  input: PayrollDetailCorrectionInput,
): Promise<PayrollDetailCorrection> {
  return apiRequest<PayrollDetailCorrection>(
    `${base}/${importId}/detail-review/rows/${mappedDetailId}`,
    { method: "POST", body: JSON.stringify(input) },
  );
}

export function finalizeDetailReview(
  importId: string,
  expectedRowVersion: number,
): Promise<PayrollDetailSnapshot> {
  return apiRequest<PayrollDetailSnapshot>(`${base}/${importId}/detail-review/finalize`, {
    method: "POST",
    body: JSON.stringify({ expected_row_version: expectedRowVersion }),
  });
}

export function listValidations(importId: string): Promise<PayrollValidationRunList> {
  return apiRequest<PayrollValidationRunList>(`${base}/${importId}/validations`);
}

export function runValidation(
  importId: string,
  snapshotId: string,
): Promise<PayrollValidationRun> {
  return apiRequest<PayrollValidationRun>(
    `${base}/${importId}/review/snapshots/${snapshotId}/validate`,
    { method: "POST" },
  );
}

export function getApproval(importId: string): Promise<PayrollApprovalState> {
  return apiRequest<PayrollApprovalState>(`${base}/${importId}/approval`);
}

export function getApprovalHistory(importId: string): Promise<PayrollApprovalHistory> {
  return apiRequest<PayrollApprovalHistory>(`${base}/${importId}/approvals`);
}

export function acknowledgeWarning(
  importId: string,
  runId: string,
  resultId: string,
  note: string | null,
): Promise<PayrollApprovalState> {
  return apiRequest<PayrollApprovalState>(
    `${base}/${importId}/validations/${runId}/warnings/${resultId}/acknowledge`,
    { method: "POST", body: JSON.stringify({ note }) },
  );
}

export function approveImport(
  importId: string,
  runId: string,
  note: string | null,
): Promise<PayrollApprovalState> {
  return apiRequest<PayrollApprovalState>(`${base}/${importId}/validations/${runId}/approve`, {
    method: "POST",
    body: JSON.stringify({ note }),
  });
}

export function rejectImport(
  importId: string,
  runId: string,
  reason: string,
): Promise<PayrollApprovalState> {
  return apiRequest<PayrollApprovalState>(`${base}/${importId}/validations/${runId}/reject`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
}

export function getMaterialization(importId: string): Promise<PayrollMaterializationState> {
  return apiRequest<PayrollMaterializationState>(`${base}/${importId}/materialization`);
}

export function materializePayroll(
  importId: string,
  approvalId: string,
): Promise<PayrollMaterializationState["materialization"]> {
  return apiRequest<NonNullable<PayrollMaterializationState["materialization"]>>(
    `${base}/${importId}/approvals/${approvalId}/materialize`,
    { method: "POST", body: JSON.stringify({}) },
  );
}

export function getDetailMaterialization(importId: string): Promise<PayrollDetailMaterialization> {
  return apiRequest<PayrollDetailMaterialization>(`${base}/${importId}/materialization/details`);
}

export function materializeDetails(importId: string): Promise<PayrollDetailMaterialization> {
  return apiRequest<PayrollDetailMaterialization>(`${base}/${importId}/materialization/details`, {
    method: "POST",
  });
}

export async function optionalNotFound<T>(request: Promise<T>): Promise<T | null> {
  try {
    return await request;
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}
