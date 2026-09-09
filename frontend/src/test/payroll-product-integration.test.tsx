import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import type { CurrentUser, DashboardData, PayrollComparison, PayrollDetail, TaxStatus } from "../api/types";
import { AuthProvider } from "../auth/AuthContext";
import { AppRoutes } from "../routes/AppRoutes";
import { decimalSign, formatMoney } from "../utils/formatters";

const authMocks = vi.hoisted(() => ({ restoreSession: vi.fn(), login: vi.fn(), logout: vi.fn() }));
const payrollMocks = vi.hoisted(() => ({
  getPayrollPeriods: vi.fn(),
  getDashboard: vi.fn(),
  getPayrollDetail: vi.fn(),
  getPayrollComparison: vi.fn(),
  getTaxStatus: vi.fn(),
  getEmployeeDashboard: vi.fn(),
  getEmployeePayrollDetail: vi.fn(),
  getEmployeePayrollComparison: vi.fn(),
  getEmployeeTaxStatus: vi.fn(),
}));

vi.mock("../api/auth", () => authMocks);
vi.mock("../api/payroll", () => payrollMocks);

const employee: CurrentUser = { id: "user-employee", organization_id: "org-1", email: "employee@example.com", roles: ["EMPLOYEE"], employee_id: "employee-1" };
const payrollAdmin: CurrentUser = { id: "user-admin", organization_id: "org-1", email: "admin@example.com", roles: ["PAYROLL_ADMIN"], employee_id: null };
const systemAdmin: CurrentUser = { ...payrollAdmin, id: "user-system", roles: ["SYSTEM_ADMIN"] };

const detail: PayrollDetail = {
  employee_id: "employee-1", year: 2026, month: 2, payroll_id: "payroll-2",
  revision: { payroll_version_id: "version-2", revision_no: 2, status: "ACTIVE", source_type: "DOCUMENT", calculation_mode: "IMPORTED", is_current: true, currency: "TRY" },
  gross: "125000.00", net: "87654.32",
  earnings: { total: "127500.25", items: [{ code: "BASE", label: "Temel Maaş", category: "SALARY", amount: "120000.00" }, { code: "BONUS", label: "Prim", category: "BONUS", amount: "7158.25" }] },
  deductions: { total: "39497.93", items: [{ code: "SGK", label: "SGK İşçi Payı", category: "STATUTORY", amount: "17500.00", is_statutory: true }, { code: "TAX", label: "Gelir Vergisi", category: "STATUTORY", amount: "19180.43", is_statutory: true }] },
  attendance: { paid_days: "28.00", missing_days: "2.00", absences: [{ reason_code: "UNPAID", description: "Ücretsiz izin", day_count: "2.00", is_paid: false, gross_effect: "-5000.00" }] },
};

const dashboard: DashboardData = {
  employee_id: "employee-1", period: { year: 2026, month: 2 },
  salary: { gross: detail.gross, net: detail.net, previous_net: "81000.00", net_delta: "6654.32", net_delta_percent: "8.22" },
  earnings: detail.earnings, deductions: detail.deductions,
  attendance: { paid_days: "28.00", missing_days: "2.00" },
  tax: { income_tax: "19180.43", monthly_taxable_base: "105000.00", cumulative_tax_base: "205000.00", current_bracket_rate: "0.20", next_bracket_rate: "0.27", distance_to_next_bracket: "195000.00", rule_set_version: "TR_PAYROLL_2026_V1", current_bracket: { sort_order: 2, lower_limit: "190000.00", upper_limit: "400000.00", rate: "0.20" }, next_bracket: { sort_order: 3, lower_limit: "400000.00", upper_limit: "1500000.00", rate: "0.27" } },
};

const comparison: PayrollComparison = {
  previous_payroll_version_id: "version-1", current_payroll_version_id: "version-2", employee_id: "employee-1", comparison_date: "2026-09-09T10:00:00Z",
  net: { previous: "81000.00", current: "87654.32", delta: "6654.32", delta_percent: "8.22" },
  earnings: { previous: "120000.00", current: "127500.25", delta: "7500.25", delta_percent: "6.25", by_code: { BONUS: { previous: "0.00", current: "7158.25", delta: "7158.25" } } },
  deductions: { previous: "39000.00", current: "39497.93", delta: "497.93", delta_percent: "1.28", by_code: {} },
  income_tax: { previous: "16500.00", current: "19180.43", delta: "2680.43", delta_percent: "16.24" },
  attendance: { previous_missing_days: "0.00", current_missing_days: "2.00", missing_days_delta: "2.00" },
};

const tax: TaxStatus = { employee_id: "employee-1", tax_year: 2026, period_month: 2, monthly_taxable_base: "105000.00", cumulative_taxable_base: "205000.00", current_bracket: dashboard.tax.current_bracket, next_bracket: dashboard.tax.next_bracket, distance_to_next_bracket: "195000.00", rule_set_version: "TR_PAYROLL_2026_V1" };

function renderRoute(path: string, actor: CurrentUser) {
  authMocks.restoreSession.mockResolvedValue(actor);
  return render(<MemoryRouter initialEntries={[path]}><AuthProvider><AppRoutes /></AuthProvider></MemoryRouter>);
}

describe("V2.2B payroll product integration", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    payrollMocks.getPayrollDetail.mockResolvedValue(detail);
    payrollMocks.getDashboard.mockResolvedValue(dashboard);
    payrollMocks.getPayrollComparison.mockResolvedValue(comparison);
    payrollMocks.getTaxStatus.mockResolvedValue(tax);
    payrollMocks.getEmployeePayrollDetail.mockResolvedValue(detail);
    payrollMocks.getEmployeeDashboard.mockResolvedValue(dashboard);
    payrollMocks.getEmployeePayrollComparison.mockResolvedValue(comparison);
    payrollMocks.getEmployeeTaxStatus.mockResolvedValue(tax);
    payrollMocks.getPayrollPeriods.mockResolvedValue({ employee_id: "employee-1", count: 1, periods: [{ year: 2026, month: 2, payroll_id: "payroll-2", payroll_version_id: "version-2", revision_no: 2, status: "ACTIVE", is_current: true, gross_earnings: "125000.00", net_pay: "87654.32" }] });
  });

  it("shows a newly materialized current payroll in employee history", async () => {
    renderRoute("/payrolls", employee);
    expect(await screen.findByText("Şubat 2026")).toBeInTheDocument();
    expect(screen.getByText("Revizyon 2")).toBeInTheDocument();
    expect(screen.getByText("87.654,32 ₺")).toBeInTheDocument();
  });

  it("preserves employee-self detail and renders authoritative detail rows", async () => {
    renderRoute("/payrolls/2026/2", employee);

    expect(await screen.findByRole("heading", { name: "Şubat 2026" })).toBeInTheDocument();
    expect(payrollMocks.getPayrollDetail).toHaveBeenCalledWith(2026, 2);
    expect(payrollMocks.getDashboard).toHaveBeenCalledWith(2026, 2);
    expect(payrollMocks.getPayrollComparison).toHaveBeenCalledWith(2026, 2);
    expect(payrollMocks.getTaxStatus).toHaveBeenCalledWith(2026, 2);
    expect(payrollMocks.getEmployeePayrollDetail).not.toHaveBeenCalled();
    expect(screen.getByText("Temel Maaş")).toBeInTheDocument();
    expect(screen.getByText("SGK İşçi Payı")).toBeInTheDocument();
    expect(screen.getByText("Ücretsiz izin")).toBeInTheDocument();
  });

  it("loads admin employee-context detail only through organization-scoped APIs", async () => {
    renderRoute("/employees/employee-1/payrolls/2026/2", payrollAdmin);

    expect(await screen.findByRole("heading", { name: "Şubat 2026" })).toBeInTheDocument();
    expect(payrollMocks.getEmployeePayrollDetail).toHaveBeenCalledWith("employee-1", 2026, 2);
    expect(payrollMocks.getEmployeeDashboard).toHaveBeenCalledWith("employee-1", 2026, 2);
    expect(payrollMocks.getEmployeePayrollComparison).toHaveBeenCalledWith("employee-1", 2026, 2);
    expect(payrollMocks.getEmployeeTaxStatus).toHaveBeenCalledWith("employee-1", 2026, 2);
    expect(payrollMocks.getPayrollDetail).not.toHaveBeenCalled();
    expect(payrollMocks.getDashboard).not.toHaveBeenCalled();
    expect(payrollMocks.getPayrollComparison).not.toHaveBeenCalled();
    expect(payrollMocks.getTaxStatus).not.toHaveBeenCalled();
  });

  it("renders backend-provided income-tax comparison values without calculating them", async () => {
    renderRoute("/payrolls/2026/2", employee);
    const incomeTaxRow = await screen.findByRole("row", { name: /Gelir Vergisi/ });

    expect(within(incomeTaxRow).getByText("19.180,43 ₺")).toBeInTheDocument();
    expect(within(incomeTaxRow).getByText("16.500,00 ₺")).toBeInTheDocument();
    expect(within(incomeTaxRow).getByText("2.680,43 ₺")).toBeInTheDocument();
    expect(within(incomeTaxRow).getByText("(16,24%)")).toBeInTheDocument();
  });

  it("shows explicit no-absence and no-previous-period states", async () => {
    payrollMocks.getPayrollDetail.mockResolvedValue({ ...detail, month: 1, attendance: { ...detail.attendance, absences: [] } });
    payrollMocks.getDashboard.mockResolvedValue({ ...dashboard, period: { year: 2026, month: 1 } });
    renderRoute("/payrolls/2026/1", employee);

    expect(await screen.findByText("Bu bordroda devamsızlık kaydı bulunmuyor.")).toBeInTheDocument();
    expect(screen.getByText("Karşılaştırılacak önceki bordro bulunamadı.")).toBeInTheDocument();
    expect(payrollMocks.getPayrollComparison).not.toHaveBeenCalled();
  });

  it("keeps SYSTEM_ADMIN out of organization-scoped payroll views", async () => {
    renderRoute("/employees/employee-1/payrolls/2026/2", systemAdmin);
    expect(await screen.findByText("Erişim izniniz yok")).toBeInTheDocument();
    expect(payrollMocks.getEmployeePayrollDetail).not.toHaveBeenCalled();
  });

  it("shows safe API errors without leaking backend detail", async () => {
    payrollMocks.getPayrollDetail.mockRejectedValue(new ApiError(500, "SELECT secret_salary"));
    renderRoute("/payrolls/2026/2", employee);
    expect(await screen.findByRole("alert")).toHaveTextContent("Sunucuya şu anda ulaşılamıyor");
    expect(screen.queryByText(/SELECT secret_salary/)).not.toBeInTheDocument();
  });

  it("formats high-precision money and signs directly from decimal strings", () => {
    expect(formatMoney("9007199254740993.17")).toBe("9.007.199.254.740.993,17 ₺");
    expect(decimalSign("9007199254740993.17")).toBe(1);
    expect(decimalSign("-0.01")).toBe(-1);
    expect(decimalSign("0.00")).toBe(0);
  });
});
