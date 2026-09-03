import type { CurrentUser, DashboardData, PayrollPeriodList } from "../api/types";

export const currentUser: CurrentUser = {
  id: "10000000-0000-0000-0000-000000000001",
  organization_id: "20000000-0000-0000-0000-000000000001",
  email: "employee@demo.local",
  roles: ["EMPLOYEE"],
  employee_id: "30000000-0000-0000-0000-000000000001",
};

export const payrollPeriods: PayrollPeriodList = {
  employee_id: currentUser.employee_id!,
  count: 2,
  periods: [
    {
      year: 2026,
      month: 2,
      payroll_id: "payroll-february",
      payroll_version_id: "version-february",
      revision_no: 1,
      status: "ACTIVE",
      is_current: true,
      gross_earnings: "100000.00",
      net_pay: "84400.00",
    },
    {
      year: 2026,
      month: 1,
      payroll_id: "payroll-january",
      payroll_version_id: "version-january",
      revision_no: 1,
      status: "ACTIVE",
      is_current: true,
      gross_earnings: "90000.00",
      net_pay: "80000.00",
    },
  ],
};

export const dashboardData: DashboardData = {
  employee_id: currentUser.employee_id!,
  period: { year: 2026, month: 2 },
  salary: {
    gross: "100000.00",
    net: "84400.00",
    previous_net: "80000.00",
    net_delta: "4400.00",
    net_delta_percent: "5.50",
  },
  earnings: {
    total: "100000.00",
    items: [
      { code: "BASE", description: "Temel Maaş", amount: "90000.00" },
      { code: "BONUS", description: "Prim", amount: "10000.00" },
    ],
  },
  deductions: {
    total: "15600.00",
    items: [
      { code: "SGK", description: "SGK İşçi Payı", amount: "10000.00" },
      { code: "TAX", description: "Gelir Vergisi", amount: "5600.00" },
    ],
  },
  attendance: { paid_days: "28.00", missing_days: "2.00" },
  tax: {
    income_tax: "5600.00",
    monthly_taxable_base: "90000.00",
    cumulative_tax_base: "190000.00",
    current_bracket_rate: "0.20",
    next_bracket_rate: "0.27",
    distance_to_next_bracket: "210000.00",
    rule_set_version: "TR_PAYROLL_2026_V1",
    current_bracket: {
      sort_order: 2,
      lower_limit: "190000.00",
      upper_limit: "400000.00",
      rate: "0.20",
    },
    next_bracket: {
      sort_order: 3,
      lower_limit: "400000.00",
      upper_limit: "1500000.00",
      rate: "0.27",
    },
  },
};
