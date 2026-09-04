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
  attendance: {
    previous_missing_days: string;
    current_missing_days: string;
    missing_days_delta: string;
  };
}
