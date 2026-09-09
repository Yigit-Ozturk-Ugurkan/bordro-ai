import { apiRequest } from "./client";
import type {
  DashboardData,
  PayrollComparison,
  PayrollDetail,
  PayrollPeriodList,
  TaxStatus,
} from "./types";

export function getPayrollPeriods(): Promise<PayrollPeriodList> {
  return apiRequest<PayrollPeriodList>("/api/v1/me/payrolls");
}

export function getDashboard(year: number, month: number): Promise<DashboardData> {
  return apiRequest<DashboardData>(`/api/v1/me/dashboard/${year}/${month}`);
}

export function getPayrollDetail(
  year: number,
  month: number,
): Promise<PayrollDetail> {
  return apiRequest<PayrollDetail>(`/api/v1/me/payrolls/${year}/${month}`);
}

export function getPayrollComparison(
  year: number,
  month: number,
): Promise<PayrollComparison> {
  return apiRequest<PayrollComparison>(
    `/api/v1/me/payrolls/${year}/${month}/comparison`,
  );
}

export function getTaxStatus(year: number, month: number): Promise<TaxStatus> {
  const query = new URLSearchParams({ year: String(year), month: String(month) });
  return apiRequest<TaxStatus>(`/api/v1/me/tax-status?${query}`);
}

function employeeBase(employeeId: string): string {
  return `/api/v1/employees/${encodeURIComponent(employeeId)}`;
}

export function getEmployeeDashboard(
  employeeId: string,
  year: number,
  month: number,
): Promise<DashboardData> {
  return apiRequest<DashboardData>(
    `${employeeBase(employeeId)}/dashboard/${year}/${month}`,
  );
}

export function getEmployeePayrollDetail(
  employeeId: string,
  year: number,
  month: number,
): Promise<PayrollDetail> {
  return apiRequest<PayrollDetail>(
    `${employeeBase(employeeId)}/payrolls/${year}/${month}`,
  );
}

export function getEmployeePayrollComparison(
  employeeId: string,
  year: number,
  month: number,
): Promise<PayrollComparison> {
  return apiRequest<PayrollComparison>(
    `${employeeBase(employeeId)}/payrolls/${year}/${month}/comparison`,
  );
}

export function getEmployeeTaxStatus(
  employeeId: string,
  year: number,
  month: number,
): Promise<TaxStatus> {
  const query = new URLSearchParams({ year: String(year), month: String(month) });
  return apiRequest<TaxStatus>(`${employeeBase(employeeId)}/tax-status?${query}`);
}
