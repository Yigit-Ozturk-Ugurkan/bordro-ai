import { afterEach, describe, expect, it, vi } from "vitest";

import {
  getEmployeeDashboard,
  getEmployeePayrollComparison,
  getEmployeePayrollDetail,
  getEmployeeTaxStatus,
  getPayrollDetail,
} from "../api/payroll";

describe("payroll API contexts", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("uses employee-scoped endpoints for admin context and never substitutes /me", async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(
      new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } }),
    ));
    vi.stubGlobal("fetch", fetchMock);

    await getEmployeePayrollDetail("employee-1", 2026, 2);
    await getEmployeePayrollComparison("employee-1", 2026, 2);
    await getEmployeeTaxStatus("employee-1", 2026, 2);
    await getEmployeeDashboard("employee-1", 2026, 2);

    const urls = fetchMock.mock.calls.map(([url]) => String(url));
    expect(urls).toEqual([
      "http://localhost:8001/api/v1/employees/employee-1/payrolls/2026/2",
      "http://localhost:8001/api/v1/employees/employee-1/payrolls/2026/2/comparison",
      "http://localhost:8001/api/v1/employees/employee-1/tax-status?year=2026&month=2",
      "http://localhost:8001/api/v1/employees/employee-1/dashboard/2026/2",
    ]);
    expect(urls.every((url) => !url.includes("/me/"))).toBe(true);
  });

  it("preserves the employee-self payroll detail endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);

    await getPayrollDetail(2026, 2);

    expect(fetchMock.mock.calls[0][0]).toBe(
      "http://localhost:8001/api/v1/me/payrolls/2026/2",
    );
  });
});
